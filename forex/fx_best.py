#!/usr/bin/env python3
"""Thousands of technical + price-action strategies on 15 symbols; best single strategies and
best combinations by five-year return.  No drawdown limit; every trade risks <= 1 % of equity.

Families: Shahin, Mojsavar, Ghoghnous, Bollinger fade, RSI(2), London/Asia range, TSMOM,
inside bar, MACD, Supertrend, Keltner, Stochastic, MA cross, ADX breakout, Heikin-Ashi,
pin bar, engulfing (fx_lab.py).

Portfolios (equity[d+1] = equity[d] * (1 + sum_i w_i * 1% * R_i[d]), w_i <= 1):
  P1 greedy max-CAGR   add the stream that most raises 5-year log growth (up to 40)
  P2 greedy max-Sharpe add the stream that most raises Sharpe (up to 40)
  P3 top-50 decorrelated (corr < 0.6) by Sharpe, equal weight
  P4 broad inverse-vol: best 400 by Sharpe, weights ~ 1/vol scaled so max weight = 1
Every portfolio is picked with hindsight on the full five years (what was asked), and the
same rule is re-run in an anchored yearly walk-forward (pick on [start, Y), trade Y) as a
reality check.  Outputs: reports/fx_best.json, data/fx_best_streams.npz, data/fx_best_meta.json
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
from fx_search_dd import SYMBOLS, corr_filter, maxdd, sharpe  # noqa: E402

RISK = 0.01
TEST_YEARS = (2023, 2024, 2025, 2026)
LAB = None


def init():
    global LAB
    LAB = fl.Lab(HERE / "data", SYMBOLS)


def work(item):
    idx, fam, tf, sp, ex = item
    out = []
    for s in SYMBOLS:
        b = LAB.get_bars(s, tf)
        daily, levd, tr = LAB.run(s, tf, fl.FAM[fam](b, sp), ex)
        r = tr[:, 3] if len(tr) else np.zeros(0)
        out.append((idx, s, daily.astype(np.float32), len(tr),
                    float(r.mean()) if len(r) else 0.0, float((r > 0).mean()) if len(r) else 0.0,
                    float(r.max()) if len(r) else 0.0, float(r.min()) if len(r) else 0.0))
    return out


def growth(R, w=None):
    x = R if w is None else (R * w[:, None]).sum(0)
    g = 1 + RISK * x
    return np.log(np.clip(g, 1e-9, None)).sum()


def greedy_cagr(S, pool, k_max=40):
    chosen, total, best = [], np.zeros(S.shape[1]), 0.0
    P = S[pool]
    for _ in range(k_max):
        g = np.log(np.clip(1 + RISK * (total[None, :] + P), 1e-9, None)).sum(1)
        g[[pool.index(c) for c in chosen]] = -np.inf
        j = int(np.argmax(g))
        if g[j] <= best + 1e-6:
            break
        chosen.append(pool[j]); total += S[pool[j]]; best = g[j]
    return chosen, np.ones(len(chosen))


def greedy_sharpe(S, pool, k_max=40):
    chosen, total, best = [], np.zeros(S.shape[1]), -1e9
    P = S[pool]
    for _ in range(k_max):
        X = total[None, :] + P
        v = X.mean(1) / (X.std(1) + 1e-12)
        v[[pool.index(c) for c in chosen]] = -np.inf
        j = int(np.argmax(v))
        if v[j] <= best + 1e-5:
            break
        chosen.append(pool[j]); total += S[pool[j]]; best = v[j]
    return chosen, np.ones(len(chosen))


def portfolio(name, S, trades):
    sh = S.mean(1) / (S.std(1) + 1e-12) * np.sqrt(365.25)
    ok = (trades >= 30) & (sh > 0)
    idx = np.where(ok)[0]
    order = list(idx[np.argsort(-sh[idx])])
    if name == "P1_greedy_max_cagr":
        pool = corr_filter(S, order[:4000], 0.9, 1500)
        return greedy_cagr(S, pool)
    if name == "P2_greedy_max_sharpe":
        pool = corr_filter(S, order[:4000], 0.9, 1500)
        return greedy_sharpe(S, pool)
    if name == "P3_top50_decorrelated":
        ch = corr_filter(S, order[:4000], 0.6, 50)
        return ch, np.ones(len(ch))
    if name == "P4_broad_invvol":
        ch = order[:400]
        w = 1 / (S[ch].std(1) + 1e-12)
        return ch, w / w.max()
    raise KeyError(name)


PORTS = ("P1_greedy_max_cagr", "P2_greedy_max_sharpe", "P3_top50_decorrelated", "P4_broad_invvol")


def stats(x, days):
    eq = np.cumprod(np.clip(1 + RISK * x, 1e-9, None))
    yrs = len(x) / 365.25
    ser = pd.Series(eq, index=days)
    ye = ser.groupby(ser.index.year).last()
    return dict(cagr=round(float(eq[-1] ** (1 / yrs) - 1), 4), total=round(float(eq[-1] - 1), 4),
                max_dd=round(maxdd(eq), 4), sharpe=round(sharpe(x), 2),
                yearly={int(k): round(float(v), 4) for k, v in (ye / ye.shift(1).fillna(1.0) - 1).items()})


def main():
    t0 = time.time()
    items = [(i, *x) for i, x in enumerate(fl.families())]
    print(f"{len(items)} configs x {len(SYMBOLS)} symbols = {len(items) * len(SYMBOLS)} strategies", flush=True)
    with Pool(os.cpu_count(), initializer=init) as pool:
        res = [r for chunk in pool.imap(work, items, chunksize=2) for r in chunk]
    print(f"simulated in {time.time() - t0:.0f}s", flush=True)
    S = np.stack([r[2] for r in res]).astype(np.float64)
    meta = []
    for r in res:
        fam, tf, sp, ex = items[r[0]][1:]
        meta.append(dict(idx=r[0], symbol=r[1], family=fam, tf=tf, trades=r[3], avg_r=round(r[4], 4),
                         win=round(r[5], 3), best_r=round(r[6], 2), worst_r=round(r[7], 2),
                         params={k: (list(v) if isinstance(v, tuple) else v) for k, v in sp.items()}, exits=ex))
    del res
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    days = pd.to_datetime((np.arange(S.shape[1]) + day0) * fl.DAY_MS, unit="ms")
    yr = days.year.values
    trades = np.array([m["trades"] for m in meta])
    np.savez_compressed(HERE / "data" / "fx_best_streams.npz", S=S.astype(np.float32))
    (HERE / "data" / "fx_best_meta.json").write_text(json.dumps(meta))

    # ---------- single strategies
    yrs = len(days) / 365.25
    final = np.exp(np.log(np.clip(1 + RISK * S, 1e-9, None)).sum(1))
    cagr = final ** (1 / yrs) - 1
    sh = S.mean(1) / (S.std(1) + 1e-12) * np.sqrt(365.25)
    for j, m in enumerate(meta):
        m["cagr_1pct"], m["sharpe"] = round(float(cagr[j]), 4), round(float(sh[j]), 2)
    eligible = np.where(trades >= 30)[0]
    top_cagr = eligible[np.argsort(-cagr[eligible])][:25]
    top_sh = eligible[np.argsort(-sh[eligible])][:25]
    single = []
    for j in top_cagr:
        m = dict(meta[j])
        m.update(stats(S[j], days))
        m["is_2021_2024"] = stats(S[j, yr < 2025], days[yr < 2025])["cagr"]
        m["oos_2025_2026"] = stats(S[j, yr >= 2025], days[yr >= 2025])["cagr"]
        single.append(m)

    # ---------- family / symbol overview
    fam_over = {}
    for fam in fl.FAM:
        js = [j for j in eligible if meta[j]["family"] == fam]
        if js:
            best = max(js, key=lambda j: cagr[j])
            fam_over[fam] = dict(strategies=len(js), share_profitable=round(float(np.mean(cagr[js] > 0)), 3),
                                 median_cagr=round(float(np.median(cagr[js])), 4), best_cagr=round(float(cagr[best]), 4),
                                 best=f"{meta[best]['symbol']} {meta[best]['tf']}")
    sym_over = {}
    for s in SYMBOLS:
        js = [j for j in eligible if meta[j]["symbol"] == s]
        sym_over[s] = dict(share_profitable=round(float(np.mean(cagr[js] > 0)), 3),
                           median_cagr=round(float(np.median(cagr[js])), 4), best_cagr=round(float(cagr[js].max()), 4))

    # ---------- portfolios: hindsight + walk-forward
    ports, curves = {}, {}
    for name in PORTS:
        ch, w = portfolio(name, S, trades)
        x = (S[ch] * w[:, None]).sum(0)
        p = stats(x, days)
        p.update(strategies=len(ch), weights_sum=round(float(w.sum()), 2),
                 members=[dict(meta[j], weight=round(float(wt), 3)) for j, wt in zip(ch, w)][:60])
        # contributions
        contrib_sym, contrib_fam = {}, {}
        for j, wt in zip(ch, w):
            v = float(wt * S[j].sum())
            contrib_sym[meta[j]["symbol"]] = contrib_sym.get(meta[j]["symbol"], 0) + v
            contrib_fam[meta[j]["family"]] = contrib_fam.get(meta[j]["family"], 0) + v
        p["contribution_R_by_symbol"] = {k: round(v, 1) for k, v in sorted(contrib_sym.items(), key=lambda a: -a[1])}
        p["contribution_R_by_family"] = {k: round(v, 1) for k, v in sorted(contrib_fam.items(), key=lambda a: -a[1])}
        # walk-forward with the same rule
        parts, rows = [], []
        for Y in TEST_YEARS:
            tr_mask, te_mask = yr < Y, yr == Y
            cw, ww = portfolio(name, S[:, tr_mask], np.array([m["trades"] for m in meta]))
            xt = (S[cw][:, te_mask] * ww[:, None]).sum(0)
            eq = np.cumprod(np.clip(1 + RISK * xt, 1e-9, None))
            rows.append(dict(year=Y, ret=round(float(eq[-1] - 1), 4), max_dd=round(maxdd(eq), 4)))
            parts.append(xt)
        xo = np.concatenate(parts)
        p["walk_forward"] = dict(years=rows, **{k: v for k, v in stats(xo, days[yr >= 2023]).items()})
        ports[name] = p
        curves[name] = dict(hindsight=x.astype(np.float32), wf=xo.astype(np.float32), members=ch, weights=w)
        print(name, "hindsight", p["cagr"], p["max_dd"], "| walk-forward", p["walk_forward"]["cagr"],
              p["walk_forward"]["max_dd"], flush=True)

    np.savez_compressed(HERE / "data" / "fx_best_curves.npz",
                        **{f"{k}_{a}": v[a] for k, v in curves.items() for a in ("hindsight", "wf")},
                        **{f"{k}_members": np.array(v["members"]) for k, v in curves.items()},
                        **{f"{k}_weights": v["weights"] for k, v in curves.items()})
    report = dict(strategies=int(S.shape[0]), configs=len(items), symbols=SYMBOLS,
                  period=[str(days[0].date()), str(days[-1].date())], risk_per_trade=RISK,
                  share_profitable_all=round(float(np.mean(cagr[eligible] > 0)), 3),
                  top25_single_by_cagr=single,
                  top25_single_by_sharpe=[{k: meta[j][k] for k in ("symbol", "family", "tf", "params", "exits", "trades",
                                                                   "cagr_1pct", "sharpe")} for j in top_sh],
                  family_overview=fam_over, symbol_overview=sym_over, portfolios=ports,
                  runtime_s=round(time.time() - t0, 1))
    (HERE / "reports" / "fx_best.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
