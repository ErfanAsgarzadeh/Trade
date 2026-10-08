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
import sys
import tempfile
import threading
import time
from typing import Any

import ccxt
import numpy as np
import pandas as pd
import strategy_archetypes as archetypes

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
    "portfolio_risk": {"rank_by": str, "enforce_shared_margin": bool, "shared_c3_account": bool, "margin_allocation_mode": str},
    "ichimoku_params": {"tenkan": int, "kijun": int, "senkou_b": int, "displacement": int, "candle_fetch_limit": int},
    "filters_and_triggers": {"rsi_period": int, "long_rsi_min": float, "long_rsi_max": float,
        "short_rsi_min": float, "short_rsi_max": float, "atr_period": int,
        "kijun_touch_atr_tolerance": float, "max_kijun_extension_atr": float},
    "al_brooks_filters": {"enable_barb_wire_filter": bool, "barb_wire_lookback": int,
        "barb_wire_min_overlap_ratio": float, "barb_wire_doji_body_ratio": float,
        "require_signal_bar_breakout": bool, "stop_entry_atr_buffer": float,
        "pending_order_expiry_bars": int, "require_h2_l2_pullback": bool, "h2_l2_lookback_bars": int},
    "risk_and_exit": {"risk_per_trade_pct": float, "max_open_positions": int,
        "engaged_capital_pct": float, "leverage_mode": str,
        "max_margin_per_position_pct": float, "default_isolated_leverage": int,
        "sl_atr_buffer": float, "tp1_rr_ratio": float, "tp1_close_pct": float,
        "daily_max_loss_pct": float, "lbank_round_trip_fee": float,
        "min_stop_distance_pct": float, "min_stop_policy": str,
        "exit_scheme": str, "breakeven_policy": str, "breakeven_trigger_rr": float,
        "trail_atr_buffer": float, "trail_timeframe": str, "hard_tp_rr": float},
    "structural_filters": {"enable_htf_slope_filter": bool, "adx_period": int,
                           "min_htf_adx": float},
    "strategy_settings": {"ichimoku_preset": str, "donchian_entry_period": int,
        "initial_stop_mode": str, "exit_tp_mode": str, "hybrid_trail_mode": str,
        "hard_tp_rr": float, "breakeven_trigger_rr": float,
        "pyramid_enabled": bool, "initial_stop_anchor": str, "trail_atr_buffer": float,
        "profit_floor_enabled": bool, "profit_floor_trigger_r": float, "profit_floor_lock_r": float,
        "safe_pyramid_enabled": bool, "pyramid_risk_fraction": float,
        "stop_width_filter_enabled": bool, "stop_width_skip_pct": float,
        "stop_width_mid_pct": float, "stop_width_mid_risk_fraction": float,
        "initial_stop_atr_mult": float,
        "btc_regime_filter_enabled": bool, "btc_regime_symbol": str,
        "funding_short_filter_enabled": bool, "funding_short_prints": int, "funding_short_threshold": float,
        "atr_regime_filter_enabled": bool, "atr_regime_window": int, "atr_regime_min_ratio": float},
    "archetype_strategy": {"family": str, "entry_variant": str, "donchian_lookback": int,
        "stop_source": str, "trail_source": str, "require_h2_l2": bool,
        "trail_close_only": bool, "pending_policy": str}}
# Verified ablation fix #4B (see high_cagr/output/ablation_fixes.json). Old configs keep legacy behaviour.
PROFIT_FLOOR_DEFAULTS = {"profit_floor_enabled": False, "profit_floor_trigger_r": 2.0,
    "profit_floor_lock_r": 0.25, "safe_pyramid_enabled": False, "pyramid_risk_fraction": 0.5,
    # Candidate "V2" (high_cagr/output/vol_throttle_results.json): in-sample evidence only, so it ships OFF.
    "stop_width_filter_enabled": False, "stop_width_skip_pct": 0.056,
    "stop_width_mid_pct": 0.045, "stop_width_mid_risk_fraction": 0.5,
    # 2.5 passed in-sample and on untouched holdout symbols, but only together with V2 + the BTC gate.
    "initial_stop_atr_mult": 2.0,
    # BTC regime gate (high_cagr/btc_regime_experiment.py): alts do not enter while BTC's closed 4h bar is inside its Kumo.
    "btc_regime_filter_enabled": False, "btc_regime_symbol": "BTC/USDT:USDT",
    # Funding crowding filter F4 (high_cagr/output/r3/hold2_results.json): no new short while the mean of the last
    # 9 funding prints (3 days) before the entry bar is below 0, i.e. shorts are already paying longs. Ships OFF.
    "funding_short_filter_enabled": False, "funding_short_prints": 9, "funding_short_threshold": 0.0,
    # ATR regime filter 2A (high_cagr/output/ideas/idea2_atr_regime.json): no entry or pyramid add while the signal
    # bar's ATR is below min_ratio x the median ATR of the `window` closed bars before it. Older configs: OFF.
    "atr_regime_filter_enabled": False, "atr_regime_window": 60, "atr_regime_min_ratio": 1.0}
ASSUMED_SLIPPAGE_BPS = 2.0  # per fill, what every benchmark assumed
LEGACY_RISK_DEFAULTS = {"min_stop_distance_pct": 0.0, "min_stop_policy": "NONE",
    "exit_scheme": "LEGACY", "breakeven_policy": "ENTRY", "breakeven_trigger_rr": 2.0,
    "trail_atr_buffer": 0.2, "trail_timeframe": "ENTRY", "hard_tp_rr": 0.0,
    "engaged_capital_pct": 1.0, "leverage_mode": "FIXED_LEVERAGE"}
