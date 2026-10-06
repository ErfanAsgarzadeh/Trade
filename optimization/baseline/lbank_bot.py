"""Closed-candle LBank futures strategy and paper execution engine.

CCXT 4.5.85 exposes LBank contract market data but only spot order entry.
Live execution is deliberately rejected rather than routed to spot endpoints.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import tempfile
import threading
import time
from typing import Any

import ccxt
import numpy as np
import pandas as pd

LOG = logging.getLogger("lbank_bot")
PENDING = "STATE_PENDING_TRIGGER"
INITIAL = "STATE_INITIAL"
TRAILING = "STATE_TRAILING_KIJUN"
LIVE_LIMITATION = (
    "Live LBank futures execution is unavailable: the pinned CCXT adapter uses "
    "spot order endpoints and has no futures reduceOnly, leverage, margin or "
    "position reconciliation support. Keep dry_run_mode=true."
)
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "1d": 86400}
SCHEMA = {
    "bot_control": {"auto_trade_enabled": bool, "dry_run_mode": bool, "check_interval_seconds": int},
    "strategy_mode": {"mode": str, "htf_trend_timeframe": str, "ltf_entry_timeframe": str, "single_timeframe": str},
    "symbols": list,
    "ichimoku_params": {"tenkan": int, "kijun": int, "senkou_b": int, "displacement": int, "candle_fetch_limit": int},
    "filters_and_triggers": {"rsi_period": int, "long_rsi_min": float, "long_rsi_max": float,
        "short_rsi_min": float, "short_rsi_max": float, "atr_period": int,
        "kijun_touch_atr_tolerance": float, "max_kijun_extension_atr": float},
    "al_brooks_filters": {"enable_barb_wire_filter": bool, "barb_wire_lookback": int,
        "barb_wire_min_overlap_ratio": float, "barb_wire_doji_body_ratio": float,
        "require_signal_bar_breakout": bool, "stop_entry_atr_buffer": float,
        "pending_order_expiry_bars": int, "require_h2_l2_pullback": bool, "h2_l2_lookback_bars": int},
    "risk_and_exit": {"risk_per_trade_pct": float, "max_open_positions": int,
        "max_margin_per_position_pct": float, "default_isolated_leverage": int,
        "sl_atr_buffer": float, "tp1_rr_ratio": float, "tp1_close_pct": float,
        "daily_max_loss_pct": float, "lbank_round_trip_fee": float}}


class ConfigError(ValueError):
    """Invalid or unsafe configuration."""


class LiveUnavailable(RuntimeError):
    """An unverified live futures execution path was requested."""


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate_config(c: dict) -> dict:
    """Validate exact schema, finite numeric values and cross-field constraints."""
    if not isinstance(c, dict) or set(c) != set(SCHEMA):
        raise ConfigError("Configuration must use the supplied top-level schema")
    for section, template in SCHEMA.items():
        if isinstance(template, dict):
            if not isinstance(c[section], dict) or set(c[section]) != set(template):
                raise ConfigError(f"Invalid keys in {section}")
            for key, value in template.items():
                actual = c[section][key]
                if value is bool:
                    ok = type(actual) is bool
                elif value is int:
                    ok = type(actual) is int
                elif value is float:
                    ok = type(actual) in (int, float) and math.isfinite(actual)
                else:
                    ok = isinstance(actual, value)
                if not ok:
                    raise ConfigError(f"Invalid type/value: {section}.{key}")
    syms = c["symbols"]
    if (not isinstance(syms, list) or not syms
            or not all(isinstance(s, str) and re.fullmatch(r"[A-Z0-9]+/USDT:USDT", s) for s in syms)
            or len(set(syms)) != len(syms)):
        raise ConfigError("symbols must contain unique USDT linear swap symbols")
    b, s, i, f, a, r = (c[k] for k in ["bot_control", "strategy_mode",
        "ichimoku_params", "filters_and_triggers", "al_brooks_filters", "risk_and_exit"])
    if s["mode"] not in ("MTF", "SINGLE"):
        raise ConfigError("mode must be MTF or SINGLE")
    if any(s[k] not in TIMEFRAMES for k in ("htf_trend_timeframe", "ltf_entry_timeframe", "single_timeframe")):
        raise ConfigError("Unsupported timeframe")
    if s["mode"] == "MTF" and TIMEFRAMES[s["htf_trend_timeframe"]] < TIMEFRAMES[s["ltf_entry_timeframe"]]:
        raise ConfigError("HTF must be at least as large as LTF")
    if not 1 <= b["check_interval_seconds"] <= 300:
        raise ConfigError("check_interval_seconds must be between 1 and 300")
    if not (1 <= i["tenkan"] <= i["kijun"] <= i["senkou_b"] and i["displacement"] > 0):
        raise ConfigError("Invalid Ichimoku periods")
    needed = max(i["senkou_b"] + 2 * i["displacement"],
                 f["rsi_period"] + 1, f["atr_period"], a["h2_l2_lookback_bars"] + 2) + 2
    if not needed <= i["candle_fetch_limit"] <= 2000:
        raise ConfigError(f"candle_fetch_limit must be between {needed} and 2000")
    if not (2 <= f["rsi_period"] <= 200 and 2 <= f["atr_period"] <= 200):
        raise ConfigError("Invalid RSI/ATR periods")
    for side in ("long", "short"):
        if not 0 <= f[f"{side}_rsi_min"] <= f[f"{side}_rsi_max"] <= 100:
            raise ConfigError("Invalid RSI range")
    if not (0 <= f["kijun_touch_atr_tolerance"] <= 5 and 0 < f["max_kijun_extension_atr"] <= 20):
        raise ConfigError("Invalid Kijun tolerance/extension")
    if not (2 <= a["barb_wire_lookback"] <= 50 and 2 <= a["h2_l2_lookback_bars"] <= 100
            and 1 <= a["pending_order_expiry_bars"] <= 100):
        raise ConfigError("Invalid price-action lookbacks or expiry")
    if not (0 <= a["barb_wire_min_overlap_ratio"] <= 1 and
            0 <= a["barb_wire_doji_body_ratio"] <= 1 and 0 <= a["stop_entry_atr_buffer"] <= 5):
        raise ConfigError("Invalid price-action thresholds")
    if not (0.001 <= r["risk_per_trade_pct"] <= 0.05 and 1 <= r["max_open_positions"] <= 100
            and 0 < r["max_margin_per_position_pct"] <= 1
            and 1 <= r["default_isolated_leverage"] <= 125
            and 0 < r["daily_max_loss_pct"] <= 1
            and 0 < r["tp1_close_pct"] < 1 and 0 < r["tp1_rr_ratio"] <= 100
            and 0 < r["sl_atr_buffer"] <= 20 and 0 <= r["lbank_round_trip_fee"] < 0.1):
        raise ConfigError("Invalid risk/exit configuration")
    if not b["dry_run_mode"]:
        raise ConfigError(LIVE_LIMITATION)
    return copy.deepcopy(c)


class ConfigStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("BOT_CONFIG", "config.json")).resolve()
        self.lock_path = self.path.with_suffix(".lock")
        with file_lock(self.lock_path):
            if not self.path.exists():
                self._write(json.loads(Path(__file__).with_name("config.json").read_text()))

    def _write(self, c: dict):
        # Mount the containing directory, never this file, so rename is visible
        # to both containers. Readers do not replace the file.
        data = json.dumps(c, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                         prefix=self.path.name + ".", suffix=".tmp", delete=False) as h:
            temporary = Path(h.name)
            try:
                h.write(data)
                h.flush()
                os.fsync(h.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self.path)
            fd = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self) -> dict:
        with file_lock(self.lock_path):
            return validate_config(json.loads(self.path.read_text(encoding="utf-8")))

    def write(self, c: dict):
        value = validate_config(c)
        with file_lock(self.lock_path):
            self._write(value)

    def stop_entries(self):
        with file_lock(self.lock_path):
            c = json.loads(self.path.read_text(encoding="utf-8"))
            # Panic must still disable entries when another config field is invalid.
            c["bot_control"]["auto_trade_enabled"] = False
            self._write(c)


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trade_lock = self.path.with_suffix(".trade.lock")
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
              symbol TEXT PRIMARY KEY, side TEXT NOT NULL, entry_price REAL NOT NULL,
              qty REAL NOT NULL, initial_sl REAL NOT NULL, active_sl REAL NOT NULL,
              tp1_price REAL NOT NULL, state TEXT NOT NULL,
              trigger_price REAL DEFAULT 0.0, cancel_price REAL DEFAULT 0.0,
              expiry_ts INTEGER DEFAULT 0,
              dry_run INTEGER NOT NULL DEFAULT 1, contract_size REAL NOT NULL DEFAULT 1,
              fee_rate REAL NOT NULL DEFAULT 0.0012, tp1_close_pct REAL NOT NULL DEFAULT 0.5,
              tp1_rr REAL NOT NULL DEFAULT 1.5, risk_budget REAL NOT NULL DEFAULT 0,
              max_notional REAL NOT NULL DEFAULT 0, timeframe TEXT NOT NULL DEFAULT '1h',
              signal_ts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS trade_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL,
              pnl_usd REAL NOT NULL, closed_at INTEGER NOT NULL,
              qty REAL NOT NULL, entry_price REAL NOT NULL, exit_price REAL NOT NULL,
              reason TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS history_time ON trade_history(closed_at);
            CREATE TABLE IF NOT EXISTS scanned_candles (
              symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_ts INTEGER NOT NULL,
              PRIMARY KEY(symbol,timeframe));
            CREATE TABLE IF NOT EXISTS runtime (
              key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextlib.contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def positions(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM positions ORDER BY symbol")]

    def position(self, symbol: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            return dict(row) if row else None

    def history_summary(self, now: float) -> tuple[float, int]:
        with self.connect() as db:
            row = db.execute("SELECT COALESCE(SUM(pnl_usd),0),COUNT(*) FROM trade_history "
                             "WHERE closed_at>=?", (now - 86400,)).fetchone()
            return float(row[0]), int(row[1])

    def runtime_set(self, key: str, value: Any):
        with self.connect() as db:
            db.execute("INSERT INTO runtime(key,value) VALUES (?,?) ON CONFLICT(key) "
                       "DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def runtime_all(self) -> dict:
        with self.connect() as db:
            return {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM runtime")}


def wilder(values: pd.Series, period: int) -> pd.Series:
    """Seed with the first period's SMA; then use Wilder's recursive smoothing."""
    result = np.full(len(values), np.nan)
    raw = values.to_numpy(dtype=float)
    start = next((i for i in range(len(raw)) if np.isfinite(raw[i])), len(raw))
    seed = start + period - 1
    if seed < len(raw) and np.isfinite(raw[start:seed + 1]).all():
        result[seed] = float(raw[start:seed + 1].mean())
        for index in range(seed + 1, len(raw)):
            if not np.isfinite(raw[index]):
                break
            result[index] = (result[index - 1] * (period - 1) + raw[index]) / period
    return pd.Series(result, index=values.index)


def indicators(bars: list, c: dict, timeframe: str, now: float) -> pd.DataFrame:
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise ValueError("Empty OHLCV response")
    df = df.astype(float)
    if not np.isfinite(df.to_numpy()).all() or not df.timestamp.is_monotonic_increasing or df.timestamp.duplicated().any():
        raise ValueError("Non-finite, duplicate or unsorted candles")
    if ((df.high < df[["open", "close", "low"]].max(axis=1)) |
        (df.low > df[["open", "close", "high"]].min(axis=1)) |
        (df[["open", "high", "low", "close"]].min(axis=1) <= 0) |
        (df.volume < 0)).any():
        raise ValueError("Invalid OHLCV geometry")
    # Always discard the final exchange bar as specified, then enforce its time.
    df = df.iloc[:-1].copy()
    seconds = TIMEFRAMES[timeframe]
    df = df[df.timestamp + seconds * 1000 <= now * 1000].reset_index(drop=True)
    if len(df) and (np.diff(df.timestamp) != seconds * 1000).any():
        raise ValueError("Gaps in candle history")
    i, f = c["ichimoku_params"], c["filters_and_triggers"]
    for name, period in (("tenkan", i["tenkan"]), ("kijun", i["kijun"]), ("senkou_b_future", i["senkou_b"])):
        df[name] = (df.high.rolling(period).max() + df.low.rolling(period).min()) / 2
    df["senkou_a_future"] = (df.tenkan + df.kijun) / 2
    df["senkou_a_curr"] = df.senkou_a_future.shift(i["displacement"])
    df["senkou_b_curr"] = df.senkou_b_future.shift(i["displacement"])
    df["kumo_top"] = df[["senkou_a_curr", "senkou_b_curr"]].max(axis=1, skipna=False)
    df["kumo_bottom"] = df[["senkou_a_curr", "senkou_b_curr"]].min(axis=1, skipna=False)
    delta = df.close.diff()
    gain = wilder(delta.clip(lower=0), f["rsi_period"])
    loss = wilder(-delta.clip(upper=0), f["rsi_period"])
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    df.loc[(gain == 0) & (loss > 0), "rsi"] = 0.0
    df.loc[(gain == 0) & (loss == 0), "rsi"] = 50.0
    previous = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - previous).abs(),
                    (df.low - previous).abs()], axis=1).max(axis=1)
    df["atr"] = wilder(tr, f["atr_period"])
    return df


def regime(df: pd.DataFrame, c: dict) -> str | None:
    displacement = c["ichimoku_params"]["displacement"]
    if len(df) <= displacement:
        return None
    bar, prior = df.iloc[-1], df.iloc[-1 - displacement]
    fields = ["close", "tenkan", "kijun", "senkou_a_future", "senkou_b_future", "kumo_top", "kumo_bottom", "atr"]
    if not np.isfinite(bar[fields]).all() or not np.isfinite(prior[["high", "low", "kumo_top", "kumo_bottom"]]).all() or bar.atr <= 0:
        return None
    if bar.kumo_bottom <= bar.close <= bar.kumo_top or abs(bar.senkou_a_future - bar.senkou_b_future) < 0.15 * bar.atr:
        return None
    if (bar.close > bar.kumo_top and bar.tenkan >= bar.kijun and
            bar.senkou_a_future > bar.senkou_b_future and
            bar.close > prior.high and bar.close > prior.kumo_top):
        return "long"
    if (bar.close < bar.kumo_bottom and bar.tenkan <= bar.kijun and
            bar.senkou_a_future < bar.senkou_b_future and
            bar.close < prior.low and bar.close < prior.kumo_bottom):
        return "short"
    return None


def entry_signal(df: pd.DataFrame, side: str, c: dict) -> bool:
    f, a = c["filters_and_triggers"], c["al_brooks_filters"]
    t = len(df) - 1
    if side not in ("long", "short") or t < max(a["barb_wire_lookback"], a["h2_l2_lookback_bars"] + 1):
        return False
    b = df.iloc[t]
    if not np.isfinite(b[["kijun", "rsi", "atr"]]).all() or b.atr <= 0:
        return False
    if abs(b.close - b.kijun) > f["max_kijun_extension_atr"] * b.atr:
        return False
    if side == "long":
        touch = b.low <= b.kijun + f["kijun_touch_atr_tolerance"] * b.atr and b.close > b.kijun
    else:
        touch = b.high >= b.kijun - f["kijun_touch_atr_tolerance"] * b.atr and b.close < b.kijun
    if not touch or not f[f"{side}_rsi_min"] <= b.rsi <= f[f"{side}_rsi_max"]:
        return False
    if a["enable_barb_wire_filter"]:
        tail = df.iloc[t - a["barb_wire_lookback"] + 1:t + 1]
        doji = any(abs(row.close - row.open) <= a["barb_wire_doji_body_ratio"] * max(row.high - row.low, 1e-8)
                   for row in tail.itertuples())
        overlaps = []
        for index in range(1, len(tail)):
            x, y = tail.iloc[index], tail.iloc[index - 1]
            overlaps.append(max(0.0, min(x.high, y.high) - max(x.low, y.low)) / max(x.high - x.low, 1e-8))
        if doji and all(v >= a["barb_wire_min_overlap_ratio"] for v in overlaps):
            return False
    if a["require_h2_l2_pullback"]:
        found = False
        for k in range(max(1, t - a["h2_l2_lookback_bars"]), t - 1):
            x, previous = df.iloc[k], df.iloc[k - 1]
            leg1 = x.high > previous.high if side == "long" else x.low < previous.low
            leg2 = any((df.iloc[m].low < x.low if side == "long" else df.iloc[m].high > x.high)
                       for m in range(k + 1, t + 1))
            found = found or (leg1 and leg2)
        if not found:
            return False
    body, span = abs(b.close - b.open), max(b.high - b.low, 1e-8)
    lower, upper = min(b.open, b.close) - b.low, b.high - max(b.open, b.close)
    if side == "long":
        return bool((b.close - b.low) / span >= 0.60 and
                    (lower >= 1.2 * body or (b.close > b.open and body >= 0.50 * span)))
    return bool((b.high - b.close) / span >= 0.60 and
                (upper >= 1.2 * body or (b.close < b.open and body >= 0.50 * span)))


class MarketData:
    """Synthetic demo or public futures tickers with user-supplied futures CSVs.

    The pinned LBank fetch_ohlcv implementation also routes to the SPOT API.
    It must never be used for futures signals. CSV mode requires actual futures
    candles; demo mode is explicitly synthetic and makes no network requests.
    """
    def __init__(self):
        self.mode = os.getenv("PAPER_DATA_MODE", "demo")
        if self.mode not in ("demo", "csv-lbank"):
            raise ValueError("PAPER_DATA_MODE must be demo or csv-lbank")
        self.ohlcv_dir = Path(os.getenv("OHLCV_DIR", "data/ohlcv"))
        self.exchange = ccxt.lbank({"apiKey": os.getenv("LBANK_API_KEY", ""),
            "secret": os.getenv("LBANK_SECRET_KEY", ""), "enableRateLimit": True,
            "timeout": 10000, "options": {"defaultType": "swap"}})
        self.lock = threading.RLock()
        self.loaded = False
        self.cache: dict[str, tuple[float, float]] = {}

    def market(self, symbol: str) -> dict:
        with self.lock:
            if self.mode == "demo":
                self.demo_base(symbol)
                return {"symbol": symbol, "swap": True, "linear": True, "settle": "USDT",
                        "contractSize": 1.0, "active": True,
                        "limits": {"amount": {"min": 0.000001}, "cost": {"min": 0.0}}}
            if not self.loaded:
                self.exchange.load_markets()
                self.loaded = True
            market = self.exchange.market(symbol)
            if not market.get("swap") or not market.get("linear") or market.get("settle") != "USDT" or market.get("active") is False:
                raise ValueError(f"Not an active USDT linear swap: {symbol}")
            return market

    def price(self, symbol: str, cached: bool = False) -> float:
        with self.lock:
            self.market(symbol)
            stamp = time.monotonic()
            if cached and symbol in self.cache and stamp - self.cache[symbol][0] < 5:
                return self.cache[symbol][1]
            value = (self.demo_price(symbol, time.time()) if self.mode == "demo" else
                     float(self.exchange.fetch_ticker(symbol)["last"]))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid ticker: {symbol}")
            self.cache[symbol] = (time.monotonic(), value)
            return value

    def candles(self, symbol: str, timeframe: str, limit: int) -> list:
        with self.lock:
            self.market(symbol)
            if self.mode == "demo":
                seconds = TIMEFRAMES[timeframe]
                last = int(time.time()) // seconds * seconds
                result = []
                for stamp in range(last - (limit - 1) * seconds, last + 1, seconds):
                    samples = [self.demo_price(symbol, stamp + seconds * k / 24) for k in range(25)]
                    result.append([stamp * 1000, samples[0], max(samples), min(samples), samples[-1], 100.0])
                return result
            name = symbol.replace("/", "_").replace(":", "_") + "_" + timeframe + ".csv"
            source = self.ohlcv_dir / name
            if not source.is_file():
                raise ValueError(f"Verified futures candles required: {source}. CCXT LBank OHLCV uses the spot endpoint.")
            df = pd.read_csv(source)
            if list(df.columns) != ["timestamp", "open", "high", "low", "close", "volume"]:
                raise ValueError("CSV header must be timestamp,open,high,low,close,volume")
            # Atomic replacement of the CSV by its producer avoids partial reads.
            return df.tail(limit).to_numpy().tolist()

    def precision(self, symbol: str, quantity: float) -> float:
        with self.lock:
            self.market(symbol)
            if self.mode == "demo":
                return math.floor(quantity * 1_000_000) / 1_000_000
            return float(self.exchange.amount_to_precision(symbol, quantity))

    @staticmethod
    def demo_base(symbol: str) -> float:
        bases = {"BTC": 60000, "ETH": 3000, "BNB": 600, "SOL": 150, "XRP": 0.5, "ADA": 0.4}
        if symbol not in [key + "/USDT:USDT" for key in bases]:
            raise ValueError(f"No synthetic demo market for {symbol}")
        return float(bases[symbol.split("/")[0]])

    @classmethod
    def demo_price(cls, symbol: str, stamp: float) -> float:
        return cls.demo_base(symbol) * (1 + 0.05 * math.sin(stamp / 86400)
            + 0.01 * math.sin(stamp / 3600) + 0.005 * math.sin(stamp / 600))

    def tradable(self, symbol: str, qty: float, price: float) -> bool:
        market = self.market(symbol)
        limits = market.get("limits", {})
        amount = limits.get("amount", {})
        cost = limits.get("cost", {})
        notional = qty * float(market.get("contractSize") or 1) * price
        return (qty > 0 and qty >= (amount.get("min") or 0) and
                qty <= (amount.get("max") or math.inf) and
                notional >= (cost.get("min") or 0) and
                notional <= (cost.get("max") or math.inf))


def size_position(data: MarketData, symbol: str, side: str, bar: pd.Series,
                  equity: float, c: dict, timeframe: str) -> dict | None:
    r, a = c["risk_and_exit"], c["al_brooks_filters"]
    sign = 1 if side == "long" else -1
    entry = (bar.high + a["stop_entry_atr_buffer"] * bar.atr if side == "long" else
             bar.low - a["stop_entry_atr_buffer"] * bar.atr) if a["require_signal_bar_breakout"] else bar.close
    stop = (min(bar.low, bar.kijun) - r["sl_atr_buffer"] * bar.atr if side == "long" else
            max(bar.high, bar.kijun) + r["sl_atr_buffer"] * bar.atr)
    distance = sign * (entry - stop)
    if equity <= 0 or stop <= 0 or entry <= 0 or distance <= 0:
        return None
    cs = float(data.market(symbol).get("contractSize") or 1)
    risk = equity * r["risk_per_trade_pct"]
    cap = equity * r["max_margin_per_position_pct"] * r["default_isolated_leverage"]
    # CCXT contract quantity is contracts, not necessarily base units.
    qty = data.precision(symbol, min(risk / (distance + entry * r["lbank_round_trip_fee"]), cap / entry) / cs)
    if not data.tradable(symbol, qty, entry):
        return None
    return dict(symbol=symbol, side=side, entry_price=float(entry), qty=qty,
        initial_sl=float(stop), active_sl=float(stop), tp1_price=float(entry + sign * r["tp1_rr_ratio"] * distance),
        state=PENDING, trigger_price=float(entry), cancel_price=float(stop),
        expiry_ts=int(bar.timestamp / 1000 + TIMEFRAMES[timeframe] * (1 + a["pending_order_expiry_bars"])),
        dry_run=1, contract_size=cs, fee_rate=r["lbank_round_trip_fee"],
        tp1_close_pct=r["tp1_close_pct"], tp1_rr=r["tp1_rr_ratio"], risk_budget=risk,
        max_notional=cap, timeframe=timeframe, signal_ts=int(bar.timestamp))


class Engine:
    def __init__(self, config: ConfigStore, db: Database, data: MarketData,
                 paper_equity: float | None = None):
        self.config, self.db, self.data = config, db, data
        self.paper_seed = float(paper_equity if paper_equity is not None else os.getenv("PAPER_EQUITY", "10000"))
        if not math.isfinite(self.paper_seed) or self.paper_seed <= 0:
            raise ValueError("PAPER_EQUITY must be positive and finite")
        with file_lock(db.trade_lock):
            values = db.runtime_all()
            if "paper_initial_equity" not in values:
                db.runtime_set("paper_initial_equity", self.paper_seed)
            self.paper_seed = float(db.runtime_all()["paper_initial_equity"])

    def assert_paper(self, p: dict | None = None):
        if p is not None and not p["dry_run"]:
            raise LiveUnavailable(LIVE_LIMITATION)

    def paper_equity(self) -> float:
        with self.db.connect() as db:
            realized = float(db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM trade_history WHERE dry_run=1").fetchone()[0])
        unrealized = 0.0
        for p in self.db.positions():
            self.assert_paper(p)
            if p["state"] != PENDING:
                unrealized += net_pnl(p, self.data.price(p["symbol"], cached=True), p["qty"])
        return max(0.0, self.paper_seed + realized + unrealized)

    def _insert(self, p: dict):
        keys = list(p)
        with self.db.connect() as db:
            db.execute("INSERT INTO positions (" + ",".join(keys) + ") VALUES (" +
                       ",".join("?" for _ in keys) + ")", [p[k] for k in keys])
            # Persist the signal claim with its position, even if the scanner
            # process dies before recording the rest of that candle's scan.
            db.execute("INSERT INTO scanned_candles VALUES(?,?,?) ON CONFLICT(symbol,timeframe) "
                       "DO UPDATE SET candle_ts=MAX(candle_ts,excluded.candle_ts)",
                       (p["symbol"], p["timeframe"], p["signal_ts"]))

    def _activate(self, p: dict, price: float) -> bool:
        self.assert_paper(p)
        direction = 1 if p["side"] == "long" else -1
        distance = direction * (price - p["initial_sl"])
        if distance <= 0:
            with self.db.connect() as db:
                db.execute("DELETE FROM positions WHERE symbol=? AND state=?", (p["symbol"], PENDING))
            return False
        # Re-size at the simulated fill after a gap, so risk isn't based on an old trigger.
        cap = min(p["qty"], p["risk_budget"] / (distance + price * p["fee_rate"]) / p["contract_size"],
                  p["max_notional"] / price / p["contract_size"])
        qty = self.data.precision(p["symbol"], cap)
        if not self.data.tradable(p["symbol"], qty, price):
            with self.db.connect() as db:
                db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
            return False
        with self.db.connect() as db:
            db.execute("UPDATE positions SET state=?,entry_price=?,qty=?,tp1_price=? WHERE symbol=? AND state=?",
                (INITIAL, price, qty, price + direction * p["tp1_rr"] * distance, p["symbol"], PENDING))
        return True

    def _close(self, p: dict, price: float, qty: float, reason: str, now: float,
               transition: bool = False) -> dict:
        self.assert_paper(p)
        if not (math.isfinite(price) and price > 0 and 0 < qty <= p["qty"]):
            raise ValueError("Invalid close price/quantity")
        pnl = net_pnl(p, price, qty)
        remaining = max(0.0, p["qty"] - qty)
        with self.db.connect() as db:
            db.execute("INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason,dry_run) "
                "VALUES(?,?,?,?,?,?,?,?,?)", (p["symbol"], p["side"], pnl, int(now), qty,
                 p["entry_price"], price, reason, p["dry_run"]))
            if remaining < 1e-12:
                db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
            else:
                db.execute("UPDATE positions SET qty=?,active_sl=?,state=? WHERE symbol=?",
                    (remaining, p["entry_price"] if transition else p["active_sl"],
                     TRAILING if transition else p["state"], p["symbol"]))
        return {"symbol": p["symbol"], "result": "closed", "qty": qty, "pnl_usd": pnl, "dry_run": True}

    def close_symbol(self, symbol: str, now: float | None = None) -> dict:
        with file_lock(self.db.trade_lock):
            p = self.db.position(symbol)
            if not p:
                raise KeyError(symbol)
            self.assert_paper(p)
            if p["state"] == PENDING:
                with self.db.connect() as db:
                    db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                return {"symbol": symbol, "result": "cancelled", "dry_run": True}
            return self._close(p, self.data.price(symbol), p["qty"], "manual", now or time.time())

    def close_all(self, disable: bool = True) -> dict:
        results, errors = [], []
        with file_lock(self.db.trade_lock):
            if disable:
                self.config.stop_entries()
            for p in self.db.positions():
                try:
                    self.assert_paper(p)
                    if p["state"] == PENDING:
                        with self.db.connect() as db:
                            db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
                        results.append({"symbol": p["symbol"], "result": "cancelled"})
                    else:
                        results.append(self._close(p, self.data.price(p["symbol"]), p["qty"], "panic", time.time()))
                except Exception as exc:
                    errors.append({"symbol": p["symbol"], "error": str(exc)})
            return {"results": results, "errors": errors, "auto_trade_disabled": disable,
                    "remaining_positions": len(self.db.positions())}

    def watchdog(self, now: float | None = None):
        now = now if now is not None else time.time()
        # Never stop risk management solely because config reload failed.
        try:
            auto = self.config.read()["bot_control"]["auto_trade_enabled"]
        except Exception:
            LOG.exception("Invalid configuration: blocking pending entries")
            auto = False
        for old in self.db.positions():
            try:
                with file_lock(self.db.trade_lock):
                    p = self.db.position(old["symbol"])
                    if not p:
                        continue
                    self.assert_paper(p)
                    # Re-read auto under the execution lock after a possible panic.
                    try:
                        auto_now = auto and self.config.read()["bot_control"]["auto_trade_enabled"]
                    except Exception:
                        auto_now = False
                    if p["state"] == PENDING and (not auto_now or now >= p["expiry_ts"]):
                        with self.db.connect() as db:
                            db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
                        continue
                    price = self.data.price(p["symbol"])
                    sign = 1 if p["side"] == "long" else -1
                    if p["state"] == PENDING:
                        if sign * (price - p["cancel_price"]) <= 0:
                            with self.db.connect() as db:
                                db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
                        elif sign * (price - p["trigger_price"]) >= 0:
                            equity = self.paper_equity()
                            pnl, _ = self.db.history_summary(now)
                            cfg = self.config.read()
                            if equity <= 0 or pnl <= -equity * cfg["risk_and_exit"]["daily_max_loss_pct"]:
                                with self.db.connect() as db:
                                    db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
                            else:
                                p["risk_budget"] = min(p["risk_budget"], equity * cfg["risk_and_exit"]["risk_per_trade_pct"])
                                p["max_notional"] = min(p["max_notional"], equity * cfg["risk_and_exit"]["max_margin_per_position_pct"] * cfg["risk_and_exit"]["default_isolated_leverage"])
                                self._activate(p, price)
                        continue
                    if sign * (price - p["active_sl"]) <= 0:
                        self._close(p, price, p["qty"], "stop", now)
                    elif p["state"] == INITIAL and sign * (price - p["tp1_price"]) >= 0:
                        qty = self.data.precision(p["symbol"], p["qty"] * p["tp1_close_pct"])
                        remainder = self.data.precision(p["symbol"], p["qty"] - qty)
                        if (not self.data.tradable(p["symbol"], qty, price) or
                                not self.data.tradable(p["symbol"], remainder, price)):
                            self._close(p, price, p["qty"], "tp1_full_small_position", now)
                        else:
                            self._close(p, price, qty, "tp1", now, transition=True)
            except Exception as exc:
                LOG.exception("Watchdog failed for %s", old["symbol"])
                self.db.runtime_set("last_error", str(exc))
        self.db.runtime_set("watchdog_at", now)

    def scan(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        failed = False
        c = self.config.read()
        s = c["strategy_mode"]
        ltf = s["ltf_entry_timeframe"] if s["mode"] == "MTF" else s["single_timeframe"]
        htf = s["htf_trend_timeframe"] if s["mode"] == "MTF" else ltf
        limit = c["ichimoku_params"]["candle_fetch_limit"]
        frames: dict[tuple[str, str], pd.DataFrame] = {}

        def frame(symbol: str, tf: str) -> pd.DataFrame:
            key = (symbol, tf)
            if key not in frames:
                result = indicators(self.data.candles(symbol, tf, limit), c, tf, now)
                expected = (int(now) // TIMEFRAMES[tf] - 1) * TIMEFRAMES[tf] * 1000
                if result.empty or int(result.iloc[-1].timestamp) != expected:
                    raise ValueError(f"Stale closed candle for {symbol} {tf}")
                frames[key] = result
            return frames[key]

        # Existing trailing positions retain their entry timeframe on hot reload.
        for old in self.db.positions():
            if old["state"] != TRAILING:
                continue
            try:
                b = frame(old["symbol"], old["timeframe"]).iloc[-1]
                if not np.isfinite(b[["kijun", "atr"]]).all():
                    raise ValueError("Uninitialized trailing indicators")
                with file_lock(self.db.trade_lock):
                    p = self.db.position(old["symbol"])
                    if not p or p["state"] != TRAILING:
                        continue
                    self.assert_paper(p)
                    sign = 1 if p["side"] == "long" else -1
                    if sign * (b.close - b.kijun) < 0:
                        self._close(p, self.data.price(p["symbol"]), p["qty"], "kijun_break", now)
                    else:
                        sl = b.kijun - sign * 0.2 * b.atr
                        sl = max(p["active_sl"], sl) if sign == 1 else min(p["active_sl"], sl)
                        with self.db.connect() as db:
                            db.execute("UPDATE positions SET active_sl=? WHERE symbol=?", (float(sl), p["symbol"]))
            except Exception as exc:
                failed = True
                LOG.exception("Trailing scan failed for %s", old["symbol"])
                self.db.runtime_set("last_error", str(exc))
        if not c["bot_control"]["auto_trade_enabled"]:
            self.db.runtime_set("scanner_at", now)
            return not failed
        candidates, scanned = [], []
        for symbol in c["symbols"]:
            try:
                low = frame(symbol, ltf)
                stamp = int(low.iloc[-1].timestamp)
                with self.db.connect() as db:
                    previous = db.execute("SELECT candle_ts FROM scanned_candles WHERE symbol=? AND timeframe=?", (symbol, ltf)).fetchone()
                if previous and stamp <= previous[0]:
                    continue
                high = low if htf == ltf else frame(symbol, htf)
                side = regime(high, c)
                scanned.append((symbol, ltf, stamp))
                if side and entry_signal(low, side, c):
                    score = abs(low.iloc[-1].rsi - (55 if side == "long" else 45))
                    candidates.append((float(score), symbol, side, low.iloc[-1]))
            except Exception as exc:
                failed = True
                LOG.exception("Signal scan failed for %s", symbol)
                self.db.runtime_set("last_error", str(exc))
        # Serialize all paper position changes across bot and dashboard processes.
        with file_lock(self.db.trade_lock):
            if self.config.read() != c:
                return False
            equity = self.paper_equity()
            daily, _ = self.db.history_summary(now)
            blocked = equity <= 0 or daily <= -equity * c["risk_and_exit"]["daily_max_loss_pct"]
            available = max(0, c["risk_and_exit"]["max_open_positions"] - len(self.db.positions()))
            for _, symbol, side, bar in sorted(candidates, key=lambda item: (item[0], item[1])):
                if blocked or available <= 0:
                    break
                if self.db.position(symbol):
                    continue
                with self.db.connect() as db:
                    prior = db.execute("SELECT candle_ts FROM scanned_candles WHERE symbol=? AND timeframe=?", (symbol, ltf)).fetchone()
                if prior and prior[0] >= int(bar.timestamp):
                    continue
                p = size_position(self.data, symbol, side, bar, equity, c, ltf)
                if p is None:
                    continue
                price = None
                if not c["al_brooks_filters"]["require_signal_bar_breakout"]:
                    # A failed price fetch must not leave a fabricated open fill.
                    price = self.data.price(symbol)
                self._insert(p)
                if price is not None:
                    self._activate(p, price)
                if self.db.position(symbol):
                    available -= 1
            with self.db.connect() as db:
                db.executemany("INSERT INTO scanned_candles VALUES(?,?,?) ON CONFLICT(symbol,timeframe) "
                    "DO UPDATE SET candle_ts=MAX(candle_ts,excluded.candle_ts)", scanned)
        self.db.runtime_set("scanner_at", now)
        return not failed


def net_pnl(p: dict, price: float, quantity: float) -> float:
    direction = 1 if p["side"] == "long" else -1
    units = quantity * p["contract_size"]
    # Split round-trip rate between entry and exit notionals, including partial exits.
    fee = units * (p["entry_price"] + price) * p["fee_rate"] / 2
    return direction * (price - p["entry_price"]) * units - fee


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config, db = ConfigStore(), Database()
    config.read()
    engine = Engine(config, db, MarketData())
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    def scan_loop():
        last_boundary = None
        while not stop.is_set():
            try:
                c = config.read()
                s = c["strategy_mode"]
                tf = s["ltf_entry_timeframe"] if s["mode"] == "MTF" else s["single_timeframe"]
                # Include retained position timeframes when config switches modes.
                periods = [TIMEFRAMES[tf]] + [TIMEFRAMES[p["timeframe"]] for p in db.positions() if p["state"] == TRAILING]
                interval = min(periods)
                now = time.time()
                boundary = int(now) // interval * interval
                key = (interval, boundary, tf)
                if now >= boundary + 3 and key != last_boundary:
                    if engine.scan(now):
                        last_boundary = key
                        db.runtime_set("scanner_error", None)
                    else:
                        db.runtime_set("scanner_error", "Some symbols failed; retrying")
                        stop.wait(10)
            except Exception as exc:
                LOG.exception("Scanner failed; will retry")
                db.runtime_set("scanner_error", str(exc))
                stop.wait(10)
            stop.wait(1)

    thread = threading.Thread(target=scan_loop, name="closed-candle-scanner", daemon=True)
    thread.start()
    LOG.info("Started PAPER engine. %s", LIVE_LIMITATION)
    while not stop.is_set():
        interval = 15
        try:
            engine.watchdog()
            interval = config.read()["bot_control"]["check_interval_seconds"]
        except Exception as exc:
            LOG.exception("Watchdog cycle failed")
            db.runtime_set("last_error", str(exc))
        stop.wait(interval)
    thread.join(timeout=12)


if __name__ == "__main__":
    run()
