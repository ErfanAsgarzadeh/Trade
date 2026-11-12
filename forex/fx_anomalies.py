#!/usr/bin/env python3
"""Published FX / index flow anomalies, rules fixed from the papers BEFORE testing.

E1 fix reversal   Krohn, Mueller & Whelan (Bank of Canada SWP 2021-48): USD appreciates into the
                  Tokyo (09:55 JST), ECB (14:15 CET) and London (16:00 UK) fixes and reverts after.
                  E1a pre-fix : long USD from fix-60 min to the fix
                  E1b post-fix: short USD from the fix to fix+60 min
                  (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD)
E2 gotobi         Bessho, Sugimoto & Suzuki (arXiv 2301.13204): USDJPY rises into the 09:55 JST
                  Tokyo fix on days 5/10/15/20/25/month-end (weekend -> previous Friday).
                  long USDJPY 07:00 JST (22:00 UTC prior day) -> 09:55 JST (00:55 UTC)
E3 local hours    Breedon & Ranaldo (JMCB 2013): currencies depreciate in their own trading hours.
                  short EURUSD and GBPUSD 07:00-12:00 London, long EURUSD and GBPUSD 08:30-12:00 New York;
                  long USDJPY 09:00-15:00 Tokyo (yen weak in Tokyo hours)
E4 month-end      Melvin & Prins (ECB FX workshop 2013): on the last weekday of the month, if the
                  S&P 500 is up month-to-date, sell USD from 10:00 London to the 16:00 London fix
                  (buy USD if it is down).  EURUSD, GBPUSD, USDJPY, AUDUSD.
E5 overnight      Boyarchenko, Larsen & Whelan (RFS 2023): long S&P 500 from the US close (16:00 NY)
                  to the next US open (09:30 NY).  Control: NY Fed (2026) says it faded 2021-25.

Execution: market entry at the open of the first minute at/after the time (buy at ask), exit
likewise; hard stop at 0.5 x D1 ATR20 (previous day) from the entry, min 5 pips, checked every
minute.  Costs from instruments.py (spread, slippage, commission).  Results in R (1R = stop risk).
Portfolio: 0.5 % of equity per trade (< 1 % cap), open risk <= 6 %.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import instruments as ins  # noqa: E402
import shahin_fx as sfx  # noqa: E402

START, END = "2021-11-12", "2026-11-07"
USD_SIGN = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCAD": 1, "USDCHF": 1}
TZ = {"tokyo": ZoneInfo("Asia/Tokyo"), "london": ZoneInfo("Europe/London"),
      "frankfurt": ZoneInfo("Europe/Berlin"), "ny": ZoneInfo("America/New_York")}
RISK = 0.005


def utc_ms(day, hh, mm, tz):
    local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ[tz])
    return int(local.astimezone(timezone.utc).timestamp() * 1000)


def weekdays():
    d = pd.date_range(START, END, freq="D")
    return [x.date() for x in d if x.dayofweek < 5]


def events():
    """(strategy, symbol, side, entry_ms, exit_ms)"""
    ev = []
    days = weekdays()
    fixes = [("tokyo", 9, 55), ("frankfurt", 14, 15), ("london", 16, 0)]
    for day in days:
        for tz, hh, mm in fixes:
            fx = utc_ms(day, hh, mm, tz)
            for s, sg in USD_SIGN.items():
                ev.append(("E1a_prefix_long_usd", s, sg, fx - 3_600_000, fx))
                ev.append(("E1b_postfix_short_usd", s, -sg, fx, fx + 3_600_000))
    # gotobi
    months = pd.period_range(START, END, freq="M")
    for m in months:
        last = m.end_time.date()
        cands = [datetime(m.year, m.month, d).date() for d in (5, 10, 15, 20, 25)] + [last]
        for c in cands:
            while c.weekday() >= 5:
                c -= timedelta(days=1)
            if not (pd.Timestamp(START).date() <= c < pd.Timestamp(END).date()):
                continue
            ev.append(("E2_gotobi_long_usdjpy", "USDJPY", 1, utc_ms(c, 7, 0, "tokyo"), utc_ms(c, 9, 55, "tokyo")))
    for day in days:
        ev.append(("E3_short_eur_gbp_london_am", "EURUSD", -1, utc_ms(day, 7, 0, "london"), utc_ms(day, 12, 0, "london")))
        ev.append(("E3_short_eur_gbp_london_am", "GBPUSD", -1, utc_ms(day, 7, 0, "london"), utc_ms(day, 12, 0, "london")))
        ev.append(("E3_long_eur_gbp_ny_am", "EURUSD", 1, utc_ms(day, 8, 30, "ny"), utc_ms(day, 12, 0, "ny")))
        ev.append(("E3_long_eur_gbp_ny_am", "GBPUSD", 1, utc_ms(day, 8, 30, "ny"), utc_ms(day, 12, 0, "ny")))
        ev.append(("E3_long_usdjpy_tokyo", "USDJPY", 1, utc_ms(day, 9, 0, "tokyo"), utc_ms(day, 15, 0, "tokyo")))
        if day.weekday() < 4:
            nxt = day + timedelta(days=1)
            ev.append(("E5_spx_overnight", "SPXUSD", 1, utc_ms(day, 16, 0, "ny"), utc_ms(nxt, 9, 30, "ny")))
    # month-end: direction from S&P 500 month-to-date (prior month-end close -> 10:00 London today)
    spx = pd.read_csv(HERE / "data" / "ohlcv" / "SPX_USD_bid_1m.csv", usecols=["timestamp", "close"])
    st, sc = spx.timestamp.to_numpy(), spx.close.to_numpy()

    def spx_at(ms):
        i = np.searchsorted(st, ms, side="right") - 1
        return sc[i] if i >= 0 else np.nan

    for m in months:
        last = m.end_time.date()
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        prev_last = (m - 1).end_time.date()
        while prev_last.weekday() >= 5:
            prev_last -= timedelta(days=1)
        t_in, t_out = utc_ms(last, 10, 0, "london"), utc_ms(last, 16, 0, "london")
        if not (sfx.ms(START) <= t_in < sfx.ms(END)):
            continue
        mtd = spx_at(t_in) / spx_at(utc_ms(prev_last, 16, 0, "ny")) - 1
        if not np.isfinite(mtd) or mtd == 0:
            continue
        sell_usd = mtd > 0
        for s in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
            side = -USD_SIGN[s] if sell_usd else USD_SIGN[s]
            ev.append(("E4_month_end_rebalance", s, side, t_in, t_out))
    return ev


@njit(cache=True)
def run_trades(t, O, H, L, C, side, ent, ext, dist, spread, slip, comm):
    n = len(side)
    out = np.full((n, 3), np.nan)  # R_net, R_gross, stopped
    for k in range(n):
        i = np.searchsorted(t, ent[k])
        j = np.searchsorted(t, ext[k])
        if i >= len(t) or j >= len(t) or j <= i or t[i] - ent[k] > 300000 or t[j] - ext[k] > 300000:
            continue
        s = side[k]
        e_mid = O[i] + spread / 2
        e = O[i] + (spread if s > 0 else 0.0) + s * slip
        stop = e - s * dist[k]
        px = np.nan
        stopped = 0.0
        for m in range(i, j):
            if s > 0 and L[m] <= stop:
                px = min(O[m], stop) - slip; stopped = 1.0; break
            if s < 0 and H[m] + spread >= stop:
                px = max(O[m] + spread, stop) + slip; stopped = 1.0; break
        if np.isnan(px):
            px = (O[j] if s > 0 else O[j] + spread) - s * slip
        x_mid = O[j] + spread / 2 if stopped == 0.0 else px
        out[k, 0] = (s * (px - e) - comm * (e + px)) / dist[k]
        out[k, 1] = s * (x_mid - e_mid) / dist[k]
        out[k, 2] = stopped
    return out


def main():
    ev = pd.DataFrame(events(), columns=["strategy", "symbol", "side", "entry_ms", "exit_ms"])
    rows = []
    for sym, g in ev.groupby("symbol"):
        f = pd.read_csv(HERE / "data" / "ohlcv" / f"{sym[:3]}_{sym[3:]}_bid_1m.csv")
        t = f.timestamp.to_numpy(np.int64)
        d1 = sfx.make_bars(f, "D1")
        tr = pd.concat([d1.high - d1.low, (d1.high - d1.close.shift()).abs(), (d1.low - d1.close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(20, min_periods=15).mean().to_numpy()
        k = np.searchsorted(d1.close_ms.to_numpy(), g.entry_ms.to_numpy(), side="right") - 1
        pip, spread, slip, comm = ins.SPEC[sym]
        dist = np.where(k >= 0, 0.5 * atr[np.clip(k, 0, None)], np.nan)
        dist = np.maximum(dist, 5 * pip)
        res = run_trades(t, f.open.to_numpy(), f.high.to_numpy(), f.low.to_numpy(), f.close.to_numpy(),
                         g.side.to_numpy(np.int64), g.entry_ms.to_numpy(np.int64), g.exit_ms.to_numpy(np.int64),
                         np.nan_to_num(dist, nan=1e9), spread, slip, comm)
        gg = g.copy()
        gg["R"], gg["R_gross"], gg["stopped"] = res[:, 0], res[:, 1], res[:, 2]
        rows.append(gg)
    tr = pd.concat(rows).dropna(subset=["R"])
    tr["date"] = pd.to_datetime(tr.exit_ms, unit="ms").dt.normalize()
    tr["year"] = tr.date.dt.year
    report = {"rules": __doc__, "per_strategy": {}, "per_strategy_symbol": {}}
    for name, g in tr.groupby("strategy"):
        r = g.R.to_numpy()
        tstat = float(r.mean() / r.std() * np.sqrt(len(r))) if r.std() > 0 else 0.0
        tg = float(g.R_gross.mean() / g.R_gross.std() * np.sqrt(len(g))) if g.R_gross.std() > 0 else 0.0
        daily = g.groupby("date").R.sum()
        eq = np.cumprod(1 + RISK * daily.to_numpy())
        peak = np.maximum.accumulate(eq)
        yrs = (daily.index[-1] - daily.index[0]).days / 365.25
        report["per_strategy"][name] = dict(
            trades=len(g), mean_R_net=round(float(r.mean()), 4), t_net=round(tstat, 2),
            mean_R_gross=round(float(g.R_gross.mean()), 4), t_gross=round(tg, 2),
            cost_R_per_trade=round(float(g.R_gross.mean() - r.mean()), 4),
            stop_rate=round(float(g.stopped.mean()), 3),
            cagr_at_0_5pct=round(float(eq[-1] ** (1 / yrs) - 1), 4), maxdd_at_0_5pct=round(float(np.max(1 - eq / peak)), 4),
            yearly_R={int(y): round(float(v), 1) for y, v in g.groupby("year").R.sum().items()},
            yearly_R_gross={int(y): round(float(v), 1) for y, v in g.groupby("year").R_gross.sum().items()})
        for sym, h in g.groupby("symbol"):
            report["per_strategy_symbol"][f"{name}|{sym}"] = dict(
                trades=len(h), mean_R_net=round(float(h.R.mean()), 4), mean_R_gross=round(float(h.R_gross.mean()), 4),
                t_gross=round(float(h.R_gross.mean() / h.R_gross.std() * np.sqrt(len(h))), 2) if h.R_gross.std() > 0 else 0.0)
        print(f"{name:32s} n={len(g):6d} netR={r.mean():+.4f} t={tstat:+.2f} | grossR={g.R_gross.mean():+.4f} t={tg:+.2f} "
              f"| CAGR@0.5%={report['per_strategy'][name]['cagr_at_0_5pct']:+.3f} DD={report['per_strategy'][name]['maxdd_at_0_5pct']:.3f}")
    (HERE / "reports" / "fx_anomalies.json").write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