POSITION_EXTENSIONS = {
    "root_entry_price": "REAL NOT NULL DEFAULT 0",
    "root_r_distance": "REAL NOT NULL DEFAULT 0",
    "pyramid_added": "INTEGER NOT NULL DEFAULT 0",
    "pyramid_eligible_ts": "REAL NOT NULL DEFAULT 0",
    "isolated_leverage": "INTEGER NOT NULL DEFAULT 0",
    "slot_margin_usd": "REAL NOT NULL DEFAULT 0",
    "sizing_slippage_pct": "REAL NOT NULL DEFAULT 0",
    "stop_atr_distance": "REAL NOT NULL DEFAULT 0",
    "exit_scheme": "TEXT NOT NULL DEFAULT 'LEGACY'",
    "be_policy": "TEXT NOT NULL DEFAULT 'ENTRY'",
    "be_confirmed": "INTEGER NOT NULL DEFAULT 1",
    "trail_atr": "REAL NOT NULL DEFAULT 0.2",
    "trail_timeframe": "TEXT NOT NULL DEFAULT ''",
    "hard_tp_price": "REAL NOT NULL DEFAULT 0",
    "hard_tp_rr": "REAL NOT NULL DEFAULT 0",
    "initial_r_distance": "REAL NOT NULL DEFAULT 0",
    "be_trigger_rr": "REAL NOT NULL DEFAULT 2",
    "trail_last_candle_ts": "INTEGER NOT NULL DEFAULT 0",
    "archetype_family": "TEXT NOT NULL DEFAULT 'LEGACY'",
    "trail_source": "TEXT NOT NULL DEFAULT 'KIJUN'",
    "trail_close_only": "INTEGER NOT NULL DEFAULT 0",
    "risk_mult": "REAL NOT NULL DEFAULT 1",
    "pending_policy": "TEXT NOT NULL DEFAULT 'ONE_BAR'",
    "strategy_config": "TEXT NOT NULL DEFAULT '{}'"}


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
    if not isinstance(c, dict):
        raise ConfigError("Configuration must be a JSON object")
    c = copy.deepcopy(c)
    c.setdefault("portfolio_risk", {"rank_by": "LEGACY_RSI", "enforce_shared_margin": False})
    if isinstance(c.get("portfolio_risk"), dict):
        c["portfolio_risk"].setdefault("shared_c3_account", False)
        c["portfolio_risk"].setdefault("margin_allocation_mode", "PER_SLOT")
        if c["portfolio_risk"]["margin_allocation_mode"] not in ("PER_SLOT", "SHARED_POOL"):
            raise ConfigError("margin_allocation_mode must be PER_SLOT or SHARED_POOL")
        if c["portfolio_risk"]["margin_allocation_mode"] == "SHARED_POOL":
            c["portfolio_risk"]["enforce_shared_margin"] = True
        if c["portfolio_risk"]["shared_c3_account"]:
            c["portfolio_risk"]["enforce_shared_margin"] = True
    c.setdefault("archetype_strategy", copy.deepcopy(archetypes.DEFAULTS))
    c.setdefault("structural_filters", {"enable_htf_slope_filter": False,
                                       "adx_period": 14, "min_htf_adx": 0.0})
    if isinstance(c.get("risk_and_exit"), dict):
        for key, value in LEGACY_RISK_DEFAULTS.items():
            c["risk_and_exit"].setdefault(key, value)
    if "strategy_settings" in c and isinstance(c["strategy_settings"], dict):
        c["strategy_settings"].setdefault("hybrid_trail_mode", "CLOSE_TRAIL_KIJUN")
        c["strategy_settings"].setdefault("pyramid_enabled", False)
        c["strategy_settings"].setdefault("initial_stop_anchor", "ENTRY")
        c["strategy_settings"].setdefault("trail_atr_buffer", 0.0)
        for key, value in PROFIT_FLOOR_DEFAULTS.items():
            c["strategy_settings"].setdefault(key, value)
    if set(c) not in (set(SCHEMA), set(SCHEMA) - {"strategy_settings"}):
        raise ConfigError("Configuration must use the supplied top-level schema")
    for section, template in SCHEMA.items():
        if section == "strategy_settings" and section not in c:
            continue
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
    if "strategy_settings" in c:
        settings = c["strategy_settings"]
        trails = ("STOP_TRAIL_DONCHIAN10", "CLOSE_TRAIL_KIJUN")
        if (settings["ichimoku_preset"] not in archetypes.ICHIMOKU_PRESETS
                or settings["donchian_entry_period"] not in (10, 20)
                or settings["initial_stop_mode"] not in ("ATR2", "KIJUN")
                or settings["initial_stop_anchor"] not in ("ENTRY", "SIGNAL")
                or settings["exit_tp_mode"] not in (*trails, "HYBRID_TRAIL_AND_HARD_TP")
                or settings["hybrid_trail_mode"] not in trails
                or not 0 <= settings["hard_tp_rr"] <= 100
                or not 0 <= settings["breakeven_trigger_rr"] <= 20
                or not 0 <= settings["trail_atr_buffer"] <= 5):
            raise ConfigError("Invalid strategy_settings")
        if not (0 < settings["profit_floor_trigger_r"] <= 20
                and 0 <= settings["profit_floor_lock_r"] < settings["profit_floor_trigger_r"]
                and 0.05 <= settings["pyramid_risk_fraction"] <= 1):
            raise ConfigError("Invalid profit floor / pyramid risk settings")
        if not (0.012 <= settings["stop_width_mid_pct"] < settings["stop_width_skip_pct"] <= 0.5
                and 0.05 <= settings["stop_width_mid_risk_fraction"] <= 1):
            raise ConfigError("Invalid stop-width filter settings")
        if not 1.0 <= settings["initial_stop_atr_mult"] <= 5.0:
            raise ConfigError("initial_stop_atr_mult must be between 1 and 5")
        if not (1 <= settings["funding_short_prints"] <= 90 and -0.01 <= settings["funding_short_threshold"] <= 0.01):
            raise ConfigError("Invalid funding short filter settings")
        if not (10 <= settings["atr_regime_window"] <= 500 and 0.1 <= settings["atr_regime_min_ratio"] <= 5.0):
            raise ConfigError("Invalid ATR regime filter settings")
        if settings["btc_regime_filter_enabled"] and settings["btc_regime_symbol"] not in c["symbols"]:
            raise ConfigError("btc_regime_symbol must be one of the traded symbols")
        if settings["exit_tp_mode"] == "HYBRID_TRAIL_AND_HARD_TP" and settings["hard_tp_rr"] <= 0:
            raise ConfigError("Hybrid exit requires a positive hard_tp_rr")
        if settings["pyramid_enabled"] and (settings["exit_tp_mode"] != "STOP_TRAIL_DONCHIAN10"
                or settings["hard_tp_rr"] != 0 or settings["breakeven_trigger_rr"] != 0
                or c["risk_and_exit"]["leverage_mode"] != "FIXED_LEVERAGE"):
            raise ConfigError("Pyramiding requires fixed leverage and an unlimited Donchian stop trail")
        modes = c["strategy_mode"]
        if modes["mode"] != "SINGLE" or modes["single_timeframe"] != "4h":
            raise ConfigError("Donchian strategy_settings require SINGLE 4h")
        if c["risk_and_exit"]["min_stop_policy"] != "REJECT" or c["risk_and_exit"]["min_stop_distance_pct"] < 0.012:
            raise ConfigError("Donchian requires REJECT and a minimum 1.2% stop")
        archetypes.apply_strategy_settings(c)
        c["portfolio_risk"]["enforce_shared_margin"] = True
    if c["portfolio_risk"]["rank_by"] not in ("LEGACY_RSI", "BREAKOUT_DISTANCE"):
        raise ConfigError("Invalid portfolio ranking")
    if c["portfolio_risk"]["rank_by"] == "BREAKOUT_DISTANCE" and c["archetype_strategy"]["family"] != "DONCHIAN":
        raise ConfigError("Breakout ranking requires DONCHIAN")
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
            and 0 < r["engaged_capital_pct"] <= 1
            and r["leverage_mode"] in ("DYNAMIC_MARGIN", "FIXED_LEVERAGE")
            and 0 < r["max_margin_per_position_pct"] <= 1
            and 1 <= r["default_isolated_leverage"] <= 125
            and 0 < r["daily_max_loss_pct"] <= 1
            and 0 <= r["tp1_close_pct"] < 1 and 0 < r["tp1_rr_ratio"] <= 100
            and 0 <= r["sl_atr_buffer"] <= 20 and 0 <= r["lbank_round_trip_fee"] < 0.1):
        raise ConfigError("Invalid risk/exit configuration")
    sf = c["structural_filters"]
    if not (2 <= sf["adx_period"] <= 50 and 0 <= sf["min_htf_adx"] <= 100):
        raise ConfigError("Invalid ADX configuration")
    if not (0 <= r["min_stop_distance_pct"] <= 0.10 and r["min_stop_policy"] in ("NONE", "WIDEN", "REJECT")
            and r["exit_scheme"] in ("LEGACY", "DELAYED_PARTIAL", "PURE_RUNNER", "PURE_KIJUN", "HARD_TARGET")
            and r["breakeven_policy"] in ("ENTRY", "QUARTER_R", "CLOSE_CONFIRM", "MILESTONE", "NONE")
            and 0 <= r["breakeven_trigger_rr"] <= 20 and 0 <= r["trail_atr_buffer"] <= 5
            and r["trail_timeframe"] in ("ENTRY", "HTF") and 0 <= r["hard_tp_rr"] <= 100):
        raise ConfigError("Invalid structural risk configuration")
    expected_policies = {"LEGACY": {"ENTRY"}, "DELAYED_PARTIAL": {"QUARTER_R", "CLOSE_CONFIRM"},
                         "PURE_RUNNER": {"MILESTONE"}, "PURE_KIJUN": {"NONE"}, "HARD_TARGET": {"NONE"}}
    if r["breakeven_policy"] not in expected_policies[r["exit_scheme"]]:
        raise ConfigError("Breakeven policy does not match exit scheme")
    if r["exit_scheme"] in ("LEGACY", "DELAYED_PARTIAL") and r["tp1_close_pct"] <= 0:
        raise ConfigError("Partial exit scheme requires a positive tp1_close_pct")
    if r["exit_scheme"] in ("PURE_RUNNER", "PURE_KIJUN", "HARD_TARGET") and r["tp1_close_pct"] != 0:
        raise ConfigError("Pure runner schemes must use tp1_close_pct=0")
    if i["candle_fetch_limit"] < 2 * sf["adx_period"] + 2:
        raise ConfigError("Not enough candles to initialize ADX")
    spec = c["archetype_strategy"]
    if spec["family"] not in ("LEGACY", "ICHI_BREAKOUT", "ICHI_PULLBACK", "EMA_PULLBACK", "DONCHIAN"):
        raise ConfigError("Unsupported archetype family")
    if (spec["entry_variant"] not in ("KUMO_CROSS", "TENKAN_RECLAIM", "MARKET", "SIGNAL_BREAKOUT")
            or spec["donchian_lookback"] not in (10, 20)
            or spec["stop_source"] not in ("KIJUN", "SIGNAL_BAR", "ATR2")
            or spec["trail_source"] not in ("KIJUN", "EMA20", "DONCHIAN10")
            or spec["pending_policy"] not in ("ONE_BAR", "GTC_REGIME")):
        raise ConfigError("Invalid archetype settings")
    if r["exit_scheme"] == "HARD_TARGET" and r["hard_tp_rr"] <= 0:
        raise ConfigError("Hard target requires a positive R target")
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
        with file_lock(self.trade_lock), self.connect() as db:
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
            CREATE TABLE IF NOT EXISTS scale_in_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
              root_signal_ts INTEGER NOT NULL, added_at REAL NOT NULL,
              entry_price REAL NOT NULL, qty REAL NOT NULL, shared_stop REAL NOT NULL,
              modeled_risk_usd REAL NOT NULL, root_entry_price REAL NOT NULL,
              root_r_distance REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS fill_quality (
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, symbol TEXT NOT NULL,
              kind TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', side TEXT NOT NULL,
              ref_price REAL NOT NULL, mid REAL NOT NULL, vwap REAL NOT NULL,
              qty REAL NOT NULL, notional_usd REAL NOT NULL,
              slip_ref_bps REAL NOT NULL, slip_mid_bps REAL NOT NULL,
              spread_bps REAL NOT NULL, filled_fraction REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS fill_quality_ts ON fill_quality(ts);
            """)
            existing = {row[1] for row in db.execute("PRAGMA table_info(positions)")}
            for name, definition in POSITION_EXTENSIONS.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE positions ADD COLUMN {name} {definition}")
            # Preserve the entry timeframe of older positions when migrating.
            db.execute("UPDATE positions SET trail_timeframe=timeframe WHERE trail_timeframe=''")

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

    def fill_quality_summary(self, limit: int = 2000) -> dict:
        """Measured order-book slippage (positive = worse than the paper fill price), per direction."""
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM fill_quality ORDER BY id DESC LIMIT ?", (limit,))]
        def stats(group: list[dict]) -> dict | None:
            if not group:
                return None
            slip = np.array([r["slip_ref_bps"] for r in group])
            return {"n": len(group), "mean_bps": float(slip.mean()), "median_bps": float(np.median(slip)),
                    "p90_bps": float(np.percentile(slip, 90)), "worst_bps": float(slip.max()),
                    "mean_spread_bps": float(np.mean([r["spread_bps"] for r in group])),
                    "thin_book_fills": int(sum(r["filled_fraction"] < 0.999 for r in group))}
        return {"total": len(rows), "assumed_bps_per_fill": ASSUMED_SLIPPAGE_BPS,
                "entry": stats([r for r in rows if r["kind"] in ("entry", "add")]),
                "exit": stats([r for r in rows if r["kind"] == "exit"]),
                "last_error": self.runtime_all().get("fill_quality_error")}

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


def adx_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX with the period-1 DM/TR seed and mean of first period DX."""
    output = np.full(len(df), np.nan)
    high, low, close = (df[field].to_numpy(dtype=float) for field in ("high", "low", "close"))
    plus = minus = true_range = dx_sum = adx = 0.0
    count = 0
    for index in range(1, len(df)):
        up, down = high[index] - high[index - 1], low[index - 1] - low[index]
        pdm = up if up > down and up > 0 else 0.0
        mdm = down if down > up and down > 0 else 0.0
        tr = max(high[index] - low[index], abs(high[index] - close[index - 1]), abs(low[index] - close[index - 1]))
        if index < period:
            plus += pdm
            minus += mdm
            true_range += tr
            continue
        plus = plus - plus / period + pdm
        minus = minus - minus / period + mdm
        true_range = true_range - true_range / period + tr
        dx = 100 * abs(plus - minus) / (plus + minus) if plus + minus > 0 else 0.0
        if count < period:
            dx_sum += dx
            count += 1
            if count == period:
                adx = dx_sum / period
                output[index] = adx
        else:
            adx = (adx * (period - 1) + dx) / period
            output[index] = adx
    return pd.Series(output, index=df.index)


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
    df["adx"] = adx_wilder(df, c.get("structural_filters", {}).get("adx_period", 14))
    return archetypes.add_features(df) if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY" else df


def atr_regime_ratio(bars: list, c: dict, timeframe: str, now: float, window: int) -> float | None:
    """ATR of the last closed bar / median ATR of the `window` closed bars before it.

    Every ATR is the value indicators() would report as the last row of its own runtime window
    (candle_fetch_limit fetched, forming bar dropped), exactly like the research features, so `bars`
    must hold candle_fetch_limit + window candles. None when history is short, gapped or not finite.
    """
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(float).iloc[:-1]
    seconds = TIMEFRAMES[timeframe]
    df = df[df.timestamp + seconds * 1000 <= now * 1000].reset_index(drop=True)
    span = c["ichimoku_params"]["candle_fetch_limit"] - 1
    if len(df) < span + window or (np.diff(df.timestamp.to_numpy()[-(span + window):]) != seconds * 1000).any():
        return None
    period = c["filters_and_triggers"]["atr_period"]
    values = []
    for end in range(len(df) - window - 1, len(df)):
        w = df.iloc[end - span + 1:end + 1]
        previous = w.close.shift(1)
        tr = pd.concat([w.high - w.low, (w.high - previous).abs(), (w.low - previous).abs()], axis=1).max(axis=1)
        values.append(float(wilder(tr.reset_index(drop=True), period).iloc[-1]))
    current, median = values[-1], float(np.median(values[:-1]))
    if not (math.isfinite(current) and math.isfinite(median) and median > 0):
        return None
    return current / median


def regime(df: pd.DataFrame, c: dict) -> str | None:
    if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY":
        if df.empty:
            return None
        longs, shorts = archetypes.regime_masks(df, c)
        return "long" if longs.iloc[-1] else "short" if shorts.iloc[-1] else None
    displacement = c["ichimoku_params"]["displacement"]
    if len(df) <= displacement:
        return None
    bar, prior = df.iloc[-1], df.iloc[-1 - displacement]
    fields = ["close", "tenkan", "kijun", "senkou_a_future", "senkou_b_future", "kumo_top", "kumo_bottom", "atr"]
    if not np.isfinite(bar[fields]).all() or not np.isfinite(prior[["high", "low", "kumo_top", "kumo_bottom"]]).all() or bar.atr <= 0:
        return None
    if bar.kumo_bottom <= bar.close <= bar.kumo_top or abs(bar.senkou_a_future - bar.senkou_b_future) < 0.15 * bar.atr:
        return None
    structural = c.get("structural_filters", {})
    threshold = structural.get("min_htf_adx", 0)
    if threshold and ("adx" not in df or not math.isfinite(bar.adx) or bar.adx < threshold):
        return None
    long_slope = short_slope = True
    if structural.get("enable_htf_slope_filter", False):
        if len(df) < 4:
            return None
        long_slope = bar.kijun >= df.iloc[-4].kijun and bar.tenkan > df.iloc[-3].tenkan
        short_slope = bar.kijun <= df.iloc[-4].kijun and bar.tenkan < df.iloc[-3].tenkan
    if (bar.close > bar.kumo_top and bar.tenkan >= bar.kijun and
            bar.senkou_a_future > bar.senkou_b_future and
            bar.close > prior.high and bar.close > prior.kumo_top and long_slope):
        return "long"
    if (bar.close < bar.kumo_bottom and bar.tenkan <= bar.kijun and
            bar.senkou_a_future < bar.senkou_b_future and
            bar.close < prior.low and bar.close < prior.kumo_bottom and short_slope):
        return "short"
    return None


def entry_signal(df: pd.DataFrame, side: str, c: dict, htf: pd.DataFrame | None = None) -> bool:
    if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY":
        source = htf if c["archetype_strategy"]["family"] == "DONCHIAN" and htf is not None else df
        if source.empty or side not in ("long", "short"):
            return False
        longs, shorts = archetypes.entry_masks(source, c)
        return bool((longs if side == "long" else shorts).iloc[-1])
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

    def funding_mean(self, symbol: str, prints: int, before_ms: int) -> float | None:
        """Mean of the last `prints` funding rates stamped strictly before `before_ms`.

        csv-lbank mode reads FUNDING_DIR/<symbol>_funding.csv (timestamp ms, funding_rate), produced like the OHLCV
        CSVs; the research used Binance USDT-M funding history. Returns None when there is no usable data: demo mode,
        missing file, too few prints, or a latest print older than 9 hours (stale feed).
        """
        if self.mode == "demo":
            return None
        source = Path(os.getenv("FUNDING_DIR", "data/funding")) / (symbol.replace("/", "_").replace(":", "_") + "_funding.csv")
        if not source.is_file():
            return None
        df = pd.read_csv(source)
        if list(df.columns) != ["timestamp", "funding_rate"]:
            raise ValueError("Funding CSV header must be timestamp,funding_rate")
        df = df[df.timestamp < before_ms].sort_values("timestamp")
        if len(df) < prints or before_ms - int(df.timestamp.iloc[-1]) > 9 * 3600 * 1000:
            return None
        value = float(df.funding_rate.tail(prints).mean())
        return value if math.isfinite(value) else None

    def book_fill(self, symbol: str, buy: bool, contracts: float) -> dict | None:
        """Average price a market order of `contracts` would get by walking the live order book.

        Measurement only: returns None in demo mode (synthetic prices have no book) or if the book is unusable.
        """
        if self.mode == "demo" or contracts <= 0:
            return None
        with self.lock:
            self.market(symbol)
            book = self.exchange.fetch_order_book(symbol, 50)
        def clean(levels):
            out = [(float(x[0]), float(x[1])) for x in levels or [] if len(x) >= 2]
            return [(p, a) for p, a in out if math.isfinite(p) and math.isfinite(a) and p > 0 and a > 0]
        bids, asks = clean(book.get("bids")), clean(book.get("asks"))
        if not bids or not asks or bids[0][0] >= asks[0][0]:
            return None
        mid = (bids[0][0] + asks[0][0]) / 2
        remaining, cost, filled = contracts, 0.0, 0.0
        for price, amount in (asks if buy else bids):
            take = min(amount, remaining)
            cost += take * price
            filled += take
            remaining -= take
            if remaining <= 1e-12:
                break
        if filled <= 0:
            return None
        return {"mid": mid, "vwap": cost / filled, "filled_fraction": filled / contracts,
                "spread_bps": (asks[0][0] - bids[0][0]) / mid * 1e4}

    def precision(self, symbol: str, quantity: float) -> float:
        with self.lock:
            self.market(symbol)
            if self.mode == "demo":
                return math.floor(quantity * 1_000_000) / 1_000_000
            return float(self.exchange.amount_to_precision(symbol, quantity))

    @staticmethod
    def demo_base(symbol: str) -> float:
        bases = {"BTC": 60000, "ETH": 3000, "BNB": 600, "SOL": 150, "XRP": 0.5, "ADA": 0.4,
                 # C3 sleeve coins (c3_sleeve.py), synthetic demo only
                 "AAVE": 150, "UNI": 8, "AVAX": 30, "KSM": 30, "EGLD": 40, "DOT": 6, "DOGE": 0.15, "ONE": 0.02, "TRX": 0.12, "SUSHI": 1.0}
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


def entry_budget(equity: float, stop_pct: float, c: dict,
                 available_notional: float | None = None) -> dict:
    """Risk fixes notional; leverage changes only reserved isolated margin.

    The total stop allowance includes 0.04% slippage in the new sizing model.
    Caps/quantity rounding can reduce risk; they must never increase it.
    """
    r = c["risk_and_exit"]
    modern = "strategy_settings" in c
    slippage = 0.0004 if modern else 0.0
    risk = equity * r["risk_per_trade_pct"]
    slot = equity * (r["engaged_capital_pct"] / r["max_open_positions"] if modern
                     else r["max_margin_per_position_pct"])
    maximum = r["default_isolated_leverage"]
    pooled = c.get("portfolio_risk", {}).get("margin_allocation_mode") == "SHARED_POOL"
    if pooled:
        # Count limits do not allocate margin: every unit uses the remaining pool.
        slot = equity * r["engaged_capital_pct"]
        if available_notional is not None:
            slot = min(slot, max(0.0, available_notional) / maximum)
    target = risk / (stop_pct + r["lbank_round_trip_fee"] + slippage)
    leverage = (max(1, min(maximum, math.ceil(target / slot) if slot > 0 else maximum))
                if r["leverage_mode"] == "DYNAMIC_MARGIN" else maximum)
    cap = slot * (leverage if pooled else maximum)
    if available_notional is not None:
        # available_notional expresses free margin at the maximum leverage.
        cap = min(cap, max(0.0, available_notional) / maximum * leverage)
    return dict(risk_budget=risk, slot_margin_usd=slot, isolated_leverage=leverage,
                max_notional=cap, final_notional=min(target, cap), sizing_slippage_pct=slippage)


def position_leverage(p: dict, default: int = 5) -> int:
    if p.get("isolated_leverage", 0) > 0:
        return int(p["isolated_leverage"])
    frozen = json.loads(p.get("strategy_config", "{}"))
    return frozen.get("risk_and_exit", {}).get("default_isolated_leverage", default)


def position_margin(p: dict, default: int = 5) -> float:
    return p["qty"] * p["entry_price"] * p["contract_size"] / position_leverage(p, default)


def size_position(data: MarketData, symbol: str, side: str, bar: pd.Series,
                  equity: float, c: dict, timeframe: str, structural_bar: pd.Series | None = None,
                  available_notional: float | None = None) -> dict | None:
    r, a = c["risk_and_exit"], c["al_brooks_filters"]
    sign = 1 if side == "long" else -1
    entry = (bar.high + a["stop_entry_atr_buffer"] * bar.atr if side == "long" else
             bar.low - a["stop_entry_atr_buffer"] * bar.atr) if a["require_signal_bar_breakout"] else bar.close
    stop = (min(bar.low, bar.kijun) - r["sl_atr_buffer"] * bar.atr if side == "long" else
            max(bar.high, bar.kijun) + r["sl_atr_buffer"] * bar.atr)
    spec = c.get("archetype_strategy", archetypes.DEFAULTS)
    if spec["family"] != "LEGACY":
        source = structural_bar if structural_bar is not None else bar
        stop = archetypes.initial_stop(source, side, c)
        if not a["require_signal_bar_breakout"]:
            entry = float(source.close)
    distance = sign * (entry - stop)
    if equity <= 0 or stop <= 0 or entry <= 0 or distance <= 0:
        return None
    minimum = r.get("min_stop_distance_pct", 0.0)
    policy = r.get("min_stop_policy", "NONE")
    if minimum and distance / entry < minimum:
        if policy == "REJECT":
            return None
        if policy == "WIDEN":
            stop = entry - sign * minimum * entry
            distance = sign * (entry - stop)
    if equity <= 0 or stop <= 0 or entry <= 0 or distance <= 0:
        return None
    cs = float(data.market(symbol).get("contractSize") or 1)
    # Optional stop-width filter: very wide 2*ATR stops (exhaustion breakouts) are skipped, wide ones sized down.
    risk_mult, settings = 1.0, c.get("strategy_settings", {})
    if settings.get("stop_width_filter_enabled", False):
        width = distance / entry
        if width > settings["stop_width_skip_pct"]:
            return None
        if width > settings["stop_width_mid_pct"]:
            risk_mult = settings["stop_width_mid_risk_fraction"]
    sized = c
    if risk_mult != 1.0:
        sized = copy.deepcopy(c)
        sized["risk_and_exit"]["risk_per_trade_pct"] *= risk_mult
    budget = entry_budget(equity, distance / entry, sized, available_notional)
    risk, cap = budget["risk_budget"], budget["max_notional"]
    # CCXT contract quantity is contracts, not necessarily base units.
    qty = data.precision(symbol, budget["final_notional"] / entry / cs)
    if not data.tradable(symbol, qty, entry):
        return None
    scheme = r.get("exit_scheme", "LEGACY")
    rr = r.get("breakeven_trigger_rr", 2.0) if scheme == "PURE_RUNNER" else r["tp1_rr_ratio"]
    mode = c["strategy_mode"]
    trend_tf = mode["htf_trend_timeframe"] if mode["mode"] == "MTF" else mode["single_timeframe"]
    trail_tf = trend_tf if r.get("trail_timeframe", "ENTRY") == "HTF" else timeframe
    hard_rr = r.get("hard_tp_rr", 0.0)
    return dict(symbol=symbol, side=side, entry_price=float(entry), qty=qty,
        initial_sl=float(stop), active_sl=float(stop), tp1_price=float(entry + sign * rr * distance),
        state=PENDING, trigger_price=float(entry), cancel_price=float(stop),
        expiry_ts=9_000_000_000_000 if spec["pending_policy"] == "GTC_REGIME" else int(bar.timestamp / 1000 + TIMEFRAMES[timeframe] * (1 + a["pending_order_expiry_bars"])),
        dry_run=1, contract_size=cs, fee_rate=r["lbank_round_trip_fee"],
        tp1_close_pct=r["tp1_close_pct"], tp1_rr=rr, risk_budget=risk,
        max_notional=cap, timeframe=timeframe, signal_ts=int(bar.timestamp),
        exit_scheme=scheme, be_policy=r.get("breakeven_policy", "ENTRY"),
        be_confirmed=int(r.get("breakeven_policy", "ENTRY") != "CLOSE_CONFIRM"),
        trail_atr=r.get("trail_atr_buffer", 0.2), trail_timeframe=trail_tf,
        hard_tp_price=float(entry + sign * hard_rr * distance) if hard_rr else 0.0,
        hard_tp_rr=hard_rr, initial_r_distance=float(distance),
        be_trigger_rr=r.get("breakeven_trigger_rr", 2.0),
        isolated_leverage=budget["isolated_leverage"], slot_margin_usd=budget["slot_margin_usd"],
        sizing_slippage_pct=budget["sizing_slippage_pct"],
        stop_atr_distance=float(distance) if "strategy_settings" in c and spec["stop_source"] == "ATR2" and c["strategy_settings"]["initial_stop_anchor"] == "ENTRY" else 0.0,
        root_entry_price=float(entry), root_r_distance=float(distance), risk_mult=float(risk_mult),
        archetype_family=spec["family"], trail_source=spec["trail_source"],
        trail_close_only=int(spec["trail_close_only"]), pending_policy=spec["pending_policy"],
        strategy_config=json.dumps(c) if spec["family"] != "LEGACY" else "{}")


def runner_transition(p: dict) -> tuple[float, int]:
    """Return stop and confirmation after a partial target, never tightening early."""
    policy = p.get("be_policy", "ENTRY")
    sign = 1 if p["side"] == "long" else -1
    distance = p.get("initial_r_distance", 0) or abs(p["entry_price"] - p["initial_sl"])
    if policy == "QUARTER_R":
        return p["entry_price"] - sign * 0.25 * distance, 1
    if policy == "CLOSE_CONFIRM":
        return p["active_sl"], 0
    return p["entry_price"], 1


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

    def main_paper_equity(self) -> float:
        with self.db.connect() as db:
            realized = float(db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM trade_history WHERE dry_run=1").fetchone()[0])
        unrealized = 0.0
        for p in self.db.positions():
            self.assert_paper(p)
            if p["state"] != PENDING:
                unrealized += net_pnl(p, self.data.price(p["symbol"], cached=True), p["qty"])
        return max(0.0, self.paper_seed + realized + unrealized)

    def shared_paper_account(self):
        if not self.config.read()["portfolio_risk"]["shared_c3_account"]:
            return None
        import c3_sleeve
        from shared_paper_account import SharedPaperAccount
        cfg, store = c3_sleeve.paths()
        return SharedPaperAccount(self, store, lambda: c3_sleeve.load(cfg))

    def paper_equity(self) -> float:
        account = self.shared_paper_account()
        return account.equity() if account is not None else self.main_paper_equity()

    def available_notional(self, equity: float, c: dict, exclude_symbol: str | None = None) -> float:
        leverage = c["risk_and_exit"]["default_isolated_leverage"]
        account = self.shared_paper_account()
        if account is not None:
            return account.available_margin(equity, exclude_symbol, leverage,
                c["risk_and_exit"]["lbank_round_trip_fee"], c["risk_and_exit"]["engaged_capital_pct"]) * leverage
        reserved = 0.0
        for p in self.db.positions():
            if p["symbol"] == exclude_symbol:
                continue
            reserved += position_margin(p, leverage)
        return max(0.0, equity * c["risk_and_exit"]["engaged_capital_pct"] - reserved) * leverage

    def _record_fill(self, kind: str, p: dict, price: float, qty: float, reason: str = ""):
        """Log what this paper fill would have cost against the real book. Never raises, never moves PnL."""
        if os.getenv("FILL_QUALITY", "on") == "off" or not hasattr(self.data, "book_fill"):
            return
        try:
            buy = (p["side"] == "long") if kind in ("entry", "add") else (p["side"] == "short")
            info = self.data.book_fill(p["symbol"], buy, qty)
            if info is None:
                return
            sign = 1 if buy else -1  # paying more / receiving less than the reference is adverse
            slip_ref = sign * (info["vwap"] - price) / price * 1e4
            slip_mid = sign * (info["vwap"] - info["mid"]) / info["mid"] * 1e4
            with self.db.connect() as db:
                db.execute("INSERT INTO fill_quality(ts,symbol,kind,reason,side,ref_price,mid,vwap,qty,notional_usd,"
                           "slip_ref_bps,slip_mid_bps,spread_bps,filled_fraction) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (time.time(), p["symbol"], kind, reason, "buy" if buy else "sell", price, info["mid"],
                            info["vwap"], qty, qty * p.get("contract_size", 1) * info["vwap"], slip_ref, slip_mid,
                            info["spread_bps"], info["filled_fraction"]))
            self.db.runtime_set("fill_quality_error", None)
        except Exception as exc:
            LOG.warning("Fill-quality measurement failed for %s: %s", p.get("symbol"), exc)
            try:
                self.db.runtime_set("fill_quality_error", f"{p.get('symbol')}: {exc}"[:300])
            except Exception:
                pass

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

    def _activate(self, p: dict, price: float, now: float | None = None) -> bool:
        self.assert_paper(p)
        direction = 1 if p["side"] == "long" else -1
        current = self.config.read()
        modern = "strategy_settings" in current
        if p.get("stop_atr_distance", 0) > 0:
            p["initial_sl"] = price - direction * p["stop_atr_distance"]
        distance = direction * (price - p["initial_sl"])
        if distance <= 0 or p["initial_sl"] <= 0:
            with self.db.connect() as db:
                db.execute("DELETE FROM positions WHERE symbol=? AND state=?", (p["symbol"], PENDING))
            return False
        retained = json.loads(p.get("strategy_config", "{}"))
        if retained:
            risk = retained["risk_and_exit"]
            if risk["min_stop_policy"] == "REJECT" and distance / price < risk["min_stop_distance_pct"]:
                with self.db.connect() as db:
                    db.execute("DELETE FROM positions WHERE symbol=? AND state=?", (p["symbol"], PENDING))
                return False
        if modern:
            equity = self.paper_equity()
            daily, _ = self.db.history_summary(now if now is not None else time.time())
            others = [x for x in self.db.positions() if x["symbol"] != p["symbol"]]
            if (equity <= 0 or daily <= -equity * current["risk_and_exit"]["daily_max_loss_pct"]
                    or len(others) >= current["risk_and_exit"]["max_open_positions"]
                    or distance / price < current["risk_and_exit"]["min_stop_distance_pct"]):
                with self.db.connect() as db:
                    db.execute("DELETE FROM positions WHERE symbol=? AND state=?", (p["symbol"], PENDING))
                return False
            sized = current
            if p.get("risk_mult", 1.0) != 1.0:  # the signal-time width filter halved this position's risk
                sized = copy.deepcopy(current)
                sized["risk_and_exit"]["risk_per_trade_pct"] *= p["risk_mult"]
            budget = entry_budget(equity, distance / price, sized,
                                  self.available_notional(equity, current, p["symbol"]))
            p["fee_rate"] = current["risk_and_exit"]["lbank_round_trip_fee"]
            p.update({k: v for k, v in budget.items() if k != "final_notional"})
            p["qty"] = budget["final_notional"] / price / p["contract_size"]
        elif current["portfolio_risk"]["enforce_shared_margin"]:
            equity = self.paper_equity()
            p["risk_budget"] = min(p["risk_budget"], equity * current["risk_and_exit"]["risk_per_trade_pct"])
            p["max_notional"] = min(p["max_notional"], self.available_notional(equity, current, p["symbol"]),
                                     equity * current["risk_and_exit"]["max_margin_per_position_pct"] * current["risk_and_exit"]["default_isolated_leverage"])
        # Re-size at the simulated fill after a gap, so risk isn't based on an old trigger.
        cap = min(p["qty"], p["risk_budget"] / (distance + price * (p["fee_rate"] + p.get("sizing_slippage_pct", 0))) / p["contract_size"],
                  p["max_notional"] / price / p["contract_size"])
        qty = self.data.precision(p["symbol"], cap)
        if not self.data.tradable(p["symbol"], qty, price):
            with self.db.connect() as db:
                db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
            return False
        with self.db.connect() as db:
            scheme = p.get("exit_scheme", "LEGACY")
            hard_rr = p.get("hard_tp_rr", 0.0)
            db.execute("UPDATE positions SET state=?,entry_price=?,qty=?,tp1_price=?,initial_r_distance=?,hard_tp_price=?,trail_last_candle_ts=?,initial_sl=?,active_sl=?,isolated_leverage=?,slot_margin_usd=?,sizing_slippage_pct=?,risk_budget=?,max_notional=?,fee_rate=?,root_entry_price=?,root_r_distance=? "
                "WHERE symbol=? AND state=?",
                (TRAILING if scheme == "PURE_KIJUN" else INITIAL, price, qty,
                 price + direction * p["tp1_rr"] * distance, distance,
                 price + direction * hard_rr * distance if hard_rr else 0.0,
                 self.trail_marker(p, now if now is not None else time.time()) if scheme == "PURE_KIJUN" else 0,
                 p["initial_sl"], p["initial_sl"], p.get("isolated_leverage", 0), p.get("slot_margin_usd", 0),
                 p.get("sizing_slippage_pct", 0), p["risk_budget"], p["max_notional"], p["fee_rate"], price, distance, p["symbol"], PENDING))
        self._record_fill("entry", p, price, qty)
        return True

    @staticmethod
    def trail_marker(p: dict, now: float) -> int:
        # The scanner runs 3 seconds after close. Do not reuse an older candle
        # after an intrabar milestone; a milestone before that scan may use the new close.
        seconds = TIMEFRAMES[p.get("trail_timeframe") or p["timeframe"]]
        return (int(now - 3) // seconds - 1) * seconds * 1000

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
                stop, confirmed = runner_transition(p) if transition else (p["active_sl"], p.get("be_confirmed", 1))
                db.execute("UPDATE positions SET qty=?,active_sl=?,state=?,be_confirmed=?,trail_last_candle_ts=? WHERE symbol=?",
                    (remaining, stop, TRAILING if transition else p["state"], confirmed,
                     self.trail_marker(p, now) if transition else p.get("trail_last_candle_ts", 0), p["symbol"]))
        if reason != "panic":  # never delay an emergency close with a network call
            self._record_fill("exit", p, price, qty, reason)
        return {"symbol": p["symbol"], "result": "closed", "qty": qty, "pnl_usd": pnl, "dry_run": True}

    def apply_profit_floor(self, p: dict, price: float):
        """Once the root unit has reached trigger R, never let the shared stop sit below entry +/- lock R.

        Idempotent and ratchet-only, so the persisted active_sl is the whole state: no extra column needed.
        """
        settings = json.loads(p.get("strategy_config", "{}")).get("strategy_settings", {})
        entry, distance = p.get("root_entry_price", 0), p.get("root_r_distance", 0)
        # Verified only with the unlimited Donchian10 stop trail; other exit modes keep their own stop logic.
        if (not settings.get("profit_floor_enabled", False) or settings.get("exit_tp_mode") != "STOP_TRAIL_DONCHIAN10"
                or p["state"] == PENDING or entry <= 0 or distance <= 0):
            return
        sign = 1 if p["side"] == "long" else -1
        if sign * (price - entry) < settings["profit_floor_trigger_r"] * distance:
            return
        floor = entry + sign * settings["profit_floor_lock_r"] * distance
        if sign * (floor - p["active_sl"]) > 0:
            with self.db.connect() as db:
                db.execute("UPDATE positions SET active_sl=? WHERE symbol=?", (float(floor), p["symbol"]))
            p["active_sl"] = float(floor)

    def arm_pyramid(self, p: dict, price: float, now: float):
        """Arm only after the root is 2R profitable and its stop covers costs."""
        frozen = json.loads(p.get("strategy_config", "{}"))
        if (not frozen.get("strategy_settings", {}).get("pyramid_enabled", False)
                or p.get("pyramid_added") or p.get("pyramid_eligible_ts") or p["state"] == PENDING):
            return
        sign = 1 if p["side"] == "long" else -1
        entry, distance = p.get("root_entry_price", 0), p.get("root_r_distance", 0)
        costs = p["fee_rate"] + p.get("sizing_slippage_pct", 0)
        if (entry > 0 and distance > 0 and sign * (price - entry) >= 2 * distance
                and sign * (p["active_sl"] - entry) >= entry * costs):
            with self.db.connect() as db:
                db.execute("UPDATE positions SET pyramid_eligible_ts=? WHERE symbol=?", (now, p["symbol"]))
            p["pyramid_eligible_ts"] = now

    def _pyramid_add(self, p: dict, side: str, bar: pd.Series, c: dict, now: float) -> bool:
        """One half-risk unit; same symbol slot/stop, persisted atomically.

        The paper position stores the weighted entry; costs/PnL remain linear.
        Root entry/R and the scale-in ledger remain separate for audit/restarts.
        """
        frozen = json.loads(p.get("strategy_config", "{}"))
        settings = frozen.get("strategy_settings", {})
        if (not settings.get("pyramid_enabled", False) or p["state"] != TRAILING
                or p.get("pyramid_added") or side != p["side"]
                or settings != c.get("strategy_settings")
                or position_leverage(p) != c["risk_and_exit"]["default_isolated_leverage"]
                or p["fee_rate"] != c["risk_and_exit"]["lbank_round_trip_fee"]):
            return False
        close_time = float(bar.timestamp) / 1000 + TIMEFRAMES[p["timeframe"]]
        if not 0 < p.get("pyramid_eligible_ts", 0) < close_time:
            return False
        self.assert_paper(p)
        price = self.data.price(p["symbol"])
        sign = 1 if side == "long" else -1
        distance = sign * (price - p["active_sl"])
        root = p["root_entry_price"]
        if (sign * (price - root) < 2 * p["root_r_distance"]
                or sign * (p["active_sl"] - root) < root * (p["fee_rate"] + .0004)
                or distance <= 0 or distance / price < .012
                or sign * (bar.close - p["active_sl"]) / bar.close < .012):
            return False
        equity = self.paper_equity()
        daily, _ = self.db.history_summary(now)
        if equity <= 0 or daily <= -equity * c["risk_and_exit"]["daily_max_loss_pct"]:
            return False
        unit = copy.deepcopy(c)
        unit["risk_and_exit"]["risk_per_trade_pct"] *= settings.get("pyramid_risk_fraction", .5)
        available = self.available_notional(equity, c)
        planned = entry_budget(equity, sign * (bar.close - p["active_sl"]) / bar.close, unit, available)
        budget = entry_budget(equity, distance / price, unit, available)
        cap = min(planned["final_notional"] / bar.close, budget["final_notional"] / price) / p["contract_size"]
        qty = self.data.precision(p["symbol"], cap)
        if not self.data.tradable(p["symbol"], qty, price):
            return False
        if settings.get("safe_pyramid_enabled", False):
            # Combined stop-out must be net >= 0 after round-trip fees and the benchmark's 2bps adverse
            # slippage on both entries and the exit; otherwise the add-on could turn a winner into a loser.
            side_fee, slip, cs = p["fee_rate"] / 2, .0002, p["contract_size"]
            exit_price = p["active_sl"] * (1 - sign * slip)
            combined = 0.0
            for unit_qty, unit_entry in ((p["qty"], p["entry_price"]), (qty, price)):
                fill = unit_entry * (1 + sign * slip)
                combined += unit_qty * cs * (sign * (exit_price - fill) - side_fee * (fill + exit_price))
            if combined < 0:
                return False
        total = p["qty"] + qty
        average = (p["entry_price"] * p["qty"] + price * qty) / total
        modeled_risk = qty * p["contract_size"] * (distance + price * (p["fee_rate"] + .0004))
        with self.db.connect() as db:
            cursor = db.execute("UPDATE positions SET qty=?,entry_price=?,pyramid_added=1 WHERE symbol=? AND pyramid_added=0 AND state=?",
                                (total, average, p["symbol"], TRAILING))
            if not cursor.rowcount:
                return False
            db.execute("INSERT INTO scale_in_history(symbol,root_signal_ts,added_at,entry_price,qty,shared_stop,modeled_risk_usd,root_entry_price,root_r_distance) VALUES(?,?,?,?,?,?,?,?,?)",
                       (p["symbol"], p["signal_ts"], now, price, qty, p["active_sl"], modeled_risk, root, p["root_r_distance"]))
        self._record_fill("add", p, price, qty)
        return True

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
                    if p["state"] == PENDING and p.get("pending_policy") == "GTC_REGIME":
                        frozen = json.loads(p.get("strategy_config", "{}")) or self.config.read()
                        modes = frozen["strategy_mode"]
                        tf = modes["htf_trend_timeframe"] if modes["mode"] == "MTF" else modes["single_timeframe"]
                        history = indicators(self.data.candles(p["symbol"], tf, frozen["ichimoku_params"]["candle_fetch_limit"]), frozen, tf, now)
                        expected = (int(now) // TIMEFRAMES[tf] - 1) * TIMEFRAMES[tf] * 1000
                        if history.empty or int(history.iloc[-1].timestamp) != expected:
                            raise ValueError("Stale regime for pending archetype setup")
                        if regime(history, frozen) != p["side"]:
                            with self.db.connect() as db:
                                db.execute("DELETE FROM positions WHERE symbol=?", (p["symbol"],))
                            continue
                    price = self.data.price(p["symbol"])
                    sign = 1 if p["side"] == "long" else -1
                    self.apply_profit_floor(p, price)
                    self.arm_pyramid(p, price, now)
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
                                self._activate(p, price, now)
                        continue
                    if sign * (price - p["active_sl"]) <= 0:
                        self._close(p, price, p["qty"], "stop", now)
                    elif p.get("hard_tp_price", 0) > 0 and sign * (price - p["hard_tp_price"]) >= 0:
                        self._close(p, price, p["qty"], "hard_tp", now)
                    elif (p.get("sizing_slippage_pct", 0) > 0 and p.get("be_trigger_rr", 0) > 0
                          and sign * (p["active_sl"] - p["entry_price"]) < 0
                          and sign * (price - p["entry_price"]) >= p["be_trigger_rr"] * p["initial_r_distance"]):
                        with self.db.connect() as db:
                            db.execute("UPDATE positions SET active_sl=?,be_confirmed=1 WHERE symbol=?",
                                       (p["entry_price"], p["symbol"]))
                    elif p["state"] == INITIAL and p.get("exit_scheme") != "HARD_TARGET" and sign * (price - p["tp1_price"]) >= 0:
                        if p.get("exit_scheme", "LEGACY") == "PURE_RUNNER":
                            with self.db.connect() as db:
                                db.execute("UPDATE positions SET state=?,active_sl=?,be_confirmed=1,trail_last_candle_ts=? WHERE symbol=?",
                                           (TRAILING, p["entry_price"], self.trail_marker(p, now), p["symbol"]))
                            continue
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

        def frame(symbol: str, tf: str, frozen: dict | None = None) -> pd.DataFrame:
            settings = frozen or c
            key = (symbol, tf, json.dumps([settings["ichimoku_params"], settings["filters_and_triggers"], settings.get("archetype_strategy", archetypes.DEFAULTS)]))
            if key not in frames:
                result = indicators(self.data.candles(symbol, tf, settings["ichimoku_params"]["candle_fetch_limit"]), settings, tf, now)
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
                frozen = json.loads(old.get("strategy_config", "{}")) or c
                trail_tf = old.get("trail_timeframe") or old["timeframe"]
                # Candle-confirmed BE uses the retained entry timeframe, even
                # when the runner follows a higher-timeframe Kijun.
                if old.get("be_policy") == "CLOSE_CONFIRM" and not old.get("be_confirmed"):
                    entry_bar = frame(old["symbol"], old["timeframe"], frozen).iloc[-1]
                    with file_lock(self.db.trade_lock):
                        current = self.db.position(old["symbol"])
                        if current and current["state"] == TRAILING and not current["be_confirmed"]:
                            direction = 1 if current["side"] == "long" else -1
                            distance = current["initial_r_distance"] or abs(current["entry_price"] - current["initial_sl"])
                            if direction * (entry_bar.close - current["entry_price"]) >= current["be_trigger_rr"] * distance:
                                stop = max(current["active_sl"], current["entry_price"]) if direction == 1 else min(current["active_sl"], current["entry_price"])
                                with self.db.connect() as db:
                                    db.execute("UPDATE positions SET active_sl=?,be_confirmed=1 WHERE symbol=?", (stop, current["symbol"]))
                b = frame(old["symbol"], trail_tf, frozen).iloc[-1]
                if not np.isfinite(b[["kijun", "atr"]]).all():
                    raise ValueError("Uninitialized trailing indicators")
                with file_lock(self.db.trade_lock):
                    p = self.db.position(old["symbol"])
                    if not p or p["state"] != TRAILING:
                        continue
                    self.assert_paper(p)
                    if int(b.timestamp) <= p.get("trail_last_candle_ts", 0):
                        continue
                    with self.db.connect() as db:
                        db.execute("UPDATE positions SET trail_last_candle_ts=? WHERE symbol=?", (int(b.timestamp), p["symbol"]))
                    sign = 1 if p["side"] == "long" else -1
                    line = archetypes.trail_line(b, p["side"], p.get("trail_source", "KIJUN"))
                    if sign * (b.close - line) < 0:
                        self._close(p, self.data.price(p["symbol"]), p["qty"], "kijun_break", now)
                    elif not p.get("trail_close_only") and (p.get("be_policy") != "CLOSE_CONFIRM" or p.get("be_confirmed")):
                        sl = archetypes.buffered_trail_stop(
                            b, p["side"], p.get("trail_source", "KIJUN"), p.get("trail_atr", 0.2))
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
        gate = c.get("strategy_settings", {})
        btc_inside = False
        if gate.get("btc_regime_filter_enabled", False):
            # Computed before any symbol is marked as scanned: if BTC data is stale we retry the whole scan instead of
            # silently consuming the candle with the gate open.
            try:
                bar = frame(gate["btc_regime_symbol"], ltf).iloc[-1]
                btc_inside = bool(np.isfinite(bar.kumo_bottom) and np.isfinite(bar.kumo_top) and bar.kumo_bottom <= bar.close <= bar.kumo_top)
            except Exception as exc:
                LOG.exception("BTC regime gate unavailable; retrying scan")
                self.db.runtime_set("last_error", str(exc))
                return False
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
                if c["archetype_strategy"]["family"] == "DONCHIAN" and (stamp + TIMEFRAMES[ltf] * 1000) % (4 * 3600 * 1000):
                    continue
                if btc_inside and symbol != gate["btc_regime_symbol"]:
                    continue
                if side == "short" and gate.get("funding_short_filter_enabled", False):
                    reader = getattr(self.data, "funding_mean", None)
                    mean = reader(symbol, gate["funding_short_prints"], stamp + TIMEFRAMES[ltf] * 1000) if reader else None
                    if mean is None:
                        # Same as the research: no funding history means the filter does not block.
                        LOG.warning("Funding data unavailable for %s; short filter not applied", symbol)
                    elif mean < gate["funding_short_threshold"]:
                        continue
                if side and (entry_signal(low, side, c) if c["archetype_strategy"]["family"] == "LEGACY" else entry_signal(low, side, c, high)):
                    if gate.get("atr_regime_filter_enabled", False):
                        # Research: missing/short history blocks the entry; a blocked bar also blocks the pyramid add.
                        window = gate["atr_regime_window"]
                        ratio = atr_regime_ratio(self.data.candles(symbol, htf, c["ichimoku_params"]["candle_fetch_limit"] + window), c, htf, now, window)
                        if ratio is None or ratio < gate["atr_regime_min_ratio"]:
                            if ratio is None:
                                LOG.warning("ATR regime history unavailable for %s; entry skipped", symbol)
                            continue
                    score = (archetypes.breakout_strength(high.iloc[-1], side, c["archetype_strategy"]["donchian_lookback"])
                             if c["portfolio_risk"]["rank_by"] == "BREAKOUT_DISTANCE" else
                             abs(low.iloc[-1].rsi - (55 if side == "long" else 45)))
                    candidates.append((float(score), symbol, side, low.iloc[-1], high.iloc[-1] if c["archetype_strategy"]["family"] == "DONCHIAN" else None))
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
            ordering = (lambda item: (-item[0], c["symbols"].index(item[1]))) if c["portfolio_risk"]["rank_by"] == "BREAKOUT_DISTANCE" else (lambda item: (item[0], item[1]))
            for _, symbol, side, bar, structural in sorted(candidates, key=ordering):
                if blocked:
                    break
                existing = self.db.position(symbol)
                if existing:
                    self._pyramid_add(existing, side, structural if structural is not None else bar, c, now)
                    continue
                if available <= 0:
                    continue
                with self.db.connect() as db:
                    prior = db.execute("SELECT candle_ts FROM scanned_candles WHERE symbol=? AND timeframe=?", (symbol, ltf)).fetchone()
                if prior and prior[0] >= int(bar.timestamp):
                    continue
                capacity = None
                if c["portfolio_risk"]["enforce_shared_margin"]:
                    equity = self.paper_equity()
                    if equity <= 0 or daily <= -equity * c["risk_and_exit"]["daily_max_loss_pct"]:
                        break
                    capacity = self.available_notional(equity, c)
                p = size_position(self.data, symbol, side, bar, equity, c, ltf, structural, capacity)
                if p is None:
                    continue
                price = None
                if not c["al_brooks_filters"]["require_signal_bar_breakout"]:
                    # A failed price fetch must not leave a fabricated open fill.
                    price = self.data.price(symbol)
                self._insert(p)
                if price is not None:
                    self._activate(p, price, now)
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
                periods = [TIMEFRAMES[tf]] + [TIMEFRAMES[p.get("trail_timeframe") or p["timeframe"]] for p in db.positions() if p["state"] == TRAILING]
                periods += [TIMEFRAMES[p["timeframe"]] for p in db.positions() if p["state"] == TRAILING and p.get("be_policy") == "CLOSE_CONFIRM"]
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
    c3_thread = None
    try:   # second strategy (C3+D on 10 other coins), paper-only; a failure here never stops the main bot
        sys.modules.setdefault("lbank_bot", sys.modules[__name__])
        import c3_sleeve
        c3_thread = c3_sleeve.start_in_bot(engine, stop)
    except Exception as exc:
        LOG.exception("C3 sleeve failed to start; main bot continues")
        db.runtime_set("c3_error", str(exc))
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
    if c3_thread:
        c3_thread.join(timeout=12)


def probe_book(symbol: str, contracts: float):
    """`python lbank_bot.py --probe-book BTC/USDT:USDT 0.01`: check that live order-book measurement works."""
    data = MarketData()
    if data.mode == "demo":
        sys.exit("Set PAPER_DATA_MODE=csv-lbank first: demo mode has no order book.")
    for buy in (True, False):
        print("BUY " if buy else "SELL", json.dumps(data.book_fill(symbol, buy, contracts)))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--probe-book":
        probe_book(sys.argv[2], float(sys.argv[3]))
    else:
        run()
