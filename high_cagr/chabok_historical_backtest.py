"""Reproducible 2021-2026 Chabok 15m/1h historical research backtest.

Run in CI with downloads from Binance Vision USDT-M futures archive. NOT LBank.
15m OHLC stop simulation is lower resolution than original 1m research engine.
All rules are the frozen, unoptimized scalp_sleeve.py candidate, no parameter search.
"""
from __future__ import annotations
import calendar
import concurrent.futures as cf
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
START = "2021-01"
END = "2026-09"
FEE_SIDE = 0.0006
SLIP_SIDE = 0.0002
RISK = 0.0015
CAP_PER_TRADE = 0.25
MARGIN_CAP = 0.80
LEVERAGE = 5
INITIAL = 10000.0
MIN_ATR_RATIO = 0.0015
STOP_ATR = 2.0
TRAIL_ATR = 2.5
MIN_STOP = 0.006
TIME_STOP_BARS = 48
MAX_POSITIONS = 2
DAILY_STOP = 0.005
OUT = Path("high_cagr/output/chabok")


def months(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def archive_url(sym, kind, interval, ym):
    if kind == "funding":
        return f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"
    return f"{BASE}/klines/{sym}/{interval}/{sym}-{interval}-{ym}.zip"


def get_archive(job):
    sym, kind, interval, ym = job
    url = archive_url(sym, kind, interval, ym)
    error = None
    for trial in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Trade-Chabok-Research/1.0"})
            with urllib.request.urlopen(req, timeout=35) as resp:
                raw = resp.read()
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                member = next(n for n in zf.namelist() if n.endswith(".csv"))
                contents = zf.read(member)
            df = pd.read_csv(io.BytesIO(contents), header=None, low_memory=False)
            if kind == "funding":
                ts = pd.to_numeric(df.iloc[:, 0], errors="coerce")
                rate = pd.to_numeric(df.iloc[:, 2], errors="coerce")
                frame = pd.DataFrame({"ts": ts, "rate": rate}).dropna()
            else:
                values = [pd.to_numeric(df.iloc[:, k], errors="coerce") for k in range(6)]
                frame = pd.DataFrame(dict(zip(("ts", "open", "high", "low", "close", "volume"), values))).dropna()
            frame = frame[frame.ts > 1e11].copy()
            if not frame.empty:
                # Binance spot files later switched to microseconds; validate units.
                frame.loc[frame.ts > 1e14, "ts"] //= 1000
                frame["ts"] = frame.ts.astype("int64")
            return job, frame, None
        except urllib.error.HTTPError as e:
            error = f"{e.code} {e.reason}"
            if e.code == 404:
                break
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        time.sleep((trial + 1) * 1.5)
    return job, None, error


def load_historical():
    dates = list(months(START, END))
    jobs = [(sym, kind, interval, ym)
            for sym in SYMBOLS
            for kind, interval in (("kline", "15m"), ("kline", "1h"), ("funding", ""))
            for ym in dates]
    groups = {(sym, kind, interval): [] for sym in SYMBOLS
              for kind, interval in (("kline", "15m"), ("kline", "1h"), ("funding", ""))}
    misses = []
    print(f"DOWNLOAD_START {len(jobs)} Binance monthly USDT-M archives", flush=True)
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        for idx, (job, frame, error) in enumerate(pool.map(get_archive, jobs), 1):
            sym, kind, interval, ym = job
            if frame is None or frame.empty:
                misses.append(dict(symbol=sym, kind=kind, interval=interval, month=ym, error=error or "empty"))
            else:
                groups[(sym, kind, interval)].append(frame)
            if idx % 60 == 0:
                print(f"DOWNLOAD_PROGRESS {idx}/{len(jobs)} missing={len(misses)}", flush=True)
    essential = [m for m in misses if m["kind"] == "kline"]
    if essential:
        raise RuntimeError(f"Missing required monthly OHLCV files ({len(essential)}): {essential[:15]}")
    result = {}
    for key, parts in groups.items():
        if not parts:
            result[key] = pd.DataFrame(columns=["ts", "rate"])
            continue
        df = pd.concat(parts, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        result[key] = df
        if key[1] == "kline":
            step = 900000 if key[2] == "15m" else 3600000
            gaps = int((np.diff(df.ts.to_numpy()) != step).sum())
            print(f"DATA {key[0]} {key[2]} rows={len(df)} gaps={gaps} "
                  f"start={pd.to_datetime(df.ts.iloc[0],unit='ms',utc=True)} "
                  f"end={pd.to_datetime(df.ts.iloc[-1],unit='ms',utc=True)}", flush=True)
            if gaps:
                raise RuntimeError(f"{key[0]} {key[2]} contains {gaps} unexpected gaps")
    print(f"FUNDING_MISSING_MONTHS {len([x for x in misses if x['kind']=='funding'])}", flush=True)
    return result, misses


def enriched(quarter, hours):
    """Exact runtime EMA/ATR/RSI warm-up convention with only closed bars."""
    a = quarter.copy()
    c = a["close"]
    prior = c.shift()
    tr = pd.concat((a.high-a.low, (a.high-prior).abs(), (a.low-prior).abs()), axis=1).max(axis=1)
    a["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    delta = c.diff().fillna(0.0)
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    a["rsi"] = 100 - 100 / (1 + up / down.where(down != 0, 1e-12))
    a["ema"] = c.ewm(span=20, adjust=False).mean()
    old_high = a.high.shift(1).rolling(20).max()
    old_low = a.low.shift(1).rolling(20).min()
    long = ((a.close > old_high) & (a.close > a.ema) &
            (a.ema > a.ema.shift()) & a.rsi.between(55,75) &
            (a.atr / a.close >= MIN_ATR_RATIO))
    short = ((a.close < old_low) & (a.close < a.ema) &
             (a.ema < a.ema.shift()) & a.rsi.between(25,45) &
             (a.atr / a.close >= MIN_ATR_RATIO))
    h = hours.copy()
    h["ema_fast"] = h.close.ewm(span=50, adjust=False).mean()
    h["ema_slow"] = h.close.ewm(span=200, adjust=False).mean()
    h["trend_bar"] = np.arange(len(h))
    h["decision_ts"] = h.ts + 3600000
    a["decision_ts"] = a.ts + 900000
    a = pd.merge_asof(a.sort_values("decision_ts"), h[["decision_ts", "ema_fast", "ema_slow", "close", "trend_bar"]]
                      .rename(columns={"close": "trend_close"}), on="decision_ts", direction="backward")
    warm = (np.arange(len(a)) >= 299) & (a.trend_bar >= 349)
    bullish = (a.ema_fast > a.ema_slow) & (a.trend_close > a.ema_fast)
    bearish = (a.ema_fast < a.ema_slow) & (a.trend_close < a.ema_fast)
    a["side"] = np.select([warm & long & bullish, warm & short & bearish], [1,-1], default=0)
    # Tests deliberately evaluate this vector result against the unchanged source
    # code's pure signal() at 30+ historical windows before allowing a report.
    return a


def parity_check(symbol, frame, hframe):
    import scalp_sleeve as S
    rng = np.random.default_rng(20261029)
    candidates = np.where(frame.side.to_numpy() != 0)[0]
    random_indexes = rng.choice(np.arange(1450, len(frame)-2), min(50, len(frame)-1452), replace=False)
    checks = sorted(set(list(random_indexes) + list(candidates[::max(1,len(candidates)//40)][:40])))
    # Recompute original two features on 300+350 closed bars, with forming bars.
    # Historical signal bar i must be closed before passing as-of close time.
    for i in checks:
        decision = int(frame.ts.iloc[i]) + 900000
        q_start = max(0, i - 299)
        qa = frame.iloc[q_start:i+1]
        fake = [list(r) for r in qa[["ts","open","high","low","close","volume"]].itertuples(index=False, name=None)]
        fake.append([decision, frame.open.iloc[i],frame.open.iloc[i],frame.open.iloc[i],frame.open.iloc[i],0])
        h_ix = int(np.searchsorted(hframe.ts.to_numpy() + 3600000, decision, side="right")-1)
        ht = hframe.iloc[max(0,h_ix-349):h_ix+1]
        hfake = [list(r) for r in ht[["ts","open","high","low","close","volume"]].itertuples(index=False, name=None)]
        hfake.append([decision//3600000*3600000,hframe.close.iloc[h_ix],
                      hframe.close.iloc[h_ix],hframe.close.iloc[h_ix],hframe.close.iloc[h_ix],0])
        if len(fake) < 301 or len(hfake) < 351:
            continue
        f15 = S.features(fake, decision/1000+3, 900, S.DEFAULTS)
        f1h = S.features(hfake, decision/1000+3, 3600, S.DEFAULTS)
        want = S.signal(f15, f1h, S.DEFAULTS)
        side = 1 if want == "long" else -1 if want == "short" else 0
        if side != int(frame.side.iloc[i]):
            raise AssertionError(f"{symbol} signal parity failed at {frame.ts.iloc[i]}: {side} vs {frame.side.iloc[i]}")
    print(f"PARITY {symbol} checked={len(checks)}", flush=True)


def simulate(raw, misses):
    frames = {}
    for sym in SYMBOLS:
        frames[sym] = enriched(raw[(sym, "kline", "15m")], raw[(sym, "kline", "1h")])
        parity_check(sym, frames[sym], raw[(sym, "kline", "1h")])
    # Both selected assets are continuous on one common clock.
    ticks = frames[SYMBOLS[0]].ts.to_numpy(dtype="int64")
    for sym in SYMBOLS[1:]:
        if not np.array_equal(frames[sym].ts.to_numpy(dtype="int64"), ticks):
            raise RuntimeError(f"Mismatched shared 15m clock for {sym}")
    arrays = {s: {k: frames[s][k].to_numpy() for k in
               ("open","high","low","close","atr","side","ts")} for s in SYMBOLS}
    funding = {}
    for sym in SYMBOLS:
        f = raw[(sym,"funding","")]
        funding[sym] = dict(zip(f.ts.to_numpy(dtype="int64"), f.rate.to_numpy(dtype="float64")))
    cash = INITIAL
    positions = {}
    trades = []
    daily = []
    realized_today = 0.0
    realized_year = None
    cost_fees = 0.0
    cost_slippage = 0.0
    total_funding = 0.0
    max_used = 0.0
    exposure_sum = 0.0
    exposure_ticks = 0
    max_bar_dd = 0.0
    peak_bar = INITIAL
    entry_rejections = dict(gap=0, max_positions=0, margin=0, daily_loss=0)
    last_mark = {s: float(arrays[s]["open"][0]) for s in SYMBOLS}
    n = len(ticks)

    def equity():
        return cash + sum(p["side"] * p["qty"] * (last_mark[s]-p["entry"])
                          - FEE_SIDE * p["qty"]*last_mark[s] for s,p in positions.items())

    def close_pos(sym, raw_price, reason, time_ms):
        nonlocal cash, realized_today, cost_fees, cost_slippage
        p = positions.pop(sym)
        actual = raw_price * (1 - p["side"] * SLIP_SIDE)
        fees = FEE_SIDE * p["qty"] * actual
        pnl = p["side"] * p["qty"] * (actual-p["entry"]) - fees - p["fee_entry"] + p["funding"]
        cash += p["side"] * p["qty"] * (actual-p["entry"]) - fees
        realized_today += pnl
        cost_fees += fees
        cost_slippage += abs(actual-raw_price)*p["qty"]
        trades.append({
            "symbol":sym, "side":p["side"], "entry_ts":p["entry_ts"], "exit_ts":int(time_ms),
            "entry":p["entry"],"exit":actual,"qty":p["qty"],"pnl_net":pnl,
            "fees":p["fee_entry"]+fees,"funding":p["funding"],"reason":reason,
            "hours_held":(time_ms-p["entry_ts"])/3600000
        })

    for i, ts in enumerate(ticks):
        utc_day = int(ts//86400000)
        if realized_year != utc_day:
            realized_today = 0.0
            realized_year = utc_day
        for sym in SYMBOLS:
            last_mark[sym] = float(arrays[sym]["open"][i])

        # Evaluate the previous fully closed 15m bar, then simulate entry at this open.
        for sym in SYMBOLS:
            if i == 0 or sym in positions:
                continue
            arr = arrays[sym]
            signal_side = int(arr["side"][i-1])
            if not signal_side:
                continue
            if len(positions) >= MAX_POSITIONS:
                entry_rejections["max_positions"] += 1
                continue
            eq = equity()
            if realized_today <= -DAILY_STOP * max(eq,1):
                entry_rejections["daily_loss"] += 1
                continue
            px = float(arr["open"][i])
            atr = float(arr["atr"][i-1])
            close_signal = float(arr["close"][i-1])
            if abs(px-close_signal) > .5*atr:
                entry_rejections["gap"] += 1
                continue
            filled = px*(1+signal_side*SLIP_SIDE)
            distance = max(STOP_ATR*atr, MIN_STOP*filled)
            margin_used = sum(p["qty"]*p["entry"]/LEVERAGE for p in positions.values())
            available = max(0, MARGIN_CAP*eq-margin_used)
            # Margins reserve new position's fee (same shared-account budget convention).
            notional = min(eq*RISK/(distance/filled+2*FEE_SIDE+2*SLIP_SIDE),
                           CAP_PER_TRADE*eq,
                           available/(1+MARGIN_CAP*LEVERAGE*2*FEE_SIDE)*LEVERAGE)
            if notional < 20 or filled-distance <= 0:
                entry_rejections["margin"] += 1
                continue
            qty = notional/filled
            entry_fee = qty*filled*FEE_SIDE
            cash -= entry_fee
            cost_fees += entry_fee
            cost_slippage += abs(filled-px)*qty
            positions[sym] = dict(
                side=signal_side,entry=filled,qty=qty,
                stop=filled-signal_side*distance, best=close_signal,
                signal_idx=i-1,entry_ts=int(ts),fee_entry=entry_fee,funding=0.0
            )
        for sym in SYMBOLS:
            arr = arrays[sym]
            b_open,b_high,b_low,b_close = (float(arr[k][i]) for k in ("open","high","low","close"))
            last_mark[sym] = b_close
            if sym not in positions:
                continue
            p = positions[sym]
            if p["side"] == 1 and b_low <= p["stop"]:
                close_pos(sym, min(p["stop"],b_open), "stop", ts+900000)
                continue
            if p["side"] == -1 and b_high >= p["stop"]:
                close_pos(sym, max(p["stop"],b_open), "stop", ts+900000)
                continue
            if i-p["signal_idx"] >= TIME_STOP_BARS:
                close_pos(sym, b_close, "time", ts+900000)
                continue
            # Pay/receive real monthly Binance funding snapshots at settlement.
            rate = funding[sym].get(int(ts+900000))
            if rate is not None:
                cost = -p["side"]*p["qty"]*b_close*rate
                cash += cost
                p["funding"] += cost
                total_funding += cost
            p["best"] = max(p["best"],b_close) if p["side"]==1 else min(p["best"],b_close)
            candidate = p["best"]-p["side"]*TRAIL_ATR*float(arr["atr"][i])
            p["stop"] = max(p["stop"],candidate) if p["side"]==1 else min(p["stop"],candidate)
        eq = equity()
        used = sum(p["qty"]*p["entry"]/LEVERAGE for p in positions.values())
        ratio = used/max(eq,1)
        max_used = max(max_used,ratio)
        exposure_sum += ratio
        exposure_ticks += 1
        peak_bar = max(peak_bar,eq)
        max_bar_dd = max(max_bar_dd,(peak_bar-eq)/peak_bar)
        if int(ts+900000) % 86400000 == 0:
            daily.append((int(ts+900000),eq))
        if i % 40000 == 0:
            print(f"REPLAY_PROGRESS {i}/{n} equity={eq:.2f} trades={len(trades)}",flush=True)

    # Mark to market last positions at dataset end (do not count them as closed trades).
    final = equity()
    d = pd.DataFrame(daily,columns=["ts","equity"])
    if d.empty:
        raise RuntimeError("Daily equity never recorded")
    d["date"] = pd.to_datetime(d.ts,unit="ms",utc=True)
    start_year = INITIAL
    yearly = {}
    for year, group in d.groupby(d.date.dt.year,sort=True):
        end = float(group.equity.iloc[-1])
        yearly[str(year)] = round(100*(end/start_year-1),3)
        start_year = end
    g = pd.DataFrame(trades)
    pf = float(g.loc[g.pnl_net>0,"pnl_net"].sum()/(-g.loc[g.pnl_net<0,"pnl_net"].sum())) if not g.empty and (g.pnl_net<0).any() else None
    wins = float(100*(g.pnl_net>0).mean()) if not g.empty else None
    timespan_years = (int(ticks[-1])-int(ticks[0]))/86400000/365.25
    daily_dd = float((1-d.equity/d.equity.cummax().clip(lower=INITIAL)).max())
    result = {
        "model": "historical Binance USDT-M 15m/1h closed-bar OHLCV, not LBank; 15m intrabar stop checks",
        "date_start":str(pd.to_datetime(ticks[0],unit="ms",utc=True)),
        "date_end":str(pd.to_datetime(ticks[-1]+900000,unit="ms",utc=True)),
        "source":"https://data.binance.vision/data/futures/um/monthly/",
        "symbols":list(SYMBOLS), "start_equity":INITIAL,
        "final_equity_marked":round(final,2),
        "net_return_pct":round((final/INITIAL-1)*100,3),
        "cagr_pct":round(100*((final/INITIAL)**(1/timespan_years)-1),3) if final>0 else -100,
        "max_dd_15m_close_pct":round(100*max_bar_dd,3),
        "max_dd_daily_pct":round(100*daily_dd,3),
        "profit_factor":round(pf,4) if pf is not None else None,
        "win_rate_pct":round(wins,3) if wins is not None else None,
        "closed_trades":len(trades),
        "trades_per_symbol":g.symbol.value_counts().to_dict() if not g.empty else {},
        "positive_trade_count":int((g.pnl_net>0).sum()) if not g.empty else 0,
        "negative_trade_count":int((g.pnl_net<0).sum()) if not g.empty else 0,
        "total_fees_usd":round(cost_fees,2),
        "total_slippage_usd":round(cost_slippage,2),
        "net_funding_usd":round(total_funding,2),
        "funding_archive_missing_months":len([x for x in misses if x["kind"]=="funding"]),
        "average_margin_pct":round(100*exposure_sum/exposure_ticks,3),
        "max_margin_pct":round(100*max_used,3),
        "years":yearly, "rejected_entries":entry_rejections,
        "exit_reasons":g.reason.value_counts().to_dict() if not g.empty else {},
        "assumptions": [
            "2 bps unfavorable slippage per entry and exit; 0.06% taker fee each side",
            "Funding applied from monthly Binance history when available; missing funding months not imputed",
            "Entry at the following 15m bar open after both 15m/1h are fully closed",
            "Stop checked against next/entry 15m candle extremes, no tick or 1m execution model",
            "No orderbook liquidity, exchange-specific spread, lot/tick precision, liquidation, or margin tiers",
            "Single-strategy account only: no claim of combined results with the existing three bots",
            "Historical 15m klines differ from 10-second sampled LBank paper candles"
        ]
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"result.json").write_text(json.dumps(result,indent=2,ensure_ascii=False))
    d.to_csv(OUT/"daily_equity.csv",index=False)
    g.to_csv(OUT/"trades.csv",index=False)
    print("BACKTEST_RESULT_JSON "+json.dumps(result,ensure_ascii=False),flush=True)
    return result


if __name__ == "__main__":
    historical,missing = load_historical()
    simulate(historical,missing)
