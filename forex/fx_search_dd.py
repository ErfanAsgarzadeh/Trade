#!/usr/bin/env python3
"""Multi-asset strategy search with a max-drawdown objective and rolling walk-forward.

Goal: highest return with max drawdown < 10 %.

1. every fx_lab family/parameter set on every symbol (FX majors, crosses, gold, silver,
   S&P 500, Nasdaq 100) -> daily R streams (costs included)
2. six portfolio-combination methods are compared in an anchored yearly walk-forward:
   for test year Y, pick on [start, Y) only, set risk so the TRAIN drawdown = 8 %, trade Y
   untouched; years are chained into one out-of-sample equity curve (2023-01 .. 2026-11)
3. the same methods on the full period (hindsight, optimistic) for reference

Outputs: reports/fx_dd_search.json ; data/fx_dd_streams.npz (not committed)
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
import instruments as ins  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "XAUUSD", "XAGUSD", "SPXUSD", "NSXUSD")
TEST_YEARS = (2023, 2024, 2025, 2026)
TRAIN_DD = 0.08
DD_LIMIT = 0.10
LAB = None


def init():
    global LAB
    LAB = fl.Lab(HERE / "data", SYMBOLS)


def work(item):
    idx, fam, tf, sp, ex = item
    out = []
    for s in SYMBOLS:
        b = LAB.get_bars(s, tf)
        sig = fl.FAM[fam](b, sp)
        daily, levd, tr = LAB.run(s, tf, sig, ex)
        out.append((idx, s, daily.astype(np.float32), levd.astype(np.float32), len(tr)))
    return out


# ------------------------------------------------------------------ metrics
def curve(r, f):
    return np.cumprod(1 + f * r)


def maxdd(eq):
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(np.max(1 - eq / peak)) if len(eq) else 0.0


def sharpe(x):
    sd = x.std()
    return float(x.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0


def risk_for_dd(r, dd, fmax=0.25):
    if maxdd(curve(r, fmax)) <= dd:
        return fmax
    lo, hi = 0.0, fmax
    for _ in range(40):
        mid = (lo + hi) / 2
        g = 1 + mid * r
        if (g <= 0).any() or maxdd(np.cumprod(g)) > dd:
            hi = mid
        else:
            lo = mid
    return lo


# ------------------------------------------------------------------ combination methods
def corr_filter(S, idx, thr, cap):
    if not idx:
        return []
    X = S[idx]
    X = (X - X.mean(1, keepdims=True)) / (X.std(1, keepdims=True) + 1e-12)
    C = X @ X.T / X.shape[1]
    kept = []
    for a in range(len(idx)):
        if all(C[a, b] < thr for b in kept):
            kept.append(a)
            if len(kept) >= cap:
                break
    return [idx[a] for a in kept]


def greedy(S, pool, k_max):
    chosen, total, best = [], np.zeros(S.shape[1]), -1e9
    for _ in range(k_max):
        cand, cval = None, best
        for j in pool:
            if j in chosen:
                continue
            x = total + S[j]
            sd = x.std()
            if sd > 0 and x.mean() / sd > cval + 1e-4:
                cand, cval = j, x.mean() / sd
        if cand is None:
            break
        chosen.append(cand)
        total += S[cand]
        best = cval
    return chosen, np.ones(len(chosen))


def eligible(S, meta, yr, train_years, min_trades=30, min_sh=0.5, every_year=False):
    sh = S.mean(1) / (S.std(1) + 1e-12) * np.sqrt(365.25)
    ok = (sh > min_sh) & (np.array([m["trades"] for m in meta]) >= min_trades)
    if every_year:
        for y in train_years:
            ok &= S[:, yr == y].sum(1) > 0
    idx = np.where(ok)[0]
    return list(idx[np.argsort(-sh[idx])]), sh


def method(name, S, meta, yr, train_years):
    if name == "M1_greedy25":
        pool, _ = eligible(S, meta, yr, train_years)
        pool = corr_filter(S, pool[:3000], 0.9, 800)
        return greedy(S, pool, 25)
    if name == "M2_greedy40_every_year":
        pool, _ = eligible(S, meta, yr, train_years, every_year=True)
        pool = corr_filter(S, pool[:3000], 0.9, 800)
        return greedy(S, pool, 40)
    if name == "M3_top50_decorrelated":
        pool, _ = eligible(S, meta, yr, train_years)
        ch = corr_filter(S, pool[:3000], 0.6, 50)
        return ch, np.ones(len(ch))
    if name == "M4_broad_equal":
        pool, _ = eligible(S, meta, yr, train_years, min_sh=0.8)
        ch = pool[:400]
        return ch, np.ones(len(ch))
    if name == "M5_broad_invvol":
        pool, _ = eligible(S, meta, yr, train_years, min_sh=0.8)
        ch = pool[:400]
        vol = S[ch].std(1)
        w = 1 / (vol + 1e-9)
        return ch, w / w.mean()
    if name == "M6_bots_all_symbols":
        # a bot = one parameter set traded on EVERY symbol (no symbol cherry-picking)
        ns = len(SYMBOLS)
        B = S.reshape(-1, ns, S.shape[1]).sum(1)
        bmeta = [{"trades": sum(meta[i * ns + k]["trades"] for k in range(ns))} for i in range(B.shape[0])]
        pool, _ = eligible(B, bmeta, yr, train_years, min_trades=60, min_sh=0.3)
        pool = corr_filter(B, pool[:2000], 0.9, 500)
        chb, w = greedy(B, pool, 12)
        ch = [i * ns + k for i in chb for k in range(ns)]
        return ch, np.ones(len(ch))
    raise KeyError(name)


METHODS = ("M1_greedy25", "M2_greedy40_every_year", "M3_top50_decorrelated", "M4_broad_equal",
           "M5_broad_invvol", "M6_bots_all_symbols")


def describe(meta, items, ch, w):
    out = []
    for j, wt in zip(ch, w):
        m = meta[j]
        fam, tf, sp, ex = items[m["idx"]][1:]
        out.append(dict(symbol=m["symbol"], family=fam, tf=tf, weight=round(float(wt), 3),
                        params={k: (list(v) if isinstance(v, tuple) else v) for k, v in sp.items()}, exits=ex,
                        trades=m["trades"]))
    return out


def main():
    t0 = time.time()
    items = [(i, *x) for i, x in enumerate(fl.families())]
    print(f"{len(items)} configs x {len(SYMBOLS)} symbols = {len(items) * len(SYMBOLS)} streams", flush=True)
    with Pool(os.cpu_count(), initializer=init) as pool:
        res = [r for chunk in pool.imap(work, items, chunksize=2) for r in chunk]
    print(f"simulated in {time.time() - t0:.0f}s", flush=True)
    S = np.stack([r[2] for r in res])
    LV = np.stack([r[3] for r in res])
    meta = [dict(idx=r[0], symbol=r[1], trades=r[4]) for r in res]
    del res
    np.savez_compressed(HERE / "data" / "fx_dd_streams.npz", S=S, LV=LV)
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    nd = S.shape[1]
    days = pd.to_datetime((np.arange(nd) + day0) * fl.DAY_MS, unit="ms")
    yr = days.year.values
    S64 = S.astype(np.float64)

    # ---------------- per symbol / family overview (full period, single streams)
    sh_all = S64.mean(1) / (S64.std(1) + 1e-12) * np.sqrt(365.25)
    overview = {}
    for s in SYMBOLS:
        js = [j for j, m in enumerate(meta) if m["symbol"] == s and m["trades"] >= 30]
        overview[s] = dict(streams=len(js), share_sharpe_gt_0=round(float(np.mean(sh_all[js] > 0)), 3),
                           share_sharpe_gt_1=round(float(np.mean(sh_all[js] > 1)), 3),
                           best_sharpe=round(float(sh_all[js].max()), 2))
    fam_over = {}
    for fam in fl.FAM:
        js = [j for j, m in enumerate(meta) if items[m["idx"]][1] == fam and m["trades"] >= 30]
        fam_over[fam] = dict(streams=len(js), share_sharpe_gt_0=round(float(np.mean(sh_all[js] > 0)), 3),
                             share_sharpe_gt_1=round(float(np.mean(sh_all[js] > 1)), 3))

    # ---------------- walk-forward
    wf = {}
    for name in METHODS:
        eq_parts, rows = [], []
        level = 1.0
        for Y in TEST_YEARS:
            tr = yr < Y
            te = yr == Y
            tr_years = sorted(set(yr[tr]) - {2021})
            ch, w = method(name, S64[:, tr], meta, yr[tr], tr_years)
            if not ch:
                rows.append(dict(year=Y, bots=0))
                continue
            R = (S64[ch] * w[:, None]).sum(0)
            f = risk_for_dd(R[tr], TRAIN_DD)
            eq = curve(R[te], f)
            lev = (LV[ch].astype(np.float64) * w[:, None]).sum(0)[te] * f
            rows.append(dict(year=Y, streams=len(ch), risk_per_trade=round(f, 5),
                             train_cagr=round(float(curve(R[tr], f)[-1] ** (365.25 / tr.sum()) - 1), 3),
                             test_return=round(float(eq[-1] - 1), 4), test_maxdd=round(maxdd(eq), 4),
                             test_sharpe=round(sharpe(R[te]), 2), max_leverage=round(float(lev.max()), 1)))
            eq_parts.append(level * eq)
            level *= eq[-1]
        oos = np.concatenate(eq_parts) if eq_parts else np.ones(1)
        years = len(oos) / 365.25
        wf[name] = dict(years=rows, oos_cagr=round(float(oos[-1] ** (1 / years) - 1), 4),
                        oos_maxdd=round(maxdd(oos), 4), oos_total=round(float(oos[-1] - 1), 4),
                        meets_dd_limit=bool(maxdd(oos) < DD_LIMIT))
        print(name, wf[name]["oos_cagr"], wf[name]["oos_maxdd"], flush=True)

    # ---------------- full-period (hindsight) books at DD = 10 %
    full = {}
    all_years = sorted(set(yr) - {2021})
    for name in METHODS:
        ch, w = method(name, S64, meta, yr, all_years)
        R = (S64[ch] * w[:, None]).sum(0)
        f = risk_for_dd(R, DD_LIMIT * 0.99)
        eq = curve(R, f)
        lev = (LV[ch].astype(np.float64) * w[:, None]).sum(0) * f
        ys = pd.Series(eq, index=days)
        ye = ys.groupby(ys.index.year).last()
        yearly = (ye / ye.shift(1).fillna(1.0) - 1).round(4)
        full[name] = dict(streams=len(ch), risk_per_trade=round(f, 5),
                          cagr=round(float(eq[-1] ** (365.25 / nd) - 1), 4), maxdd=round(maxdd(eq), 4),
                          sharpe=round(sharpe(R), 2), max_leverage=round(float(lev.max()), 1),
                          p99_leverage=round(float(np.percentile(lev, 99)), 1),
                          yearly={int(k): float(v) for k, v in yearly.items()},
                          members=describe(meta, items, ch, w)[:60])
        print("full", name, full[name]["cagr"], full[name]["maxdd"], flush=True)

    best_wf = max(METHODS, key=lambda n: wf[n]["oos_cagr"] if wf[n]["oos_maxdd"] < DD_LIMIT else -1 + wf[n]["oos_cagr"])
    report = dict(symbols=SYMBOLS, streams=int(S.shape[0]), configs=len(items),
                  period=[str(days[0].date()), str(days[-1].date())],
                  objective=f"max return subject to max drawdown < {DD_LIMIT:.0%} (daily marks)",
                  walk_forward_rule=f"anchored yearly; risk set so the TRAIN drawdown = {TRAIN_DD:.0%}",
                  symbol_overview=overview, family_overview=fam_over,
                  walk_forward=wf, best_walk_forward_method=best_wf, full_period_hindsight=full,
                  costs_pip_spread_slip_comm={s: list(ins.SPEC[s]) for s in SYMBOLS},
                  runtime_s=round(time.time() - t0, 1))
    (HERE / "reports" / "fx_dd_search.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    print("best walk-forward method:", best_wf, wf[best_wf]["oos_cagr"], wf[best_wf]["oos_maxdd"])
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
