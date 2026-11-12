#!/usr/bin/env python3
"""Losing-trade diagnostics for the chosen 5-bot basket (portfolio_proposal.py).

1. every trade gets its path stats from minute data: MFE / MAE (in R), and the entry context
   (hour, weekday, volatility regime, trend strength, ADX, extension before entry, daily trend)
2. losers are classified
     A never worked   : MFE < 0.3R and closed <= 0
     B gave back      : MFE >= 1R and closed <= 0
     C half-way       : 0.3R <= MFE < 1R and closed <= 0
     D gap            : loss beyond -1.05R
     E cost-killed    : gross R > 0, net R <= 0
3. expectancy per context bucket (terciles / sessions) with a t-statistic vs the bot's mean;
   these are HYPOTHESES only (many buckets -> some look significant by chance) and must be
   confirmed on held-out data before any rule changes.
Outputs: reports/diagnose/*.json, trades_*.csv, charts.
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
import fx_lab as fl  # noqa: E402
import instruments as ins  # noqa: E402
import portfolio_proposal as pp  # noqa: E402
from fx_search_dd import SYMBOLS  # noqa: E402

OUT = HERE / "reports" / "diagnose"
REASON = {1: "stop", 2: "line_cross", 3: "signal_flip", 4: "time_stop", 5: "weekend", 6: "target", 7: "period_end"}


def context_bars(b):
    """Indicators on the bot's own bars, known at each bar close."""
    h, l, c = b.high, b.low, b.close
    atr = b.atr
    e200 = fl.ema(c, 200)
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=c.index)
    ndm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=c.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / a14
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / a14
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    volp = (atr / c).rolling(250, min_periods=100).rank(pct=True)
    return pd.DataFrame({"close_ms": b.close_ms, "close": c, "atr": atr, "trend_atr": (c - e200) / atr,
                         "adx": adx, "vol_pct": volp, "ext10_atr": (c - c.shift(10)) / atr})


def daily_trend(lab, sym):
    d = lab.get_bars(sym, "D1")
    return pd.DataFrame({"close_ms": d.close_ms, "d1_trend": np.sign(d.close - fl.ema(d.close, 50))})


def path_stats(m, spread, entry_ms, exit_ms, side, lev):
    t = m["t"]
    i = np.searchsorted(t, entry_ms)
    j = np.searchsorted(t, exit_ms, side="right")
    e = m["open"][i] + (spread if side > 0 else 0.0)
    dist = e / lev
    hi, lo = m["high"][i:j].max(), m["low"][i:j].min()
    if side > 0:
        mfe, mae = (hi - e) / dist, (e - lo) / dist
    else:
        mfe, mae = (e - (lo + spread)) / dist, ((hi + spread) - e) / dist
    return mfe, mae, e, dist


def enrich(trades, lab, sym, tf):
    b = lab.get_bars(sym, tf)
    ctx = context_bars(b)
    dtr = daily_trend(lab, sym)
    m = lab.min[sym]
    pip, spread, slip, comm = ins.SPEC[sym]
    rows = []
    for k, r in trades.iterrows():
        mfe, mae, e, dist = path_stats(m, spread, int(r.entry_ms), int(r.exit_ms), int(r.side), float(r.lev))
        ci = int(np.searchsorted(ctx.close_ms.to_numpy(), r.entry_ms, side="right") - 1)
        di = int(np.searchsorted(dtr.close_ms.to_numpy(), r.entry_ms, side="right") - 1)
        x = ctx.iloc[ci] if ci >= 0 else None
        gross_cost_R = (spread + 2 * slip) / dist + 2 * comm * e / dist
        ts = pd.Timestamp(int(r.entry_ms), unit="ms")
        rows.append(dict(
            entry=ts, exit=pd.Timestamp(int(r.exit_ms), unit="ms"), side=int(r.side), R=float(r.R),
            R_gross_est=float(r.R) + gross_cost_R, mfe=mfe, mae=mae,
            hours_held=(r.exit_ms - r.entry_ms) / 3.6e6, reason=REASON.get(int(r.reason), str(r.reason)),
            hour=ts.hour, weekday=ts.dayofweek, year=ts.year,
            trend_aligned=float(r.side * x.trend_atr) if x is not None else np.nan,
            adx=float(x.adx) if x is not None else np.nan,
            vol_pct=float(x.vol_pct) if x is not None else np.nan,
            ext_aligned=float(r.side * x.ext10_atr) if x is not None else np.nan,
            d1_with=float(r.side * dtr.d1_trend.iloc[di]) if di >= 0 else np.nan))
    return pd.DataFrame(rows)


