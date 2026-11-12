#!/usr/bin/env python3
"""Flow bot: the two published anomalies that survived costs in fx_anomalies.py.

    E2 Gotobi  : long USDJPY 07:00 -> 09:55 JST on gotobi days, 0.90 % planned equity risk per trade
    E4 Month-end: last weekday, 10:00 -> 16:00 London, sell USD if S&P 500 is up month-to-date
                 (buy USD if down) on EURUSD, GBPUSD, USDJPY, AUDUSD at 0.225 % each
                 = 0.90 % for the whole event (one USD bet)
No trade/event risks more than 1 % of equity.  Equity compounds per trade.
Also reports a cost sensitivity (half the spread/slippage/commission, e.g. a raw-spread ECN
account with limit-order entries).  Output: reports/flow_bot.json
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_anomalies as fa

ALLOC = {"E2_gotobi_long_usdjpy": 0.009, "E4_month_end_rebalance": 0.00225}  # 0.9 % plan: gaps stay under the 1 % cap


def trades():
    ev = pd.DataFrame(fa.events(), columns=["strategy", "symbol", "side", "entry_ms", "exit_ms"])
    ev = ev[ev.strategy.isin(ALLOC)]
    out = []
    for sym, g in ev.groupby("symbol"):
        f = pd.read_csv(HERE / "data" / "ohlcv" / f"{sym[:3]}_{sym[3:]}_bid_1m.csv")
        d1 = fa.sfx.make_bars(f, "D1")
        tr = pd.concat([d1.high - d1.low, (d1.high - d1.close.shift()).abs(), (d1.low - d1.close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(20, min_periods=15).mean().to_numpy()
        k = np.searchsorted(d1.close_ms.to_numpy(), g.entry_ms.to_numpy(), side="right") - 1
        pip, spread, slip, comm = fa.ins.SPEC[sym]
        dist = np.maximum(np.where(k >= 0, 0.5 * atr[np.clip(k, 0, None)], np.nan), 5 * pip)
        res = fa.run_trades(f.timestamp.to_numpy(np.int64), f.open.to_numpy(), f.high.to_numpy(), f.low.to_numpy(),
                            f.close.to_numpy(), g.side.to_numpy(np.int64), g.entry_ms.to_numpy(np.int64),
                            g.exit_ms.to_numpy(np.int64), np.nan_to_num(dist, nan=1e9), spread, slip, comm)
        g = g.assign(R=res[:, 0], R_gross=res[:, 1])
        out.append(g)
    t = pd.concat(out).dropna(subset=["R"]).sort_values("exit_ms")
    t["R_halfcost"] = t.R_gross - (t.R_gross - t.R) / 2
    return t


def equity(t, col):
    eq, peak, dd, curve = 1.0, 1.0, 0.0, []
    for _, g in t.groupby("exit_ms"):
        eq *= 1 + sum(ALLOC[s] * r for s, r in zip(g.strategy, g[col]))
        peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        curve.append((int(g.exit_ms.iloc[0]), eq))
    return eq, dd, curve


def main():
    t = trades()
    yrs = (pd.Timestamp(fa.END) - pd.Timestamp(fa.START)).days / 365.25
    rep = {"rules": __doc__}
    for col, name in (("R", "base_costs"), ("R_halfcost", "half_costs"), ("R_gross", "zero_costs")):
        eq, dd, curve = equity(t, col)
        s = pd.Series({pd.to_datetime(a, unit="ms"): b for a, b in curve})
        ye = s.groupby(s.index.year).last()
        rep[name] = dict(cagr=round(eq ** (1 / yrs) - 1, 4), total=round(eq - 1, 4), max_dd=round(dd, 4),
                         yearly={int(k): round(float(v), 4) for k, v in (ye / ye.shift(1).fillna(1.0) - 1).items()})
        print(name, rep[name])
    t["w"] = t.strategy.map(ALLOC) * t.R
    worst = t.groupby(["strategy", "exit_ms"]).w.sum().min()
    rep["worst_trade_or_event_pct_equity"] = round(100 * float(worst), 3)
    rep["trades"] = {k: int(v) for k, v in t.strategy.value_counts().items()}
    print("worst event % of equity:", rep["worst_trade_or_event_pct_equity"], rep["trades"])
    (HERE / "reports" / "flow_bot.json").write_text(json.dumps(rep, indent=1) + "\n")


if __name__ == "__main__":
    main()
