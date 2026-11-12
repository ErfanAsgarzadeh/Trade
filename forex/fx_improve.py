#!/usr/bin/env python3
"""Test every improvement hypothesis from fx_diagnose.py on the 5-bot basket.

Variants are fixed in advance (small set per hypothesis).  Thresholds of data-driven filters are
computed on 2021-11..2024-12 ONLY.  A variant is ACCEPTED only if
    bot Sharpe improves in-sample (2021-24) AND out-of-sample (2025-26), and
    the basket's out-of-sample CAGR does not fall.
H1 Nasdaq stochastic : profit lock after +1R  (lock 0 / 0.1 / 0.5 R; arm 0.75 R variant)
H2 Gold inside bar   : flat before the weekend
H3 USDJPY supertrend : profit lock (0.75/0.1, 1/0.1, 1/0.5, 1.5/0.5) or ATR chandelier trail (3, 4)
H4 USDJPY supertrend : flat before the weekend
H5 Gotobi            : skip Thursday gotobi days; skip weak-trend days (lowest in-sample tercile)
H6 Month-end         : skip pairs that are over-extended before entry (top in-sample tercile)
H7 S&P stochastic    : no change (control)
Output: reports/improve/improve.json, charts
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flow_bot as fb  # noqa: E402
import fx_diagnose as dg  # noqa: E402
import fx_lab as fl  # noqa: E402
import portfolio_proposal as pp  # noqa: E402
from fx_search_dd import SYMBOLS  # noqa: E402

OUT = HERE / "reports" / "improve"
SPLIT = pd.Timestamp("2025-01-01")


def stats(x, days):
    eq = np.cumprod(1 + x)
    yrs = len(x) / 365.25
    return dict(cagr=round(float(eq[-1] ** (1 / yrs) - 1), 4),
                max_dd=round(float(np.max(1 - eq / np.maximum.accumulate(eq))), 4),
                sharpe=round(float(x.mean() / x.std() * np.sqrt(365.25)), 3) if x.std() > 0 else 0.0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lab = fl.Lab(HERE / "data", SYMBOLS)
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    days = pd.to_datetime((np.arange(lab.ndays) + day0) * fl.DAY_MS, unit="ms")
    IS, OOS = days < SPLIT, days >= SPLIT
    spec = {b[0]: b for b in pp.BOTS}

    def engine_stream(name, ex_override):
        _, risk, sym, tf, fam, sp, ex = spec[name]
        b = lab.get_bars(sym, tf)
        daily, _, tr = lab.run(sym, tf, fl.FAM[fam](b, sp), {**ex, **ex_override})
        return risk * daily, tr

    def flow_stream(t, strat):
        g = t[t.strategy == strat]
        x = np.zeros(lab.ndays)
        np.add.at(x, (g.exit_ms // fl.DAY_MS - day0).astype(int).to_numpy(), (fb.ALLOC[strat] * g.R).to_numpy())
        return x

    # ---------- baseline streams
    base = {}
    for name in spec:
        base[name], _ = engine_stream(name, {})
    ft = fb.trades()
    base["Gotobi"] = flow_stream(ft, "E2_gotobi_long_usdjpy")
    base["Month-end"] = flow_stream(ft, "E4_month_end_rebalance")

    # ---------- variants
    variants = []  # (hypothesis, bot, label, stream)
    nas, st, gold = "Nasdaq 4h Stochastic", "USDJPY 1h Supertrend", "Gold D1 inside bar"
    for arm, lock in ((1.0, 0.0), (1.0, 0.1), (1.0, 0.5), (0.75, 0.1)):
        variants.append(("H1", nas, f"lock {lock}R after +{arm}R", engine_stream(nas, {"arm_r": arm, "lock_r": lock})[0]))
    variants.append(("H2", gold, "flat before weekend", engine_stream(gold, {"weekend_flat": True})[0]))
    for arm, lock in ((0.75, 0.1), (1.0, 0.1), (1.0, 0.5), (1.5, 0.5)):
        variants.append(("H3", st, f"lock {lock}R after +{arm}R", engine_stream(st, {"arm_r": arm, "lock_r": lock})[0]))
    for k in (3.0, 4.0):
        variants.append(("H3", st, f"ATR chandelier trail {k:g}", engine_stream(st, {"trail_mode": 2, "chand_k": k})[0]))
    variants.append(("H4", st, "flat before weekend", engine_stream(st, {"weekend_flat": True})[0]))

    # flow-bot filters need entry context
    g = ft[ft.strategy == "E2_gotobi_long_usdjpy"].copy()
    d1 = dg.context_bars(lab.get_bars("USDJPY", "D1"))
    ci = np.searchsorted(d1.close_ms.to_numpy(), g.entry_ms.to_numpy(), side="right") - 1
    g["trend"] = d1.trend_atr.to_numpy()[ci]  # gotobi is always long USDJPY -> aligned = raw
    g["wd"] = pd.to_datetime(g.entry_ms, unit="ms").dt.dayofweek
    g_is = pd.to_datetime(g.exit_ms, unit="ms") < SPLIT
    thr_tr = np.nanquantile(g.trend[g_is], 1 / 3)
    for label, keep in (("skip Thursday gotobi", g.wd != 2),
                        (f"skip weak trend (< {thr_tr:.2f} ATR from EMA200, in-sample tercile)", g.trend >= thr_tr),
                        ("both filters", (g.wd != 2) & (g.trend >= thr_tr))):
        t2 = pd.concat([ft[ft.strategy != "E2_gotobi_long_usdjpy"], g[keep]])
        variants.append(("H5", "Gotobi", label, flow_stream(t2, "E2_gotobi_long_usdjpy")))
    m = ft[ft.strategy == "E4_month_end_rebalance"].copy()
    ext = np.full(len(m), np.nan)
    for sym in m.symbol.unique():
        cb = dg.context_bars(lab.get_bars(sym, "D1"))
        idx = np.where(m.symbol == sym)[0]
        k = np.searchsorted(cb.close_ms.to_numpy(), m.entry_ms.to_numpy()[idx], side="right") - 1
        ext[idx] = m.side.to_numpy()[idx] * cb.ext10_atr.to_numpy()[k]
    m["ext"] = ext
    m_is = pd.to_datetime(m.exit_ms, unit="ms") < SPLIT
    thr_ext = np.nanquantile(m.ext[m_is], 2 / 3)
    t2 = pd.concat([ft[ft.strategy != "E4_month_end_rebalance"], m[~(m.ext > thr_ext)]])
    variants.append(("H6", "Month-end", f"skip over-extended pairs (> {thr_ext:.2f} ATR, in-sample tercile)",
                     flow_stream(t2, "E4_month_end_rebalance")))

    # ---------- evaluate
    def basket(streams):
        x = sum(streams.values())
        return {"full": stats(x, days), "is": stats(x[IS], days[IS]), "oos": stats(x[OOS], days[OOS])}

    b0 = basket(base)
    rows = []
    for hyp, bot, label, x in variants:
        bs, vs = base[bot], x
        r = dict(hypothesis=hyp, bot=bot, variant=label,
                 base_is=stats(bs[IS], days[IS]), var_is=stats(vs[IS], days[IS]),
                 base_oos=stats(bs[OOS], days[OOS]), var_oos=stats(vs[OOS], days[OOS]))
        nb = dict(base)
        nb[bot] = vs
        r["basket"] = basket(nb)
        r["accepted"] = bool(r["var_is"]["sharpe"] > r["base_is"]["sharpe"] and r["var_oos"]["sharpe"] > r["base_oos"]["sharpe"]
                             and r["basket"]["oos"]["cagr"] >= b0["oos"]["cagr"])
        rows.append(r)
    # best accepted variant per bot -> improved basket
    best = {}
    for r, (_, _, _, x) in zip(rows, variants):
        if r["accepted"] and (r["bot"] not in best or r["var_is"]["sharpe"] > best[r["bot"]][0]["var_is"]["sharpe"]):
            best[r["bot"]] = (r, x)  # pick among accepted by IN-SAMPLE Sharpe
    improved = dict(base)
    for bot, (r, x) in best.items():
        improved[bot] = x
    b1 = basket(improved)
    rep = dict(rules=__doc__, baseline_basket=b0, improved_basket=b1,
               adopted={bot: r["variant"] for bot, (r, _) in best.items()}, tests=rows)
    (OUT / "improve.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(f"{'hyp':4s} {'bot':22s} {'variant':58s} {'IS Sh base->var':>18s} {'OOS Sh base->var':>18s} {'basket OOS CAGR':>16s} ok")
    for r in rows:
        print(f"{r['hypothesis']:4s} {r['bot']:22s} {r['variant'][:58]:58s} "
              f"{r['base_is']['sharpe']:+.2f} -> {r['var_is']['sharpe']:+.2f}   {r['base_oos']['sharpe']:+.2f} -> {r['var_oos']['sharpe']:+.2f}   "
              f"{b0['oos']['cagr']:+.3f}->{r['basket']['oos']['cagr']:+.3f} {'YES' if r['accepted'] else '-'}")
    print("baseline basket", b0)
    print("improved basket", b1, rep["adopted"])
    chart(base, improved, days, b0, b1, rep["adopted"])


def chart(base, improved, days, b0, b1, adopted):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mt
    import matplotlib.dates as mdates
    import fx_charts as fc
    e0, e1 = np.cumprod(1 + sum(base.values())), np.cumprod(1 + sum(improved.values()))
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    axs[0].plot(days, e0, color=fc.SER[1], label=f"before: {b0['full']['cagr']:+.1%}/yr, DD {b0['full']['max_dd']:.1%}")
    axs[0].plot(days, e1, color=fc.SER[0], label=f"after: {b1['full']['cagr']:+.1%}/yr, DD {b1['full']['max_dd']:.1%}")
    axs[0].axvline(SPLIT, color=fc.NEUTRAL, lw=1, ls="--")
    axs[0].yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
    axs[0].legend(loc="upper left")
    axs[0].set_title("Basket before vs after the accepted changes (dashed line: start of the 2025-26 check)")
    for e, col in ((e0, fc.SER[1]), (e1, fc.SER[0])):
        axs[1].plot(days, e / np.maximum.accumulate(e) - 1, color=col, lw=1.2)
    axs[1].yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    axs[1].set_title("Drawdown", fontsize=11)
    axs[1].xaxis.set_major_locator(mdates.YearLocator())
    axs[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.savefig(OUT / "01_basket_before_after.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