def classify(d):
    loss = d.R <= 0
    cat = pd.Series("win", index=d.index)
    cat[loss & (d.R < -1.05)] = "D gap"
    rest = loss & (d.R >= -1.05)
    cat[rest & (d.R_gross_est > 0)] = "E cost-killed"
    rest &= d.R_gross_est <= 0
    cat[rest & (d.mfe >= 1.0)] = "B gave back"
    cat[rest & (d.mfe < 0.3)] = "A never worked"
    cat[rest & (d.mfe >= 0.3) & (d.mfe < 1.0)] = "C half-way"
    return cat


def buckets(d):
    """Expectancy by context bucket, with t-stat of the bucket mean vs the overall mean."""
    out = []
    mu = d.R.mean()

    def add(feature, labels):
        for lab_, g in d.groupby(labels, observed=True):
            if len(g) < 12:
                continue
            se = g.R.std() / np.sqrt(len(g)) if len(g) > 1 else np.nan
            out.append(dict(feature=feature, bucket=str(lab_), n=len(g), win=round(float((g.R > 0).mean()), 3),
                            exp_R=round(float(g.R.mean()), 3), t_vs_all=round(float((g.R.mean() - mu) / se), 2) if se else 0.0))
    sess = pd.cut(d.hour, [-1, 6, 12, 16, 21, 24], labels=["Asia 22-07", "London 07-13", "LDN/NY 13-17", "NY 17-22", "late 22-24"])
    add("session (UTC hour)", sess)
    add("weekday", d.weekday.map({0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 6: "Sun"}))
    for f, name in (("vol_pct", "volatility regime"), ("trend_aligned", "trend strength (EMA200, ATR, with trade)"),
                    ("adx", "ADX"), ("ext_aligned", "extension before entry (10 bars, ATR)")):
        x = d[f]
        if x.notna().sum() > 30:
            add(name, pd.qcut(x, 3, labels=["low", "mid", "high"], duplicates="drop"))
    add("daily trend (EMA50)", d.d1_with.map({1.0: "with", -1.0: "against", 0.0: "flat"}))
    add("year", d.year)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lab = fl.Lab(HERE / "data", SYMBOLS)
    bots = {}
    for name, risk, sym, tf, fam, sp, ex in pp.BOTS:
        b = lab.get_bars(sym, tf)
        _, _, tr = lab.run(sym, tf, fl.FAM[fam](b, sp), ex)
        t = pd.DataFrame(tr, columns=["entry_ms", "exit_ms", "side", "R", "lev", "reason"])
        bots[name] = (enrich(t, lab, sym, tf), sym)
    ft = fb.trades()
    for strat, label in (("E2_gotobi_long_usdjpy", "Flow: Gotobi (USDJPY)"),
                         ("E4_month_end_rebalance", "Flow: month-end")):
        g = ft[ft.strategy == strat]
        parts = []
        for sym, gs in g.groupby("symbol"):
            pip, spread, slip, comm = ins.SPEC[sym]
            m = lab.min[sym]
            # stop distance from the flow bot rule (0.5 x D1 ATR20, >= 5 pips) -> lev = e / dist
            d1 = fl.sfx.make_bars(pd.DataFrame({"timestamp": m["t"], "open": m["open"], "high": m["high"],
                                                "low": m["low"], "close": m["close"]}), "D1")
            trr = pd.concat([d1.high - d1.low, (d1.high - d1.close.shift()).abs(), (d1.low - d1.close.shift()).abs()],
                            axis=1).max(axis=1).rolling(20, min_periods=15).mean().to_numpy()
            k = np.searchsorted(d1.close_ms.to_numpy(), gs.entry_ms.to_numpy(), side="right") - 1
            dist = np.maximum(0.5 * trr[np.clip(k, 0, None)], 5 * pip)
            i = np.searchsorted(m["t"], gs.entry_ms.to_numpy())
            e = m["open"][i] + np.where(gs.side.to_numpy() > 0, spread, 0.0)
            t = pd.DataFrame({"entry_ms": gs.entry_ms.to_numpy(), "exit_ms": gs.exit_ms.to_numpy(), "side": gs.side.to_numpy(),
                              "R": gs.R.to_numpy(), "lev": e / dist, "reason": 4})
            de = enrich(t, lab, sym, "D1")
            de["symbol"] = sym
            de["R_gross_est"] = gs.R_gross.to_numpy()
            parts.append(de)
        bots[label] = (pd.concat(parts, ignore_index=True), "multi")

    report = {}
    for name, (d, sym) in bots.items():
        d["category"] = classify(d)
        d.to_csv(OUT / f"trades_{name.split(':')[0].replace(' ', '_').replace('&', '')}_{abs(hash(name)) % 1000}.csv", index=False)
        losers = d[d.R <= 0]
        cats = losers.category.value_counts()
        cat_tab = {c: dict(n=int(n), share=round(float(n / len(losers)), 3),
                           R_lost=round(float(losers[losers.category == c].R.sum()), 1)) for c, n in cats.items()}
        report[name] = dict(
            trades=len(d), winners=int((d.R > 0).sum()), losers=int(len(losers)),
            R_won=round(float(d[d.R > 0].R.sum()), 1), R_lost=round(float(losers.R.sum()), 1),
            loser_categories=cat_tab,
            losers_avg_mfe=round(float(losers.mfe.mean()), 2), winners_avg_mae=round(float(d[d.R > 0].mae.mean()), 2),
            loser_exit_reasons=losers.reason.value_counts().to_dict(),
            avg_hours_loser=round(float(losers.hours_held.mean()), 1), avg_hours_winner=round(float(d[d.R > 0].hours_held.mean()), 1),
            buckets=buckets(d))
    (OUT / "diagnose.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for name, r in report.items():
        print(f"\n=== {name}: {r['trades']} trades, {r['losers']} losers, lost {r['R_lost']}R vs won {r['R_won']}R")
        for c, v in r["loser_categories"].items():
            print(f"   {c:16s} {v['n']:4d} ({v['share']:.0%})  {v['R_lost']:+.1f}R")
        print("   loser avg MFE", r["losers_avg_mfe"], "| winner avg MAE", r["winners_avg_mae"],
              "| hours loser/winner", r["avg_hours_loser"], r["avg_hours_winner"], "| exits", r["loser_exit_reasons"])
        strong = sorted([b for b in r["buckets"] if abs(b["t_vs_all"]) >= 2 and b["feature"] != "year"],
                        key=lambda b: b["t_vs_all"])
        for b in strong:
            print(f"   {b['feature']:42s} {b['bucket']:14s} n={b['n']:4d} win={b['win']:.0%} exp={b['exp_R']:+.2f}R t={b['t_vs_all']:+.1f}")
    charts(report, bots)


def charts(report, bots):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mt
    import fx_charts as fc
    cats = ["A never worked", "C half-way", "B gave back", "D gap", "E cost-killed"]
    cols = [fc.SER[1], fc.SER[3], fc.SER[0], fc.SER[7], fc.SER[6]]
    names = list(report)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    left = np.zeros(len(names))
    for c, col in zip(cats, cols):
        v = np.array([-report[n]["loser_categories"].get(c, {}).get("R_lost", 0.0) for n in names])
        ax.barh(names, v, left=left, color=col, label=c, height=0.6, edgecolor=fc.SURF, linewidth=2)
        left += v
    ax.invert_yaxis()
    ax.set_xlabel("R lost by losing trades (5 years)")
    ax.set_title("Where the losses come from, by loser type", pad=28)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=5, fontsize=8)
    ax.grid(axis="y", visible=False)
    fig.savefig(OUT / "01_loser_categories.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    # MFE vs result per bot
    fig, axs = plt.subplots(2, 3, figsize=(14, 7.5))
    for ax, n in zip(axs.flat, names):
        d = bots[n][0]
        w = d.R > 0
        ax.scatter(d.mfe[~w].clip(upper=6), d.R[~w], s=10, color=fc.SER[1], alpha=0.6, lw=0, label="loser")
        ax.scatter(d.mfe[w].clip(upper=6), d.R[w], s=10, color=fc.SER[0], alpha=0.6, lw=0, label="winner")
        ax.axhline(0, color=fc.INK2, lw=1)
        ax.axvline(1, color=fc.NEUTRAL, lw=1, ls="--")
        ax.set_title(n, fontsize=10)
        ax.set_xlabel("best open profit during the trade (MFE, R)", fontsize=8)
        ax.set_ylabel("final result (R)", fontsize=8)
    axs.flat[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("How far trades went in our favour vs how they ended (right of the dashed line = reached +1R)",
                 x=0.02, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "02_mfe_vs_result.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
