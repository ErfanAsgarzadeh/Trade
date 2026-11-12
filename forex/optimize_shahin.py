#!/usr/bin/env python3
"""Research-only adaptation of Shahin's 4h Donchian/Kumo/ATR core to spot FX.

Requires real Dukascopy bid AND ask 1m data, with matching manifests.
This is NOT a byte-for-byte port of the crypto kernel: no pyramiding,
exchange liquidation, crypto funding, or live order execution.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PAIRS = ("EURUSD", "GBPUSD", "USDJPY")
START, SPLIT_TRAIN, SPLIT_VALID, END = (
    "2021-11-12", "2025-01-01", "2026-01-01", "2026-11-12"
)
FOUR_HOURS_MS, MINUTE_MS = 14_400_000, 60_000
DAY_MS = 86_400_000
SEED_USD = 10_000.0
SCHEMA = ("timestamp", "open", "high", "low", "close", "volume")
RESEARCH_ASSUMPTIONS = {
    "signals": "4h closed mid-price Donchian breakout confirmed outside shifted Ichimoku Kumo",
    "stop": "2*ATR-like initial stop, trailed by last closed Donchian10 channel",
    "floor": "After 1R favourable touch, move stop to +0.1R on the following minute",
    "execution": "next available 1m bid/ask open, stop at adverse quote with gap-open protection",
    "costs": "observed bid/ask spread + user-adjustable adverse slippage + assumed broker commission",
    "omissions": "swap/rollover, broker margin calls, tick-level ordering, pyramids and live integration",
    "scope": "one-position-per-pair; independent $10k capital per pair, not shared-margin portfolio",
}

def ts_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def load_checked_pair(data_dir: Path, pair: str, expected_start: str, expected_end: str):
    if pair not in PAIRS:
        raise ValueError("Unsupported pair")
    files = []
    for side in ("bid", "ask"):
        mf = data_dir / f"manifest_{side}.json"
        if not mf.is_file():
            raise FileNotFoundError(f"Missing {mf}. Run download_forex.py --side {side}")
        manifest = json.loads(mf.read_text())
        if manifest.get("start") != expected_start or manifest.get("end") != expected_end:
            raise ValueError(f"{mf}: range mismatch, request full five-year history")
        if manifest.get("side") != side or manifest.get("source") != "Dukascopy via dukascopy-node":
            raise ValueError(f"{mf}: source or side not verified")
        entry = manifest.get("symbols", {}).get(pair, {}).get("outputs", {}).get("1m")
        if not entry:
            raise ValueError(f"{pair} {side} has no verified 1m manifest output")
        path = (data_dir / entry["file"]).resolve()
        if not path.is_relative_to(data_dir.resolve()) or not path.is_file():
            raise FileNotFoundError(f"Missing/unsafe path for {pair} {side}: {path}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"{path}: SHA-256 mismatch")
        frame = pd.read_csv(path, dtype={"timestamp": "int64", **{k: "float64" for k in SCHEMA[1:]}})
        if tuple(frame.columns) != SCHEMA or len(frame) != entry["rows"]:
            raise ValueError(f"{path}: schema or row count mismatch")
        stamp = frame.timestamp.to_numpy()
        if len(stamp) < 250_000 or not np.all(np.diff(stamp) > 0):
            raise ValueError(f"{pair} {side}: inadequate five-year coverage or unordered minutes")
        if np.any(stamp % MINUTE_MS):
            raise ValueError(f"{pair} {side}: not minute aligned")
        lo, hi = ts_ms(expected_start), ts_ms(expected_end)
        if stamp[0] < lo or stamp[-1] >= hi or stamp[0] > lo + 7 * DAY_MS or stamp[-1] < hi - 7 * DAY_MS:
            raise ValueError(f"{pair} {side}: boundary coverage invalid")
        if len(stamp) < 0.55 * (hi - lo) / MINUTE_MS:
            raise ValueError(f"{pair} {side}: suspiciously low market-session coverage")
        prices = frame[list(SCHEMA[1:5])].to_numpy()
        if not np.isfinite(frame[list(SCHEMA[1:])].to_numpy()).all() or np.any(prices <= 0):
            raise ValueError(f"{pair} {side}: invalid prices/volumes")
        if (frame.volume < 0).any() or (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any():
            raise ValueError(f"{pair} {side}: invalid OHLC")
        if int(stamp[0]) != int(entry["first_ms"]) or int(stamp[-1]) != int(entry["last_ms"]):
            raise ValueError(f"{pair} {side}: first/last timestamp differs from manifest")
        files.append((frame, entry["sha256"]))
    bid, ask = files[0][0], files[1][0]
    if not np.array_equal(bid.timestamp.to_numpy(), ask.timestamp.to_numpy()):
        raise ValueError(f"{pair}: bid/ask minute timestamps do not align (no forward fill permitted)")
    if (ask.open < bid.open).any() or (ask.close < bid.close).any():
        raise ValueError(f"{pair}: crossed bid/ask quotations")
    gap = np.diff(bid.timestamp.to_numpy())
    if np.any(gap > 5 * DAY_MS):
        raise ValueError(f"{pair}: unexplained data gap longer than five days")
    return bid, ask, {"pair": pair, "bid_sha256": files[0][1], "ask_sha256": files[1][1],
                       "minutes": len(bid), "gaps": int((gap > MINUTE_MS).sum())}

def compute_bars(bid: pd.DataFrame, ask: pd.DataFrame, preset: str, n: int):
    period = (9, 26, 52, 26) if preset == "standard" else (20, 60, 120, 30)
    t = bid.timestamp.to_numpy()
    mid = pd.DataFrame({"bucket": t // FOUR_HOURS_MS})
    for col in ("open", "high", "low", "close"):
        mid[col] = (bid[col].to_numpy() + ask[col].to_numpy()) / 2
    mid["volume"] = bid.volume.to_numpy()
    grouped = mid.groupby("bucket", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), count=("close", "size"))
    # Never fill missing weekends. Do not trade on incomplete 4h candles.
    f = grouped.loc[grouped["count"] == 240, ["open", "high", "low", "close", "volume"]].copy()
    f.insert(0, "timestamp", f.index.to_numpy(dtype="int64") * FOUR_HOURS_MS)
    f.reset_index(drop=True, inplace=True)
    def midline(window):
        return (f.high.rolling(window).max() + f.low.rolling(window).min()) / 2
    ten, kij, sen_b = midline(period[0]), midline(period[1]), midline(period[2])
    f["kumo_top"] = pd.concat([(ten + kij).shift(period[3]) / 2,
                                sen_b.shift(period[3])], axis=1).max(axis=1, skipna=False)
    f["kumo_bottom"] = pd.concat([(ten + kij).shift(period[3]) / 2,
                                   sen_b.shift(period[3])], axis=1).min(axis=1, skipna=False)
    f["don_high"] = f.high.rolling(n).max().shift(1)
    f["don_low"] = f.low.rolling(n).min().shift(1)
    f["trail_low"] = f.low.rolling(10).min()
    f["trail_high"] = f.high.rolling(10).max()
    tr = pd.concat([f.high - f.low,
                    (f.high - f.close.shift(1)).abs(),
                    (f.low - f.close.shift(1)).abs()], axis=1).max(axis=1)
    # Continuous Wilder-like EWM rather than the crypto engine's reset-199 window.
    f["atr"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    f["atr_median"] = f.atr.rolling(60).median().shift(1)
    return f

@dataclass(frozen=True)
class Settings:
    preset: str = "standard"
    donchian: int = 10
    atr_mult: float = 2.0
    min_stop_pips: float = 8.0
    atr_gate: bool = True

def grid() -> list[Settings]:
    return [Settings(*vals) for vals in itertools.product(
        ("standard", "crypto"), (10, 20), (1.5, 2.0, 2.5), (8.0, 15.0), (True, False))]

def case_key(s: Settings) -> str:
    return f"{s.preset}_N{s.donchian}_ATR{s.atr_mult:g}_PIP{s.min_stop_pips:g}_G{int(s.atr_gate)}"

def signal(row, settings: Settings) -> int:
    keys = ("close", "kumo_top", "kumo_bottom", "don_high", "don_low", "atr", "atr_median")
    if any(not math.isfinite(float(row[k])) for k in keys):
        return 0
    if row.atr <= 0 or (settings.atr_gate and row.atr < row.atr_median):
        return 0
    if row.close > max(row.kumo_top, row.don_high):
        return 1
    if row.close < min(row.kumo_bottom, row.don_low):
        return -1
    return 0

def usd_per_quote(pair: str, ask_price: float) -> float:
    # EURUSD/GBPUSD quoted in USD; USDJPY P&L is JPY converted to USD.
    return 1.0 if pair != "USDJPY" else 1.0 / ask_price

def usd_notional_per_base(pair: str, mid_price: float) -> float:
    return 1.0 if pair == "USDJPY" else mid_price

def pip_size(pair: str) -> float:
    return 0.01 if pair == "USDJPY" else 0.0001

def fill_price(raw: float, side: int, slippage_bps: float) -> float:
    """side=+1 buys at worse price; side=-1 sells at worse price."""
    return raw * (1 + side * slippage_bps / 10_000)

def position_size(equity: float, entry: float, stop: float, ask_price: float,
                  pair: str, risk_pct: float, leverage: float, margin_cap: float,
                  commission_rt_per_100k: float, lot_units: int) -> int:
    unit_loss_usd = abs(entry - stop) * usd_per_quote(pair, ask_price)
    notional_unit_usd = usd_notional_per_base(pair, ask_price)
    round_trip_fee_per_unit = notional_unit_usd * commission_rt_per_100k / 100_000
    per_unit_risk = unit_loss_usd + round_trip_fee_per_unit
    if per_unit_risk <= 0 or equity <= 0:
        return 0
    by_risk = equity * risk_pct / per_unit_risk
    by_margin = equity * leverage * margin_cap / notional_unit_usd
    return max(0, math.floor(min(by_risk, by_margin) / lot_units) * lot_units)

def summarize(initial: float, final: float, max_dd: float, trades: list[dict], days: float):
    pnl = np.asarray([t["net_usd"] for t in trades], dtype=float)
    pos = pnl[pnl > 0]
    neg = pnl[pnl < 0]
    return {
        "trades": len(trades), "wins": int(len(pos)),
        "win_rate_pct": float(100 * len(pos) / len(trades)) if trades else 0.0,
        "return_pct": float(100 * (final / initial - 1)),
        "cagr_pct": float(100 * ((final / initial) ** (365.2425 / days) - 1)) if final > 0 and days > 0 else None,
        "max_daily_dd_pct": float(100 * max_dd),
        "profit_factor": float(pos.sum() / -neg.sum()) if len(neg) and -neg.sum() > 0 else None,
        "net_usd": float(final - initial),
        "final_equity_usd": float(final),
    }

def run_period(pair: str, bid: pd.DataFrame, ask: pd.DataFrame, bars: pd.DataFrame,
               settings: Settings, start: str, end: str, *,
               risk_pct=0.0075, leverage=5, margin_cap=0.8,
               commission_rt_per_100k=7.0, slippage_bps=0.5, lot_units=1000):
    begin_ms, end_ms = ts_ms(start), ts_ms(end)
    times = bid.timestamp.to_numpy(dtype="int64")
    i0, i1 = int(np.searchsorted(times, begin_ms)), int(np.searchsorted(times, end_ms))
    if i1 <= i0:
        raise ValueError(f"{pair}: no minutes in period {start}..{end}")
    bid_o, bid_h, bid_l, bid_c = [bid[c].to_numpy() for c in ("open", "high", "low", "close")]
    ask_o, ask_h, ask_l, ask_c = [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
    bts = bars.timestamp.to_numpy(dtype="int64")
    # signal and trailing changes become available only at the *next* bar opening.
    closed_at = bts + FOUR_HOURS_MS
    action = np.full(i1 - i0, -1, dtype=np.int32)
    for j, close_ts in enumerate(closed_at):
        if close_ts < begin_ms or close_ts >= end_ms:
            continue
        idx = int(np.searchsorted(times, close_ts))
        if i0 <= idx < i1 and times[idx] == close_ts:
            action[idx - i0] = j
    balance = SEED_USD
    peak = balance
    dd = 0.0
    pos = None
    trades = []
    prev_day = None
    last_t = None

    def mark(i: int):
        if pos is None:
            return balance
        quote = bid_c[i] if pos["side"] == 1 else ask_c[i]
        conversion = usd_per_quote(pair, ask_c[i])
        return balance + pos["side"] * (quote - pos["entry"]) * pos["qty"] * conversion

    def close(i: int, raw: float, why: str):
        nonlocal balance, pos
        price = fill_price(raw, -pos["side"], slippage_bps)
        gross = pos["side"] * (price - pos["entry"]) * pos["qty"] * usd_per_quote(pair, ask_c[i])
        notional = pos["qty"] * usd_notional_per_base(pair, ask_c[i])
        exit_fee = notional * commission_rt_per_100k / 200_000
        balance += gross - exit_fee
        net = gross - pos["entry_fee"] - exit_fee
        trades.append({"entry_ms": pos["entry_ms"], "exit_ms": int(times[i]),
                       "side": pos["side"], "qty_base": pos["qty"],
                       "entry": float(pos["entry"]), "exit": float(price),
                       "net_usd": float(net), "exit_reason": why})
        pos = None

    for i in range(i0, i1):
        t = int(times[i])
        day = t // DAY_MS
        if prev_day is not None and day != prev_day:
            eq = mark(i - 1)
            peak = max(peak, eq)
            if peak > 0:
                dd = max(dd, max(0.0, (peak - eq) / peak))
        prev_day, last_t = day, t
        bar_idx = int(action[i - i0])
        if bar_idx >= 0 and pos is not None:
            b = bars.iloc[bar_idx]
            if math.isfinite(b.trail_low) and math.isfinite(b.trail_high):
                level = float(b.trail_low if pos["side"] == 1 else b.trail_high)
                if pos["side"] == 1:
                    pos["stop"] = max(pos["stop"], level)
                else:
                    pos["stop"] = min(pos["stop"], level)

        exited = False
        if pos is not None:
            side = pos["side"]
            if pos["floor_next"]:
                lock = pos["entry"] + side * 0.1 * pos["initial_risk"]
                pos["stop"] = max(pos["stop"], lock) if side == 1 else min(pos["stop"], lock)
                pos["floor_next"] = False
                pos["floor_done"] = True
            stop = pos["stop"]
            open_quote = bid_o[i] if side == 1 else ask_o[i]
            touched = bid_l[i] <= stop if side == 1 else ask_h[i] >= stop
            if touched or (side == 1 and open_quote <= stop) or (side == -1 and open_quote >= stop):
                # Conservatively price stop at open when market gaps beyond it.
                raw = min(open_quote, stop) if side == 1 else max(open_quote, stop)
                close(i, raw, "stop")
                exited = True
            elif not pos["floor_done"]:
                favourable = bid_h[i] if side == 1 else ask_l[i]
                if side * (favourable - pos["entry"]) >= pos["initial_risk"]:
                    pos["floor_next"] = True

        if bar_idx >= 0 and pos is None and not exited:
            bar = bars.iloc[bar_idx]
            side = signal(bar, settings)
            if side:
                raw = ask_o[i] if side == 1 else bid_o[i]
                entry = fill_price(raw, side, slippage_bps)
                proposed_stop = float(bar.close - side * settings.atr_mult * bar.atr)
                risk_distance = side * (entry - proposed_stop)
                if risk_distance > 0 and risk_distance >= settings.min_stop_pips * pip_size(pair):
                    qty = position_size(balance, entry, proposed_stop, ask_o[i],
                                        pair, risk_pct, leverage, margin_cap,
                                        commission_rt_per_100k, lot_units)
                    if qty >= lot_units:
                        entry_fee = qty * usd_notional_per_base(pair, ask_o[i]) * commission_rt_per_100k / 200_000
                        balance -= entry_fee
                        pos = {"side": side, "entry": float(entry), "stop": proposed_stop,
                               "initial_risk": float(risk_distance), "entry_ms": t, "qty": qty,
                               "entry_fee": float(entry_fee), "floor_done": False, "floor_next": False}
        if balance <= 0:
            raise ValueError(f"{pair}: equity exhausted; invalid cost/risk settings")

    if pos is not None:
        raw = bid_c[i1 - 1] if pos["side"] == 1 else ask_c[i1 - 1]
        close(i1 - 1, raw, "period_end")
    peak = max(peak, balance)
    dd = max(dd, max(0.0, (peak - balance) / peak)) if peak > 0 else dd
    stats = summarize(SEED_USD, balance, dd, trades, (end_ms - begin_ms) / DAY_MS)
    stats["period_start"] = start
    stats["period_end_exclusive"] = end
    stats["last_candle_ms"] = last_t
    return stats

def score(group: dict[str, dict]) -> float:
    # Robust across three independently capitalised pairs, not a shared portfolio.
    returns = np.array([v["return_pct"] for v in group.values()])
    dd = np.array([v["max_daily_dd_pct"] for v in group.values()])
    return float(np.mean(returns) - 0.8 * np.mean(dd) - 0.2 * np.std(returns))

def evaluate_pair(data_dir: Path, pair: str, options: list[Settings], phase: str,
                  start: str, end: str, costs: dict) -> tuple[dict, dict]:
    bid, ask, provenance = load_checked_pair(data_dir, pair, START, END)
    bar_cache = {}
    results = {}
    for setting in options:
        identity = (setting.preset, setting.donchian)
        if identity not in bar_cache:
            bar_cache[identity] = compute_bars(bid, ask, *identity)
        results[case_key(setting)] = run_period(pair, bid, ask, bar_cache[identity],
                                                 setting, start, end, **costs)
    return results, provenance

def run_optimization(data_dir: Path, report_dir: Path, costs: dict,
                     cases: list[Settings] | None = None) -> dict:
    cases = cases or grid()
    if not cases:
        raise ValueError("No candidates")
    # Verify that every pair and both quote sides exist before attempting a costly study.
    for pair in PAIRS:
        for side in ("bid", "ask"):
            path = data_dir / f"manifest_{side}.json"
            if not path.is_file():
                raise FileNotFoundError(f"Missing {path}: download both bid and ask first")
    provenance, result_train = {}, {}
    for pair in PAIRS:
        p, meta = evaluate_pair(data_dir, pair, cases, "train", START, SPLIT_TRAIN, costs)
        provenance[pair] = meta
        for cid, metrics in p.items():
            result_train.setdefault(cid, {})[pair] = metrics
    candidates = sorted(cases, key=lambda c: (-score(result_train[case_key(c)]), case_key(c)))
    shortlist = candidates[:min(8, len(candidates))]
    result_val = {}
    for pair in PAIRS:
        p, _ = evaluate_pair(data_dir, pair, shortlist, "validation", SPLIT_TRAIN, SPLIT_VALID, costs)
        for cid, metrics in p.items():
            result_val.setdefault(cid, {})[pair] = metrics
    # Selection is fully determined before the held-out 2026 sample is evaluated.
    eligible = [c for c in shortlist if sum(result_val[case_key(c)][p]["trades"] for p in PAIRS) >= 9]
    if not eligible:
        eligible = shortlist  # Flag weak-sample selection rather than silently dropping it.
    winner = sorted(eligible, key=lambda c: (-score(result_val[case_key(c)]), case_key(c)))[0]
    test = {}
    for pair in PAIRS:
        result, _ = evaluate_pair(data_dir, pair, [winner], "test", SPLIT_VALID, END, costs)
        test[pair] = result[case_key(winner)]
    selected = case_key(winner)
    report = {
        "status": "completed_real_bid_ask_data", "model": "Shahin FX research core",
        "methodology": RESEARCH_ASSUMPTIONS, "costs": costs, "coverage": provenance,
        "periods": {"train": [START, SPLIT_TRAIN], "validation": [SPLIT_TRAIN, SPLIT_VALID],
                    "untouched_test": [SPLIT_VALID, END]},
        "candidate_count": len(cases), "shortlist": [case_key(x) for x in shortlist],
        "train_scores": {case_key(x): score(result_train[case_key(x)]) for x in candidates},
        "validation_scores": {case_key(x): score(result_val[case_key(x)]) for x in shortlist},
        "weak_validation_trade_count": not any(
            sum(result_val[case_key(c)][p]["trades"] for p in PAIRS) >= 9 for c in shortlist),
        "selected_case": asdict(winner), "selected_id": selected,
        "train_per_pair": result_train[selected], "validation_per_pair": result_val[selected],
        "untouched_test_per_pair": test,
        "mean_test_return_pct": float(np.mean([test[p]["return_pct"] for p in PAIRS])),
        "warning": "Research only. No USD portfolio DD, tick ordering, swaps, margin liquidation or live execution.",
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / "shahin_forex_5y.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temp.replace(target)
    return report

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--risk-pct", type=float, default=0.0075)
    parser.add_argument("--leverage", type=float, default=5)
    parser.add_argument("--margin-cap", type=float, default=0.8)
    parser.add_argument("--commission-rt-per-100k", type=float, default=7)
    parser.add_argument("--slippage-bps", type=float, default=0.5)
    parser.add_argument("--lot-units", type=int, default=1000)
    args = parser.parse_args()
    if not (0 < args.risk_pct <= 0.02 and 1 <= args.leverage <= 30 and 0 < args.margin_cap <= 1
            and args.commission_rt_per_100k >= 0 and 0 <= args.slippage_bps <= 10
            and args.lot_units >= 1):
        parser.error("Invalid risk, leverage, commission, slippage or lot-size assumptions")
    costs = dict(risk_pct=args.risk_pct, leverage=args.leverage, margin_cap=args.margin_cap,
                 commission_rt_per_100k=args.commission_rt_per_100k,
                 slippage_bps=args.slippage_bps, lot_units=args.lot_units)
    report = run_optimization(args.data_dir, args.report_dir or args.data_dir / "reports", costs)
    print(json.dumps({"selected_id": report["selected_id"],
                      "test_per_pair": report["untouched_test_per_pair"],
                      "report": str(args.report_dir or args.data_dir / "reports" / "shahin_forex_5y.json")},
                     indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
