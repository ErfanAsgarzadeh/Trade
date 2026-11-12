#!/usr/bin/env python3
"""Search thousands of FX strategies and combine them into multi-bot portfolios.

1. run every family/parameter set of fx_lab on each pair -> daily R streams
2. portfolio A ("best five-year"): greedy pick on the FULL period (in-sample, optimistic)
   portfolio B (honest): greedy pick on 2021-11..2024-12 only, then tested on 2025-01..2026-11
3. scale risk per trade so the combined book reaches the target CAGR; report drawdown and
   leverage that this requires.

Outputs forex/reports/fx_search.json (+ fx_search_streams.npz, not committed).
"""
from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_lab as fl  # noqa: E402

PAIRS = fl.PAIRS
IS_END = "2025-01-01"
TARGET_CAGR = 1.00
LAB = None


def init():
    global LAB
    LAB = fl.Lab(HERE / "data")


def work(item):
    idx, fam, tf, sp, ex = item
    out = []
    for p in PAIRS:
        b = LAB.get_bars(p, tf)
        sig = fl.FAM[fam](b, sp)
        daily, levd, tr = LAB.run(p, tf, sig, ex)
        out.append((idx, p, daily.astype(np.float32), levd.astype(np.float32), len(tr),
                    float(np.mean(tr[:, 3])) if len(tr) else 0.0, float(np.mean(tr[:, 3] > 0)) if len(tr) else 0.0))
    return out


def stats(r, lev=None, f=0.01, years=None):
    """Equity path with risk f per 1R."""
    g = 1 + f * r
    if (g <= 0).any():
        return dict(cagr=-1.0, dd=1.0, sharpe=0.0, final=0.0)
    eq = np.cumprod(g)
    years = years or len(r) / 365.25
    cagr = eq[-1] ** (1 / years) - 1
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = float(np.max(1 - eq / peak))
    tr_days = r[r != 0]
    sh = float(np.mean(r) / np.std(r) * np.sqrt(365.25)) if np.std(r) > 0 else 0.0
    out = dict(cagr=float(cagr), dd=dd, sharpe=sh, final=float(eq[-1]))
    if lev is not None:
        out["max_lev"] = float(np.max(lev) * f)
        out["p99_lev"] = float(np.percentile(lev[lev > 0], 99) * f) if (lev > 0).any() else 0.0
    return out


def risk_for(r, target, years, fmax=0.2):
    lo, hi = 0.0, fmax
    if stats(r, f=hi, years=years)["cagr"] < target:
        # growth is not monotone in f (Kelly): return the growth-maximising f
        fs = np.linspace(0.001, fmax, 200)
        c = [stats(r, f=x, years=years)["cagr"] for x in fs]
        return float(fs[int(np.argmax(c))]), False
    for _ in range(50):
        mid = (lo + hi) / 2
        if stats(r, f=mid, years=years)["cagr"] < target:
            lo = mid
        else:
            hi = mid
    return hi, True


def greedy(S, pool_idx, k_max=25, min_gain=0.005):
    """Pick streams maximising the Sharpe of their equal-risk sum."""
    chosen = []
    total = np.zeros(S.shape[1])
    best = -1e9
    for _ in range(k_max):
        cand, cval = None, best
        for j in pool_idx:
            if j in chosen:
                continue
            x = total + S[j]
            sd = x.std()
            if sd == 0:
                continue
            v = x.mean() / sd
            if v > cval + min_gain / np.sqrt(365.25):
                cand, cval = j, v
        if cand is None:
            break
        chosen.append(cand)
        total += S[cand]
        best = cval
    return chosen


