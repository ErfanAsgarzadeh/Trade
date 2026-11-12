#!/usr/bin/env python3
"""Charts for fx_tf.py -> reports/charts_tf/*.png"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_charts as fc  # noqa: E402  (shared style)
import fx_lab as fl  # noqa: E402
from fx_search_dd import SYMBOLS  # noqa: E402

OUT = HERE / "reports" / "charts_tf"
SER, SURF, INK2, NEUTRAL = fc.SER, fc.SURF, fc.INK2, fc.NEUTRAL
RISK = 0.01


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def eq_of(x):
    return np.cumprod(np.clip(1 + RISK * x, 1e-9, None))


def years_axis(ax):
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def name_of(c):
    return f"{c['symbol']} {c['tf']} {c['family']}"


def main():
    rep = json.loads((HERE / "reports" / "fx_tf.json").read_text())
    S_old = np.load(HERE / "data" / "fx_best_streams.npz")["S"]
    S_new = np.load(HERE / "data" / "fx_tf_streams.npz")["S"]
    final = rep["finalists_distinct"]
    rows = []
    for c in final:
        j = c["j"]
        rows.append(S_old[j] if j < len(S_old) else S_new[j - len(S_old)])
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    nd = S_old.shape[1]
    days = pd.to_datetime((np.arange(nd) + day0) * fl.DAY_MS, unit="ms")
    split = pd.Timestamp("2025-01-01")

    # 1 share profitable by timeframe, in-sample vs out-of-sample
    bt = rep["by_timeframe"]
    tfs = list(bt)
    x = np.arange(len(tfs))
    fig, ax = plt.subplots(figsize=(10, 4.4))
    a = ax.bar(x - 0.2, [bt[t]["share_profitable_is"] for t in tfs], 0.38, color=SER[0], label="2021-11 to 2024-12",
               edgecolor=SURF, linewidth=2)
    b = ax.bar(x + 0.2, [bt[t]["share_profitable_oos"] for t in tfs], 0.38, color=SER[1], label="2025-01 to 2026-11",
               edgecolor=SURF, linewidth=2)
    for bars in (a, b):
        for r in bars:
            ax.annotate(f"{r.get_height():.0%}", (r.get_x() + r.get_width() / 2, r.get_height()), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, [f"{t}\n(n={bt[t]['strategies']:,})" for t in tfs], fontsize=8)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_title("Share of profitable strategies by timeframe (after costs)", pad=28)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    save(fig, "01_profitable_share_by_timeframe.png")

    # 2 selected vs chance
    fig, ax = plt.subplots(figsize=(7, 3.6))
    vals = [rep["selected_in_sample"]] + rep["selected_by_chance_null"]
    labels = ["real data"] + [f"no-edge copy {i + 1}" for i in range(len(rep["selected_by_chance_null"]))]
    cols = [SER[0]] + [NEUTRAL] * len(rep["selected_by_chance_null"])
    ax.barh(labels[::-1], vals[::-1], color=cols[::-1], height=0.6, edgecolor=SURF, linewidth=2)
    for i, v in enumerate(vals[::-1]):
        ax.annotate(f"{v:,}", (v, i), xytext=(4, 0), textcoords="offset points", va="center", fontsize=9, color=INK2)
    ax.grid(axis="y", visible=False)
    ax.set_title("Strategies passing the in-sample rules: real vs pure luck")
    save(fig, "02_selected_vs_luck.png")

    if not final:
        return
    top = final[:8]
    # 3 small multiples of the finalists
    n = len(top)
    cols_n = 4 if n > 4 else n
    rows_n = int(np.ceil(n / cols_n))
    fig, axs = plt.subplots(rows_n, cols_n, figsize=(4 * cols_n, 3.4 * rows_n), sharey=True, squeeze=False)
    for ax, c, r in zip(axs.flat, top, rows):
        e = eq_of(r.astype(np.float64))
        ax.plot(days, e, color=SER[0], lw=1.6)
        ax.axhline(1, color=INK2, lw=0.8)
        ax.axvline(split, color=NEUTRAL, lw=1, ls="--")
        ax.set_title(f"{name_of(c)}\n5y {c['full_cagr']:+.0%}/yr · test {c['oos_cagr']:+.0%}/yr · DD {c['full_maxdd']:.0%}",
                     fontsize=9, fontweight="bold")
        years_axis(ax)
        ax.tick_params(axis="x", labelsize=7)
        ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
    for ax in list(axs.flat)[n:]:
        ax.set_visible(False)
    fig.suptitle("Finalists: chosen on 2021-2024 only; right of the dashed line is the untouched test",
                 x=0.02, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "03_finalists_equity.png")

    # 4 per-finalist detail: drawdown + yearly + R distribution (top 4)
    lab = fl.Lab(HERE / "data", SYMBOLS)
    for k, c in enumerate(final[:4]):
        b = lab.get_bars(c["symbol"], c["tf"])
        sp = dict(c["params"])
        for key in ("fade_hours",):
            if key in sp:
                sp[key] = tuple(sp[key])
        daily, _, tr = lab.run(c["symbol"], c["tf"], fl.FAM[c["family"]](b, sp), c["exits"])
        e = eq_of(daily)
        fig, axs = plt.subplots(1, 3, figsize=(15, 3.8), gridspec_kw={"width_ratios": [2.2, 1.2, 1.2]})
        d = e / np.maximum.accumulate(e) - 1
        axs[0].fill_between(days, d, 0, color=SER[0], alpha=0.25, lw=0)
        axs[0].plot(days, d, color=SER[0], lw=1.3)
        axs[0].axvline(split, color=NEUTRAL, lw=1, ls="--")
        axs[0].yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
        axs[0].set_title("Drawdown", fontsize=11)
        years_axis(axs[0])
        yv = c["yearly"]
        ys = sorted(yv)
        axs[1].bar(ys, [yv[y] for y in ys], color=[SER[0] if int(y) < 2025 else SER[1] for y in ys],
                   edgecolor=SURF, linewidth=2)
        for y in ys:
            axs[1].annotate(f"{yv[y]:+.0%}", (y, yv[y]), xytext=(0, 3 if yv[y] >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=8, color=INK2)
        axs[1].axhline(0, color=INK2, lw=1)
        axs[1].yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
        axs[1].set_title("Yearly return (orange = test years)", fontsize=11)
        r = tr[:, 3]
        axs[2].hist(np.clip(r, -2, 6), bins=40, color=SER[0], edgecolor=SURF, linewidth=1)
        axs[2].axvline(0, color=INK2, lw=1)
        axs[2].set_title(f"Trade results in R (n={len(r)}, win {np.mean(r > 0):.0%}, avg {r.mean():+.2f}R)", fontsize=11)
        fig.suptitle(f"{name_of(c)}  ·  {c['params']}  ·  exits {c['exits']}", x=0.02, ha="left", fontsize=10,
                     fontweight="bold")
        fig.tight_layout()
        save(fig, f"04_finalist_{k + 1}_detail.png")

    # 5 equal-risk book of all distinct finalists
    if rep.get("finalists_book"):
        R = np.load(HERE / "data" / "fx_tf_book.npy").astype(np.float64)
        e = eq_of(R)
        fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
        axs[0].plot(days, e, color=SER[0])
        axs[0].axvline(split, color=NEUTRAL, lw=1, ls="--")
        axs[0].set_yscale("log")
        axs[0].yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
        bk = rep["finalists_book"]
        axs[0].set_title(f"All {bk['members']} finalists together, 1% risk each: {bk['cagr']:+.0%}/yr, max DD {bk['max_dd']:.0%}"
                         f" (test {bk['oos_cagr']:+.0%}/yr)")
        d = e / np.maximum.accumulate(e) - 1
        axs[1].fill_between(days, d, 0, color=SER[0], alpha=0.25, lw=0)
        axs[1].plot(days, d, color=SER[0], lw=1.2)
        axs[1].yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
        axs[1].set_title("Drawdown", fontsize=11)
        years_axis(axs[1])
        save(fig, "05_finalists_book.png")

    # 6 in-sample Sharpe vs test result for every selected strategy
    cand = rep["candidates_in_sample_ranked"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter([c["is_sharpe"] for c in cand], [c["oos_cagr"] for c in cand], s=14, color=SER[0], alpha=0.6, lw=0)
    ax.axhline(0, color=INK2, lw=1)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("In-sample Sharpe (2021-2024)")
    ax.set_ylabel("Test-period yearly return (2025-2026)")
    pos = np.mean([c["oos_cagr"] > 0 for c in cand]) if cand else 0
    ax.set_title(f"Selected strategies in the test period: {pos:.0%} positive")
    save(fig, "06_selected_is_vs_test.png")


if __name__ == "__main__":
    main()
