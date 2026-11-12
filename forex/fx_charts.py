#!/usr/bin/env python3
"""Charts for fx_best.py results -> reports/charts/*.png (light theme, validated palette)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_lab as fl  # noqa: E402

OUT = HERE / "reports" / "charts"
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SER = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#a9a8a3"
DIV_NEG, DIV_MID, DIV_POS = "#d03b3b", "#f0efec", "#2a78d6"
RISK = 0.01
LABEL = {"P1_greedy_max_cagr": "P1 greedy max-CAGR", "P2_greedy_max_sharpe": "P2 greedy max-Sharpe",
         "P3_top50_decorrelated": "P3 top-50 decorrelated", "P4_broad_invvol": "P4 broad inverse-vol"}

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "lines.linewidth": 2,
    "legend.frameon": False,
})


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def equity(x):
    return np.cumprod(np.clip(1 + RISK * x, 1e-9, None))


def dd(eq):
    peak = np.maximum.accumulate(eq)
    return eq / peak - 1


def end_label(ax, x, y, text, color):
    ax.annotate(text, (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points", va="center",
                fontsize=9, color=INK, fontweight="bold")
    ax.plot([x[-1]], [y[-1]], "o", ms=5, color=color, mec=SURF, mew=2)


def main():
    rep = json.loads((HERE / "reports" / "fx_best.json").read_text())
    cv = np.load(HERE / "data" / "fx_best_curves.npz")
    S = np.load(HERE / "data" / "fx_best_streams.npz")["S"].astype(np.float64)
    meta = json.loads((HERE / "data" / "fx_best_meta.json").read_text())
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    days = pd.to_datetime((np.arange(S.shape[1]) + day0) * fl.DAY_MS, unit="ms")
    yr = days.year.values
    ports = rep["portfolios"]
    names = list(ports)
    best = max(names, key=lambda n: ports[n]["cagr"])

    # 1 portfolios equity (hindsight), log scale
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for k, n in enumerate(names):
        eq = equity(cv[f"{n}_hindsight"])
        ax.plot(days, eq, color=SER[k], label=LABEL[n])
        end_label(ax, days, eq, f"{ports[n]['cagr']:+.0%}/yr", SER[k])
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
    ax.set_title("Best combinations, picked with hindsight on all five years (1% risk per trade)")
    ax.set_ylabel("Equity (start = 1x, log scale)")
    ax.legend(loc="upper left")
    save(fig, "01_portfolios_equity_hindsight.png")

    # 2 hindsight vs walk-forward, small multiples (same y-axis)
    fig, axs = plt.subplots(2, 2, figsize=(11, 7), sharey=True, sharex=True)
    m23 = yr >= 2023
    for ax, n in zip(axs.flat, names):
        h = equity(cv[f"{n}_hindsight"][m23])
        w = equity(cv[f"{n}_wf"])
        ax.plot(days[m23], h, color=SER[0], label="picked with hindsight")
        ax.plot(days[m23], w, color=SER[1], label="walk-forward (picked only on the past)")
        end_label(ax, days[m23], h, f"{h[-1] - 1:+.0%}", SER[0])
        end_label(ax, days[m23], w, f"{w[-1] - 1:+.0%}", SER[1])
        ax.axhline(1, color=INK2, lw=1)
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
        ax.set_title(LABEL[n], fontsize=11)
    axs[0, 0].legend(loc="upper left", fontsize=9)
    fig.suptitle("Same rule, two ways: hindsight vs walk-forward, 2023-01 to 2026-11", x=0.06, ha="left",
                 fontweight="bold")
    fig.tight_layout()
    save(fig, "02_hindsight_vs_walkforward.png")

    # 3 drawdown of the best portfolio (hindsight) and its walk-forward
    fig, ax = plt.subplots(figsize=(10, 3.8))
    d = dd(equity(cv[f"{best}_hindsight"]))
    ax.fill_between(days, d, 0, color=SER[0], alpha=0.25, lw=0)
    ax.plot(days, d, color=SER[0], lw=1.5, label="hindsight")
    wd = dd(equity(cv[f"{best}_wf"]))
    ax.plot(days[m23], wd, color=SER[1], lw=1.5, label="walk-forward")
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_title(f"Drawdown: {LABEL[best]}")
    ax.legend(loc="lower left")
    save(fig, "03_drawdown_best.png")

    # 4 yearly returns: hindsight vs walk-forward for the best portfolio
    hy = ports[best]["yearly"]
    wy = {r["year"]: r["ret"] for r in ports[best]["walk_forward"]["years"]}
    years = [y for y in sorted(int(k) for k in hy) if y >= 2022]
    xs = np.arange(len(years))
    fig, ax = plt.subplots(figsize=(9, 4.2))
    b1 = ax.bar(xs - 0.2, [hy[str(y)] if str(y) in hy else hy[y] for y in years], 0.38, color=SER[0],
                label="hindsight", edgecolor=SURF, linewidth=2)
    b2 = ax.bar(xs + 0.2, [wy.get(y, np.nan) for y in years], 0.38, color=SER[1], label="walk-forward",
                edgecolor=SURF, linewidth=2)
    for bars in (b1, b2):
        for r in bars:
            v = r.get_height()
            if np.isfinite(v):
                ax.annotate(f"{v:+.0%}", (r.get_x() + r.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=8, color=INK2)
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(xs, years)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_title(f"Yearly return: {LABEL[best]}")
    ax.legend(loc="upper left")
    save(fig, "04_yearly_best.png")

    # 5 monthly heatmap of the best portfolio (hindsight), diverging
    eq = pd.Series(equity(cv[f"{best}_hindsight"]), index=days)
    me = eq.resample("ME").last()
    mr = me / me.shift(1).fillna(1.0) - 1
    tab = mr.groupby([mr.index.year, mr.index.month]).first().unstack()
    lim = np.nanpercentile(np.abs(tab.values), 95)
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("div", [DIV_NEG, DIV_MID, DIV_POS])
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.grid(False)
    im = ax.imshow(tab.values, cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
    for i in range(tab.shape[0]):
        for j in range(tab.shape[1]):
            v = tab.values[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:+.0%}", ha="center", va="center", fontsize=8, color=INK)
    ax.set_xticks(range(tab.shape[1]), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][:tab.shape[1]])
    ax.set_yticks(range(tab.shape[0]), tab.index)
    ax.set_title(f"Monthly return: {LABEL[best]} (hindsight)")
    fig.colorbar(im, ax=ax, format=mt.PercentFormatter(1.0, decimals=0), shrink=0.8)
    save(fig, "05_monthly_heatmap_best.png")

    # 6/7 contribution by symbol and family (R)
    for fname, key, title in (("06_contribution_by_symbol.png", "contribution_R_by_symbol", "symbol"),
                              ("07_contribution_by_family.png", "contribution_R_by_family", "strategy family")):
        c = ports[best][key]
        ks = list(c)[::-1]
        fig, ax = plt.subplots(figsize=(8, 0.35 * len(ks) + 1.5))
        ax.barh(ks, [c[k] for k in ks], color=SER[0], height=0.7, edgecolor=SURF, linewidth=2)
        for i, k in enumerate(ks):
            ax.annotate(f"{c[k]:+.0f}R", (c[k], i), xytext=(4 if c[k] >= 0 else -4, 0), textcoords="offset points",
                        va="center", ha="left" if c[k] >= 0 else "right", fontsize=8, color=INK2)
        ax.axvline(0, color=INK2, lw=1)
        ax.set_title(f"Where {LABEL[best]} made its profit, by {title} (5 years, in R)")
        ax.grid(axis="y", visible=False)
        save(fig, fname)

    # 8 top 10 single strategies, small multiples
    top = rep["top25_single_by_cagr"][:10]
    jmap = {(m["idx"], m["symbol"]): j for j, m in enumerate(meta)}
    fig, axs = plt.subplots(2, 5, figsize=(16, 6.2), sharey=True)
    for ax, m in zip(axs.flat, top):
        j = jmap[(m["idx"], m["symbol"])]
        e = equity(S[j])
        ax.plot(days, e, color=SER[0], lw=1.6)
        ax.axhline(1, color=INK2, lw=0.8)
        ax.axvline(pd.Timestamp("2025-01-01"), color=NEUTRAL, lw=1, ls="--")
        ax.set_title(f"{m['symbol']} {m['tf']} {m['family']}\n{m['cagr']:+.0%}/yr  DD {m['max_dd']:.0%}", fontsize=9,
                     fontweight="bold")
        ax.tick_params(axis="x", labelsize=7, rotation=45)
        ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
    fig.suptitle("Top 10 single strategies by five-year return (1% risk per trade; dashed line = 2025-01)",
                 x=0.06, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "08_top10_single_strategies.png")

    # 9 share of profitable strategies by family
    fo = rep["family_overview"]
    ks = sorted(fo, key=lambda k: fo[k]["share_profitable"])
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(ks, [fo[k]["share_profitable"] for k in ks], color=SER[0], height=0.7, edgecolor=SURF, linewidth=2)
    for i, k in enumerate(ks):
        ax.annotate(f"{fo[k]['share_profitable']:.0%}  (n={fo[k]['strategies']})", (fo[k]["share_profitable"], i),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    ax.xaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.set_title("Share of strategies that were profitable over five years, by family")
    save(fig, "09_profitable_share_by_family.png")

    # 10 Sharpe distribution vs a no-edge null (monthly-block sign flips)
    ok = np.array([m["trades"] >= 30 for m in meta]) & (S.std(1) > 0)
    X = S[ok]
    sh = X.mean(1) / X.std(1) * np.sqrt(365.25)
    rng = np.random.default_rng(0)
    blk = np.arange(S.shape[1]) // 21
    sg = rng.choice([-1, 1], size=(X.shape[0], blk.max() + 1))[:, blk]
    Y = X * sg
    shn = Y.mean(1) / Y.std(1) * np.sqrt(365.25)
    bins = np.linspace(-3, 3, 61)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.hist(sh, bins=bins, histtype="step", lw=2, color=SER[0], label=f"real strategies (best {sh.max():.2f})")
    ax.hist(shn, bins=bins, histtype="step", lw=2, color=SER[1], label=f"same strategies, edge removed (best {shn.max():.2f})")
    ax.set_xlabel("Sharpe ratio over five years")
    ax.set_ylabel("Number of strategies")
    ax.set_title("Are the best strategies better than luck?")
    ax.legend(loc="upper left")
    save(fig, "10_sharpe_vs_luck.png")

    # 11 in-sample vs out-of-sample per strategy
    is_m, oos_m = yr < 2025, yr >= 2025
    gi = np.log(np.clip(1 + RISK * X[:, is_m], 1e-9, None)).sum(1) / (is_m.sum() / 365.25)
    go = np.log(np.clip(1 + RISK * X[:, oos_m], 1e-9, None)).sum(1) / (oos_m.sum() / 365.25)
    ci, co = np.expm1(gi), np.expm1(go)
    rho = pd.Series(ci).corr(pd.Series(co), method="spearman")
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(ci, co, s=4, color=SER[0], alpha=0.15, lw=0)
    top_i = np.argsort(-ci)[:50]
    ax.scatter(ci[top_i], co[top_i], s=18, color=SER[1], lw=0, label="top 50 in 2021-2024")
    ax.axhline(0, color=INK2, lw=1)
    ax.axvline(0, color=INK2, lw=1)
    ax.xaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Yearly return 2021-11 to 2024-12")
    ax.set_ylabel("Yearly return 2025-01 to 2026-11")
    ax.set_title(f"Past winners vs later results (rank correlation {rho:+.2f})")
    ax.legend(loc="upper left")
    save(fig, "11_in_sample_vs_out_of_sample.png")
    (OUT / "summary.json").write_text(json.dumps({"best_portfolio": best, "spearman_is_oos": round(float(rho), 3),
                                                  "best_real_sharpe": round(float(sh.max()), 2),
                                                  "best_null_sharpe": round(float(shn.max()), 2),
                                                  "top50_is_mean_oos_cagr": round(float(co[top_i].mean()), 4)}, indent=1))


if __name__ == "__main__":
    main()
