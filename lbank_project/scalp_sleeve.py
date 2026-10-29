"""Chabok: optional fourth PAPER-ONLY 15m breakout sleeve, with a 1h trend filter.

Research candidate, NOT a proven profitable strategy. No live futures orders.
OHLCV is supplied by scalp_candles.py (last, forming bar is always discarded).
The entry strategy uses no true volume because LBank quote sampling has none.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

import c3_sleeve as c3
import lbank_bot as bot

LOG = logging.getLogger("scalp_sleeve")
NAME = "Chabok"
TF_SECONDS = {"15m": 900, "1h": 3600}
DEFAULTS = dict(
    enabled=False, dry_run_mode=True, timeframe="15m", trend_timeframe="1h",
    symbols=[], paper_capital=10000.0, risk_per_trade_pct=0.0015,
    max_notional_pct=0.25, max_open_positions=2, isolated_leverage=5,
    round_trip_fee=0.0012, sizing_slippage_pct=0.0004,
    ema_entry=20, ema_trend_fast=50, ema_trend_slow=200,
    rsi_period=14, atr_period=14, breakout_lookback=20,
    stop_atr=2.0, trail_atr=2.5, min_stop_pct=0.006,
    min_atr_pct=0.0015, time_stop_bars=48, daily_max_loss_pct=0.005,
    candle_fetch_limit=300, trend_candle_fetch_limit=350,
    check_interval_seconds=15,
)


def validate(c: dict) -> dict:
    if not isinstance(c, dict) or set(c) != set(DEFAULTS):
        raise ValueError("Chabok configuration keys must match the shipped schema")
    if c["dry_run_mode"] is not True or type(c["enabled"]) is not bool:
        raise ValueError("Chabok is PAPER ONLY")
    if (c["timeframe"], c["trend_timeframe"]) != ("15m", "1h"):
        raise ValueError("Only 15m entries with a closed 1h filter were designed")
    if not c["symbols"] or len(c["symbols"]) != len(set(c["symbols"])):
        raise ValueError("Distinct symbols required")
    if any(not isinstance(s, str) or not s.endswith("/USDT:USDT") for s in c["symbols"]):
        raise ValueError("Only USDT linear contracts")
    for k in ("ema_entry", "ema_trend_fast", "ema_trend_slow", "rsi_period",
              "atr_period", "breakout_lookback", "time_stop_bars",
              "max_open_positions", "isolated_leverage", "candle_fetch_limit",
              "trend_candle_fetch_limit", "check_interval_seconds"):
        if type(c[k]) is not int or c[k] <= 0:
            raise ValueError("Invalid positive integer: " + k)
    if c["ema_trend_fast"] >= c["ema_trend_slow"]:
        raise ValueError("Trend fast EMA must be shorter")
    if not 1 <= c["isolated_leverage"] <= 5 or not 1 <= c["max_open_positions"] <= 2:
        raise ValueError("Paper leverage <= 5x and at most 2 open positions")
    if c["candle_fetch_limit"] < max(150, 3 * c["ema_entry"], c["breakout_lookback"] + 10):
        raise ValueError("Insufficient 15m history")
    if c["trend_candle_fetch_limit"] < c["ema_trend_slow"] + 100:
        raise ValueError("Insufficient closed 1h trend history")
    bounds = {
        "risk_per_trade_pct": (0, 0.0025), "max_notional_pct": (0, 0.3),
        "round_trip_fee": (0, 0.02), "sizing_slippage_pct": (0, 0.02),
        "stop_atr": (0.5, 10), "trail_atr": (1, 15),
        "min_stop_pct": (0.004, 0.03), "min_atr_pct": (0.0005, 0.02),
        "daily_max_loss_pct": (0, 0.02), "paper_capital": (0, 1e12),
    }
    for k, (lo, hi) in bounds.items():
        v = c[k]
        if type(v) not in (float, int) or not math.isfinite(v) or not lo < v <= hi:
            raise ValueError("Invalid risk parameter: " + k)
    return dict(c)


def features(rows: list, now: float, seconds: int, c: dict) -> pd.DataFrame:
    """No future bar, no invented history, no candle gaps."""
    df = pd.DataFrame(rows, columns=("timestamp", "open", "high", "low", "close", "volume"))
    if df.empty:
        raise ValueError("No OHLCV history")
    df = df.astype(float).iloc[:-1].copy()
    df = df[df.timestamp + seconds * 1000 <= now * 1000].reset_index(drop=True)
    if len(df) < 100 or (np.diff(df.timestamp.to_numpy()) != seconds * 1000).any():
        raise ValueError("Missing or noncontiguous closed candles")
    if not np.isfinite(df[["open", "high", "low", "close"]].to_numpy()).all():
        raise ValueError("Non-finite OHLC")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Invalid OHLC")
    close = df.close
    tr = pd.concat(
        (df.high - df.low, (df.high - close.shift()).abs(), (df.low - close.shift()).abs()), axis=1
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / c["atr_period"], adjust=False).mean()
    delta = close.diff().fillna(0.0)
    gain = delta.clip(lower=0).ewm(alpha=1 / c["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / c["rsi_period"], adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.where(loss > 0, 1e-12))
    df["ema_entry"] = close.ewm(span=c["ema_entry"], adjust=False).mean()
    df["ema_fast"] = close.ewm(span=c["ema_trend_fast"], adjust=False).mean()
    df["ema_slow"] = close.ewm(span=c["ema_trend_slow"], adjust=False).mean()
    return df


def signal(entry: pd.DataFrame, trend: pd.DataFrame, c: dict) -> str | None:
    """15m close breaks prior highs/lows in a CLOSED 1h directional regime."""
    if len(entry) < c["breakout_lookback"] + 2 or len(trend) < c["ema_trend_slow"] + 100:
        return None
    b, prev, h = entry.iloc[-1], entry.iloc[-2], trend.iloc[-1]
    if not math.isfinite(b.atr) or b.atr / b.close < c["min_atr_pct"]:
        return None
    highs = entry.high.iloc[-c["breakout_lookback"] - 1:-1]
    lows = entry.low.iloc[-c["breakout_lookback"] - 1:-1]
    bullish = h.ema_fast > h.ema_slow and h.close > h.ema_fast
    bearish = h.ema_fast < h.ema_slow and h.close < h.ema_fast
    if (bullish and b.close > highs.max() and b.close > b.ema_entry
            and b.ema_entry > prev.ema_entry and 55 <= b.rsi <= 75):
        return "long"
    if (bearish and b.close < lows.min() and b.close < b.ema_entry
            and b.ema_entry < prev.ema_entry and 25 <= b.rsi <= 45):
        return "short"
    return None


class Sleeve(c3.Sleeve):
    NAME = NAME
    LOG = LOG

    def __init__(self, config, store, data, base_equity=None, shared_account=None):
        self.c = validate(config)
        self.store, self.data = store, data
        self.base_equity, self._shared_account = base_equity, shared_account

    def _open(self, symbol: str, side: str, bar: pd.Series, now: float):
        """Shared lock is owned by c3.Sleeve.open; sizing always uses shared margin."""
        if not bot.license_access.entries_allowed(now):
            return None
        account = self.shared_account
        if account is None or not account.engine.config.read()["portfolio_risk"]["shared_c3_account"]:
            return None
        if not self.c["enabled"] or any(p["symbol"] == symbol for p in self.store.positions()):
            return None
        if len(self.store.positions()) >= self.c["max_open_positions"]:
            return None
        day_start = int(now // 86400) * 86400
        with self.store.db() as db:
            daily = float(db.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE closed>=?", (day_start,)
            ).fetchone()[0])
        equity = self.equity()
        if equity <= 0 or daily <= -equity * self.c["daily_max_loss_pct"]:
            return None
        price = self.data.price(symbol)
        if abs(price - float(bar.close)) > 0.5 * float(bar.atr):
            return None  # never chase large post-close gaps
        sign = 1 if side == "long" else -1
        distance = max(self.c["stop_atr"] * float(bar.atr), self.c["min_stop_pct"] * price)
        stop = price - sign * distance
        if stop <= 0:
            return None
        risk_fraction = distance / price + self.c["round_trip_fee"] + self.c["sizing_slippage_pct"]
        notional = min(
            equity * self.c["risk_per_trade_pct"] / risk_fraction,
            equity * self.c["max_notional_pct"],
            account.available_margin(
                equity, leverage=self.c["isolated_leverage"],
                fee_rate=self.c["round_trip_fee"]
            ) * self.c["isolated_leverage"],
        )
        if notional < 20:
            return None
        contract_size = float(self.data.market(symbol).get("contractSize") or 1)
        contracts = self.data.precision(symbol, notional / (price * contract_size))
        quantity = contracts * contract_size
        if quantity <= 0 or not self.data.tradable(symbol, contracts, price):
            return None
        with self.store.db() as db:
            db.execute(
                "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (symbol, side, price, quantity, stop, float(bar.close), now,
                 int(bar.timestamp), int(bar.timestamp), quantity * distance),
            )
            db.execute(
                "INSERT OR REPLACE INTO position_margin VALUES(?,?,?)",
                (symbol, now, self.c["isolated_leverage"]),
            )
        LOG.info("Chabok paper entry %s %s %.6g stop %.6g qty %.6g",
                 symbol, side, price, stop, quantity)
        return True

    def scan(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        ok = True
        c = self.c
        for symbol in c["symbols"]:
            try:
                entry = features(
                    self.data.candles(symbol, "15m", c["candle_fetch_limit"]), now, 900, c
                )
                trend = features(
                    self.data.candles(symbol, "1h", c["trend_candle_fetch_limit"]), now, 3600, c
                )
                if (len(entry) < c["candle_fetch_limit"] - 1 or
                        len(trend) < c["trend_candle_fetch_limit"] - 1):
                    raise ValueError("Insufficient uninterrupted 15m/1h warm-up history")
                b = entry.iloc[-1]
                stamp = int(b.timestamp)
                expected15 = (int(now) // 900 - 1) * 900 * 1000
                expected1h = (int(now) // 3600 - 1) * 3600 * 1000
                if stamp != expected15 or int(trend.iloc[-1].timestamp) != expected1h:
                    raise ValueError("Stale 15m or 1h futures candles")
                with self.store.db() as db:
                    last = db.execute(
                        "SELECT candle_ts FROM scanned WHERE symbol=?", (symbol,)
                    ).fetchone()
                if last and stamp <= last[0]:
                    continue
                position = next(
                    (p for p in self.store.positions() if p["symbol"] == symbol), None
                )
                closed_for_time = False
                if position:
                    if (stamp - position["signal_ts"]) // (900 * 1000) >= c["time_stop_bars"]:
                        self.close(position, self.data.price(symbol), "time", now)
                        position = None
                        closed_for_time = True
                    elif stamp > position["last_bar_ts"]:
                        sign = 1 if position["side"] == "long" else -1
                        best = max(position["best"], float(b.close)) if sign == 1 else min(position["best"], float(b.close))
                        candidate = best - sign * c["trail_atr"] * float(b.atr)
                        new_stop = max(position["stop"], candidate) if sign == 1 else min(position["stop"], candidate)
                        with self.execution_lock(), self.store.db() as db:
                            db.execute(
                                "UPDATE positions SET best=?,stop=?,last_bar_ts=? "
                                "WHERE symbol=? AND opened=? AND last_bar_ts<?",
                                (best, new_stop, stamp, symbol, position["opened"], stamp)
                            )
                # Don't re-enter on the same candle after a time stop.
                if position is None and c["enabled"] and not closed_for_time:
                    side = signal(entry, trend, c)
                    if side:
                        self.open(symbol, side, b, now)
                with self.store.db() as db:
                    db.execute(
                        "INSERT INTO scanned VALUES(?,?) ON CONFLICT(symbol) "
                        "DO UPDATE SET candle_ts=MAX(candle_ts,excluded.candle_ts)",
                        (symbol, stamp),
                    )
            except Exception:
                ok = False
                LOG.exception("Chabok scan failed for %s", symbol)
        return ok


def load(path: Path) -> dict:
    return validate(json.loads(path.read_text()))


def write_config(path: Path, value: dict) -> dict:
    import tempfile
    c = validate(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False,
                                     prefix="scalp.", suffix=".tmp") as fp:
        fp.write(json.dumps(c, indent=2) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
        name = fp.name
    os.replace(name, path)
    return c


def paths() -> tuple[Path, c3.Store]:
    here = Path(__file__).resolve().parent
    shipped = here / "scalp_config.json"
    path = Path(os.getenv("SCALP_CONFIG", str(shipped)))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_config(path, json.loads(shipped.read_text()))
    store = c3.Store(Path(os.getenv("SCALP_DB", str(here / "data/scalp_sleeve.db"))))
    return path, store


def summary(store, config, price, base_equity):
    return c3.summary(store, dict(config, confirm_bars=0), price, base_equity, net_costs=True)


def loop(sleeve, path, stop=None, once=False):
    last = None
    while not (stop and stop.is_set()):
        now = time.time()
        try:
            try:
                sleeve.c = load(path)
            except Exception:
                LOG.exception("Chabok config unreadable; retaining last valid settings")
            boundary = int(now) // 900 * 900
            if boundary != last and now >= boundary + 3 and sleeve.scan(now):
                last = boundary
        except Exception:
            LOG.exception("Chabok scan loop error")
        finally:
            sleeve.watchdog(now)  # stops still checked if candles are stale or invalid
        if once:
            break
        (stop.wait if stop else time.sleep)(sleeve.c["check_interval_seconds"])


def start_in_bot(engine, stop):
    import threading
    if os.getenv("SCALP_IN_BOT", "0") != "1":
        LOG.info("Chabok disabled by SCALP_IN_BOT (defaults to 0)")
        return None
    path, store = paths()
    sleeve = Sleeve(load(path), store, bot.MarketData(),
                    base_equity=engine.main_paper_equity,
                    shared_account=engine.shared_paper_account)
    thread = threading.Thread(target=loop, args=(sleeve, path, stop),
                              name="scalp-sleeve", daemon=True)
    thread.start()
    return thread


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = bot.Engine(bot.ConfigStore(), bot.Database(), bot.MarketData())
    path, store = paths()
    loop(Sleeve(load(path), store, bot.MarketData(),
                base_equity=engine.main_paper_equity,
                shared_account=engine.shared_paper_account), path, once=args.once)


if __name__ == "__main__":
    main()
