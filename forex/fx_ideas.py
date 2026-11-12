#!/usr/bin/env python3
"""Pre-declared multi-asset ideas, tested ONCE on five years (no parameter search).

All rules below were fixed before any result was seen.

I1 carry       weekly: among the 11 FX pairs, long the 3 with the highest policy-rate
               differential (base - quote) >= +1 %, short the 3 with the lowest <= -1 %
I2 carry+trend I1, but only while the D1 close is on the carry side of its 100-day SMA
I3 xs-mom      weekly: all 15 instruments ranked by 12-week return / 12-week daily-return vol;
               long the top 3, short the bottom 3
I4 tsmom       weekly: every instrument in the direction of mean(sign(r60), sign(r120), sign(r250))
               if |mean| = 1 (all three agree), else flat
I5 combo       I2 + I3 + I4 in one account

Risk (user rule: never more than 1 % of equity per trade)
    * hard stop at 3 x ATR20 (D1) from the entry; checked against each day's high/low,
      gap-through fills at the open
    * size so that the stop loss = risk_pct of current equity (0.5 % and 0.75 % planned; swap
      and gaps can push a loss to ~1.4 x plan, so 0.75 % keeps every realised loss below 1 %)
    * open risk across positions capped at 6 %, gross leverage at 20x
    * a stopped position is not re-entered until the next weekly rebalance
Execution at the next D1 open after the Friday close (22:00 UTC), bid/ask spread, slippage,
commission, and daily swap from the policy-rate table.  P&L is converted to USD to first
order (USD notional x price return).  Output: reports/fx_ideas.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import instruments as ins  # noqa: E402
import shahin_fx as sfx  # noqa: E402

FX = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY")
ALL = FX + ("XAUUSD", "XAGUSD", "SPXUSD", "NSXUSD")
START, END = "2021-11-12", "2026-11-08"
SEED = 10_000.0
STOP_ATR = 3.0
OPEN_RISK_CAP = 0.06
LEV_CAP = 20.0


def load_daily():
    """Five-year data plus the 2020-11..2021-11 warm-up (data/warmup) for the 250-day lookback."""
    lo, hi = sfx.ms(START), sfx.ms(END)
    bars = {}
    for s in ALL:
        name = f"{s[:3]}_{s[3:]}_bid_1m.csv"
        f = pd.read_csv(HERE / "data" / "ohlcv" / name)
        f = f[(f.timestamp >= lo) & (f.timestamp < hi)]
        w = HERE / "data" / "warmup" / "ohlcv" / name
        if w.is_file():
            g = pd.read_csv(w)
            f = pd.concat([g[g.timestamp < lo], f], ignore_index=True)
        b = sfx.make_bars(f, "D1")
        b.index = pd.to_datetime(b.close_ms, unit="ms").dt.normalize()
        bars[s] = b[["open", "high", "low", "close"]]
    idx = sorted(set().union(*[b.index for b in bars.values()]))
    O, H, L, C = (pd.DataFrame({s: bars[s][k] for s in ALL}, index=idx) for k in ("open", "high", "low", "close"))
    return O, H, L, C


def rate_diff(dates):
    out = {}
    for s in FX:
        res = []
        for side in (s[:3], s[3:]):
            tab = ins.RATES[side]
            when = pd.to_datetime([d for d, _ in tab]).values
            i = np.searchsorted(when, dates.values, side="right") - 1
            res.append(np.array([tab[max(k, 0)][1] for k in i]))
        out[s] = res[0] - res[1]
    return pd.DataFrame(out, index=dates)


def targets(name, C, ATR, diff):
    """Target side (+1/-1/0) per instrument, decided at each Friday close."""
    T = pd.DataFrame(0, index=C.index, columns=ALL)
    fri = C.index[C.index.dayofweek == 4]
    sma100 = C.rolling(100, min_periods=100).mean()
    ret = C.pct_change()
    vol12 = ret.rolling(60, min_periods=40).std()
    mom12 = C / C.shift(60) - 1
    for d in fri:
        row = pd.Series(0, index=ALL)
        if name in ("I1", "I2"):
            dd = diff.loc[d]
            longs = dd[dd >= 1.0].sort_values(ascending=False).index[:3]
            shorts = dd[dd <= -1.0].sort_values().index[:3]
            row[longs] = 1
            row[shorts] = -1
            if name == "I2":
                for s in list(longs) + list(shorts):
                    if not np.isfinite(sma100.at[d, s]) or row[s] * (C.at[d, s] - sma100.at[d, s]) <= 0:
                        row[s] = 0
        elif name == "I3":
            sc = (mom12.loc[d] / (vol12.loc[d] * np.sqrt(60))).dropna()
            if len(sc) >= 10:
                sc = sc.sort_values()
                row[sc.index[-3:]] = 1
                row[sc.index[:3]] = -1
        elif name == "I4":
            sg = sum(np.sign(C.loc[d] / C.shift(n).loc[d] - 1) for n in (60, 120, 250))
            row[sg == 3] = 1
            row[sg == -3] = -1
        T.loc[d] = row.values
    return T


def simulate(T, O, H, L, C, ATR, risk_pct, label):
    spec = {s: ins.SPEC[s] for s in ALL}
    days = C.index
    swap_d0, swL, swS = ins.swap_tables(ALL, sfx.ms(START), sfx.ms(END) + sfx.DAY_MS)
    eq = SEED
    pos = {}  # s -> dict(side, entry, stop, usd, last)
    curve, trades = [], []
    want = None
    t0 = pd.Timestamp(START)
    prev_day = None
    for k, d in enumerate(days):
        if d < t0:
            continue
        # ---- 1. execute the pending weekly rebalance at today's open
        if want is not None:
            for s in list(pos):
                if want[s] != pos[s]["side"]:
                    raw = O.at[d, s]
                    if not np.isfinite(raw):  # instrument closed today (holiday): last known price
                        raw = pos[s]["last"] if pos[s]["side"] > 0 else pos[s]["last"] - spec[s][1]
                    eq += close(pos, s, raw, spec[s], trades, d, "rebalance")
            open_risk = sum(p["risk"] for p in pos.values())
            for s in ALL:
                side = int(want[s])
                if side == 0 or s in pos or not np.isfinite(O.at[d, s]) or not np.isfinite(ATR.at[prev_day, s]):
                    continue
                pip, spread, slip, comm = spec[s]
                px = O.at[d, s] + (spread if side > 0 else 0) + side * slip
                stop = px - side * STOP_ATR * ATR.at[prev_day, s]
                dist = abs(px - stop) / px
                if open_risk + risk_pct > OPEN_RISK_CAP + 1e-12:
                    continue
                usd = min(eq * risk_pct / (dist + 2 * comm + 2 * slip / px + spread / px), eq * 0.5 * LEV_CAP)
                gross = sum(p["usd"] for p in pos.values())
                usd = min(usd, eq * LEV_CAP - gross)
                if usd <= 0:
                    continue
                eq -= usd * comm
                pos[s] = dict(side=side, entry=px, stop=stop, usd=usd, usd0=usd, last=px, risk=risk_pct, risk_usd=eq * risk_pct,
                              opened=d, swap=0.0)
                open_risk += risk_pct
            want = None
        # ---- 2. stops on today's range, swap, mark at close
        for s in list(pos):
            p = pos[s]
            pip, spread, slip, comm = spec[s]
            o, h, l, c = O.at[d, s], H.at[d, s], L.at[d, s], C.at[d, s]
            if not np.isfinite(c):
                continue
            if p["side"] > 0 and l <= p["stop"]:
                eq += close(pos, s, min(o, p["stop"]), spec[s], trades, d, "stop")
                continue
            if p["side"] < 0 and h + spread >= p["stop"]:
                eq += close(pos, s, max(o + spread, p["stop"]) - spread, spec[s], trades, d, "stop")
                continue
            ndays = (d - prev_day).days if prev_day is not None else 1
            di = int(d.value // 10**6 // sfx.DAY_MS) - swap_d0
            rate = swL[s][di] if p["side"] > 0 else swS[s][di]
            sw = p["usd"] * rate / 365 * ndays
            eq += sw
            p["swap"] += sw
            mark = c if p["side"] > 0 else c + spread
            eq += p["side"] * p["usd"] * (mark / p["last"] - 1)
            p["usd"] *= mark / p["last"]
            p["last"] = mark
            # risk budget guard: paid swap eats into the budget, so the stop tightens to keep
            # price loss + swap + exit costs <= the planned risk (<= 1 % of equity)
            budget = p["risk_usd"] + min(p["swap"], 0.0) - 2 * p["usd0"] * comm - p["usd0"] * slip / p["entry"]
            if budget <= 0:
                eq += close(pos, s, mark if p["side"] > 0 else mark - spread, spec[s], trades, d, "risk_guard")
                continue
            tight = p["entry"] * (1 - p["side"] * budget / p["usd0"])
            p["stop"] = max(p["stop"], tight) if p["side"] > 0 else min(p["stop"], tight)
        curve.append((d, eq))
        # ---- 3. Friday close -> next open rebalance
        if d.dayofweek == 4:
            want = T.loc[d]
        prev_day = d
    lastc = C.ffill().iloc[-1]
    for s in list(pos):
        eq += close(pos, s, lastc[s], spec[s], trades, days[-1], "end")
    curve[-1] = (curve[-1][0], eq)
    return pd.Series(dict(curve)), trades


def close(pos, s, raw, sp, trades, d, why):
    pip, spread, slip, comm = sp
    p = pos.pop(s)
    px = (raw if p["side"] > 0 else raw + spread) - p["side"] * slip
    pnl = p["side"] * p["usd"] * (px / p["last"] - 1) - p["usd"] * comm
    total = p["side"] * p["usd0"] * (px / p["entry"] - 1) - (p["usd0"] + p["usd"]) * comm + p["swap"]
    trades.append(dict(symbol=s, side=int(p["side"]), opened=str(p["opened"].date()), closed=str(d.date()),
                       reason=why, net_usd=round(float(total), 2), risk_usd=round(float(p["risk_usd"]), 2)))
    return pnl


def summarize(eq: pd.Series, trades):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    peak = eq.cummax()
    dd = float((1 - eq / peak).max())
    r = eq.pct_change().dropna()
    ye = eq.groupby(eq.index.year).last()
    yearly = (ye / ye.shift(1).fillna(SEED) - 1).round(4)
    return dict(cagr=round(float((eq.iloc[-1] / SEED) ** (1 / yrs) - 1), 4), max_dd=round(dd, 4),
                sharpe=round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else 0.0,
                final=round(float(eq.iloc[-1]), 2), trades=len(trades),
                stops=sum(t["reason"] == "stop" for t in trades),
                yearly={int(k): float(v) for k, v in yearly.items()})


def main():
    O, H, L, C = load_daily()
    tr = pd.concat({s: pd.concat([H[s] - L[s], (H[s] - C[s].shift()).abs(), (L[s] - C[s].shift()).abs()],
                                 axis=1).max(axis=1) for s in ALL}, axis=1)
    ATR = tr.rolling(20, min_periods=15).mean()
    diff = rate_diff(C.index)
    T = {n: targets(n, C, ATR, diff) for n in ("I1", "I2", "I3", "I4")}
    T["I5"] = None
    report = {"rules": __doc__, "start": START, "end": str(C.index[-1].date()), "results": {}}
    for risk in (0.005, 0.0075):  # 0.75 % planned keeps the realised worst loss under the 1 % cap
        for name in ("I1", "I2", "I3", "I4", "I5"):
            if name == "I5":
                # one account, union of targets; on conflict prefer the trend books (I4 > I3 > I2)
                t = T["I2"].copy()
                for src in ("I3", "I4"):
                    t = t.where(T[src] == 0, T[src])
            else:
                t = T[name]
            eq, trades = simulate(t, O, H, L, C, ATR, risk, name)
            res = summarize(eq, trades)
            worst = min((t["net_usd"] / t["risk_usd"] for t in trades), default=0.0)
            res["worst_trade_pct_of_equity"] = round(100 * risk * worst, 3)
            report["results"][f"{name}_risk{risk:g}"] = res
            print(name, risk, res["cagr"], res["max_dd"], res["sharpe"], res["trades"], res["yearly"], flush=True)
            if name == "I5" and risk == 0.005:
                report["I5_equity_weekly"] = [[str(d.date()), round(float(v), 2)] for d, v in eq.iloc[::5].items()]
    (HERE / "reports" / "fx_ideas.json").write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
