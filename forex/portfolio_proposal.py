#!/usr/bin/env python3
"""Proposed bot basket: 5 bots, each trade risks <= 1 % of equity, combined on one account.

  1 Flow bot (Gotobi + month-end; published anomalies, pre-declared)     0.90 % / event
  2 USDJPY 1h Supertrend(20, 3xATR), stop 3xATR, exit on flip            0.50 % / trade
  3 S&P 500 4h Stochastic 20/80 + EMA200 filter, stop 3xATR, 2R/20 bars   0.35 % / trade
  4 Nasdaq 100 4h Stochastic 10/90 + EMA200 filter, stop 1.5xATR, 2R/20   0.35 % / trade
  5 Gold D1 inside-bar breakout with EMA200 filter, 2R / 20 bars          0.50 % / trade
Daily R streams from the same engines/costs as the research; equity compounds daily.
Output: reports/portfolio_proposal.json, reports/charts_tf/07_proposed_basket.png
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_lab as fl, flow_bot as fb
from fx_search_dd import SYMBOLS

BOTS = [
    ("USDJPY 1h Supertrend", 0.005, "USDJPY", "1h", "supertrend", dict(n=20, mult=3.0, stop=3.0), {}),
    ("S&P 500 4h Stochastic", 0.0035, "SPXUSD", "4h", "stoch", dict(lvl=20.0, trend=True, stop=3.0), {"tgt_r": 2.0, "time_stop": 20}),
    ("Nasdaq 4h Stochastic", 0.0035, "NSXUSD", "4h", "stoch", dict(lvl=10.0, trend=True, stop=1.5), {"tgt_r": 2.0, "time_stop": 20}),
    ("Gold D1 inside bar", 0.005, "XAUUSD", "D1", "insidebar", dict(trend=True, valid=3, tf="D1"), {"tgt_r": 2.0, "time_stop": 20}),
]

def main():
    lab = fl.Lab(HERE / "data", SYMBOLS)
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    streams, worst = {}, {}
    for name, risk, sym, tf, fam, sp, ex in BOTS:
        b = lab.get_bars(sym, tf)
        daily, _, tr = lab.run(sym, tf, fl.FAM[fam](b, sp), ex)
        streams[name] = risk * daily
        worst[name] = round(100 * risk * float(tr[:, 3].min()), 3)
    # flow bot: per-trade R -> daily, weighted by its allocation
    t = fb.trades()
    t["w"] = t.strategy.map(fb.ALLOC) * t.R
    d = (t.exit_ms // fl.DAY_MS - day0).astype(int)
    flow = np.zeros(lab.ndays)
    np.add.at(flow, d.to_numpy(), t.w.to_numpy())
    streams["Flow bot (Gotobi + month-end)"] = flow
    worst["Flow bot (Gotobi + month-end)"] = round(100 * float(t.groupby(["strategy", "exit_ms"]).w.sum().min()), 3)
    days = pd.to_datetime((np.arange(lab.ndays) + day0) * fl.DAY_MS, unit="ms")
    df = pd.DataFrame(streams, index=days)
    tot = df.sum(1)

    def st(x):
        eq = np.cumprod(1 + x.to_numpy())
        yrs = len(x) / 365.25
        ser = pd.Series(eq, index=x.index); ye = ser.groupby(ser.index.year).last()
        return dict(cagr=round(float(eq[-1] ** (1 / yrs) - 1), 4), max_dd=round(float(np.max(1 - eq / np.maximum.accumulate(eq))), 4),
                    sharpe=round(float(x.mean() / x.std() * np.sqrt(365.25)), 2),
                    yearly={int(k): round(float(v), 4) for k, v in (ye / ye.shift(1).fillna(1.0) - 1).items()})
    rep = {"rules": __doc__, "worst_trade_pct_equity": worst,
           "per_bot": {k: st(df[k]) for k in df}, "basket": st(tot),
           "basket_2021_2024": st(tot[days < "2025-01-01"]), "basket_2025_2026": st(tot[days >= "2025-01-01"]),
           "correlation": df.resample("W").sum().corr().round(2).to_dict()}
    (HERE / "reports" / "portfolio_proposal.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps({k: rep[k] for k in ("basket", "basket_2021_2024", "basket_2025_2026", "worst_trade_pct_equity")}, indent=1))
    for k, v in rep["per_bot"].items(): print(k, v["cagr"], v["max_dd"], v["sharpe"])
    print(df.resample("W").sum().corr().round(2))
    # chart
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt, matplotlib.ticker as mt, matplotlib.dates as mdates
    import fx_charts as fc
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    for i, k in enumerate(df):
        axs[0].plot(days, np.cumprod(1 + df[k].to_numpy()), color=fc.SER[i], lw=1.2, label=k)
    eq = np.cumprod(1 + tot.to_numpy())
    axs[0].plot(days, eq, color=fc.INK, lw=2.4, label="basket")
    axs[0].axvline(pd.Timestamp("2025-01-01"), color=fc.NEUTRAL, lw=1, ls="--")
    axs[0].yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}x"))
    axs[0].legend(loc="upper left", fontsize=8, ncol=2)
    b = rep["basket"]
    axs[0].set_title(f"Proposed 5-bot basket: {b['cagr']:+.1%}/yr, max DD {b['max_dd']:.1%}, Sharpe {b['sharpe']}")
    dd = eq / np.maximum.accumulate(eq) - 1
    axs[1].fill_between(days, dd, 0, color=fc.SER[0], alpha=0.25, lw=0); axs[1].plot(days, dd, color=fc.SER[0], lw=1.2)
    axs[1].yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0)); axs[1].set_title("Drawdown", fontsize=11)
    axs[1].xaxis.set_major_locator(mdates.YearLocator()); axs[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.savefig(HERE / "reports" / "charts_tf" / "07_proposed_basket.png", dpi=150, bbox_inches="tight")

if __name__ == "__main__":
    main()