def main():
    t0 = time.time()
    items = [(i, *x) for i, x in enumerate(fl.families())]
    print(f"{len(items)} configs x {len(PAIRS)} pairs", flush=True)
    with Pool(os.cpu_count(), initializer=init) as pool:
        res = [r for chunk in pool.imap(work, items, chunksize=4) for r in chunk]
    print(f"simulated in {time.time() - t0:.0f}s", flush=True)
    init()
    day0, nd = LAB.day0, LAB.ndays
    days = pd.to_datetime((np.arange(nd) + day0) * fl.DAY_MS, unit="ms")
    S = np.stack([r[2] for r in res]).astype(np.float64)
    LV = np.stack([r[3] for r in res]).astype(np.float64)
    meta = [dict(idx=r[0], pair=r[1], trades=r[4], avg_r=r[5], win=r[6]) for r in res]
    for m in meta:
        fam, tf, sp, ex = items[m["idx"]][1:]
        m.update(family=fam, tf=tf, params={k: (list(v) if isinstance(v, tuple) else v) for k, v in sp.items()},
                 exits=ex)
    split = int(np.searchsorted(days.values, np.datetime64(IS_END)))
    yrs_full, yrs_is, yrs_oos = nd / 365.25, split / 365.25, (nd - split) / 365.25

    def sharpe(x):
        return float(x.mean() / x.std() * np.sqrt(365.25)) if x.std() > 0 else 0.0

    for j, m in enumerate(meta):
        m["sh_full"], m["sh_is"], m["sh_oos"] = sharpe(S[j]), sharpe(S[j, :split]), sharpe(S[j, split:])
        m["r_full"], m["r_is"], m["r_oos"] = float(S[j].sum()), float(S[j, :split].sum()), float(S[j, split:].sum())

    # ---------- per family summary
    fam_sum = {}
    for fam in fl.FAM:
        js = [j for j, m in enumerate(meta) if m["family"] == fam and m["trades"] >= 20]
        if not js:
            continue
        best = max(js, key=lambda j: meta[j]["sh_full"])
        best_is = max(js, key=lambda j: meta[j]["sh_is"])
        fam_sum[fam] = dict(
            streams=len(js),
            share_positive_full=round(float(np.mean([meta[j]["r_full"] > 0 for j in js])), 3),
            share_positive_oos=round(float(np.mean([meta[j]["r_oos"] > 0 for j in js])), 3),
            best_full={k: meta[best][k] for k in ("pair", "tf", "params", "exits", "trades", "sh_full", "r_full", "sh_oos")},
            best_in_sample_then_oos={k: meta[best_is][k] for k in ("pair", "tf", "params", "exits", "trades", "sh_is", "r_is", "sh_oos", "r_oos")})

    def build(period_end, label):
        sl = slice(0, period_end)
        pool_idx = [j for j, m in enumerate(meta)
                    if m["trades"] >= 25 and (m["sh_full"] if period_end == nd else m["sh_is"]) > 0.4]
        # drop near-duplicates (corr > 0.9) keeping the higher Sharpe
        key = "sh_full" if period_end == nd else "sh_is"
        pool_idx.sort(key=lambda j: -meta[j][key])
        kept = []
        for j in pool_idx:
            ok = True
            for k in kept[-400:]:
                a, b = S[j, sl], S[k, sl]
                if a.std() > 0 and b.std() > 0 and np.corrcoef(a, b)[0, 1] > 0.9:
                    ok = False
                    break
            if ok:
                kept.append(j)
            if len(kept) >= 600:
                break
        chosen = greedy(S[:, sl], kept)
        R = S[chosen].sum(axis=0)
        Lv = LV[chosen].sum(axis=0)
        yrs = period_end / 365.25
        f, reach = risk_for(R[sl], TARGET_CAGR, yrs)
        out = dict(label=label, candidates=len(kept), bots=len(chosen),
                   members=[{k: meta[j][k] for k in ("family", "pair", "tf", "params", "exits", "trades",
                                                     "sh_full", "sh_is", "sh_oos")} for j in chosen],
                   risk_per_trade_for_target=round(f, 5), target_reached_in_selection_period=reach)
        for name, s_ in (("full", slice(0, nd)), ("in_sample", slice(0, split)), ("out_of_sample", slice(split, nd))):
            y = (s_.stop - s_.start) / 365.25
            out[name] = {"at_target_risk": stats(R[s_], LV[chosen].sum(axis=0)[s_], f, y),
                         "at_1pct_per_bot": stats(R[s_], Lv[s_], 0.01, y),
                         "at_0.25pct_per_bot": stats(R[s_], Lv[s_], 0.0025, y)}
            ser = pd.Series(np.cumprod(1 + f * R[s_]), index=days[s_])
            out[name]["yearly_at_target_risk"] = {int(k): round(float(v), 4) for k, v in
                                                  (ser.groupby(ser.index.year).last() /
                                                   ser.groupby(ser.index.year).last().shift(1).fillna(1.0) - 1).items()}
        out["sharpe_full"] = sharpe(R)
        out["sharpe_is"] = sharpe(R[:split])
        out["sharpe_oos"] = sharpe(R[split:])
        out["equity_full_at_target"] = [[str(d.date()), round(float(v), 4)]
                                        for d, v in zip(days[::7], np.cumprod(1 + f * R)[::7])]
        return out, chosen

    A, chosenA = build(nd, "A: picked on full 5 years (in-sample)")
    B, chosenB = build(split, "B: picked on 2021-11..2024-12, tested 2025-01..2026-11")
    # Risk needed for the honest portfolio to make 100 % over the whole span (hindsight sizing)
    RB = S[chosenB].sum(axis=0)
    fB, okB = risk_for(RB, TARGET_CAGR, yrs_full)
    B["full_period_risk_for_100pct"] = {"risk": round(fB, 5), "reached": okB,
                                        **stats(RB, LV[chosenB].sum(axis=0), fB, yrs_full)}
    top = sorted(range(len(meta)), key=lambda j: -meta[j]["sh_full"])[:40]
    report = {
        "period": [str(days[0].date()), str(days[-1].date())], "split": IS_END,
        "streams": len(meta), "configs": len(items),
        "costs": vars(LAB.costs) if hasattr(LAB.costs, "__dict__") else str(LAB.costs),
        "families": fam_sum,
        "portfolio_A_full_period_pick": A, "portfolio_B_walk_forward": B,
        "top40_single_streams_full": [{k: meta[j][k] for k in ("family", "pair", "tf", "params", "exits", "trades",
                                                              "avg_r", "win", "sh_full", "sh_is", "sh_oos", "r_full")}
                                      for j in top],
        "note": "Streams are in R (1R = planned risk incl. costs). Daily marks; intraday DD is larger. "
                "Equity: eq[d+1]=eq[d]*(1+risk*sum R[d]); each bot gets the same risk per trade.",
        "runtime_s": round(time.time() - t0, 1),
    }
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / "fx_search.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    np.savez_compressed(HERE / "data" / "fx_search_streams.npz", S=S.astype(np.float32), LV=LV.astype(np.float32))
    for P in (A, B):
        print(P["label"], P["bots"], "risk", P["risk_per_trade_for_target"])
        for k in ("full", "in_sample", "out_of_sample"):
            print("  ", k, {a: round(b, 3) for a, b in P[k]["at_target_risk"].items()})
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
