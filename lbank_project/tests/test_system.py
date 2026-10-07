import copy
from concurrent.futures import ThreadPoolExecutor
import json
import math
import multiprocessing
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
import yaml

import lbank_bot as lb
from dashboard_server import create_app

ROOT = Path(__file__).parents[1]


@pytest.fixture
def cfg():
    return lb.validate_config(json.loads((ROOT / "tests" / "baseline_config.json").read_text()))


class FakeData:
    mode = "test-fixture"

    def __init__(self):
        self.prices = {}
        self.fail = set()
        self.contract_size = 1.0
        self.minimum = 0.001
        self.bars = {}

    def market(self, symbol):
        return {"contractSize": self.contract_size}

    def price(self, symbol, cached=False):
        if symbol in self.fail:
            raise RuntimeError("price feed unavailable")
        return self.prices.get(symbol, 100.0)

    def precision(self, symbol, quantity):
        return math.floor(quantity * 1e6 + 1e-8) / 1e6

    def tradable(self, symbol, qty, price):
        return qty >= self.minimum and price > 0

    def candles(self, symbol, timeframe, limit):
        return self.bars[(symbol, timeframe)][-limit:]


@pytest.fixture
def system(tmp_path, cfg):
    config = lb.ConfigStore(tmp_path / "config.json")
    config.write(cfg)
    db = lb.Database(tmp_path / "data" / "lbank_ichimoku_bot.db")
    data = FakeData()
    return lb.Engine(config, db, data, paper_equity=10000)


def setup_position(engine, symbol="BTC/USDT:USDT", side="long", state=lb.PENDING):
    direction = 1 if side == "long" else -1
    p = dict(symbol=symbol, side=side, entry_price=100.0, qty=2.0,
        initial_sl=100.0 - direction * 10, active_sl=100.0 - direction * 10,
        tp1_price=100.0 + direction * 15, state=state, trigger_price=100.0,
        cancel_price=100.0 - direction * 10, expiry_ts=2_000_000_000,
        dry_run=1, contract_size=1.0, fee_rate=0.0012, tp1_close_pct=0.5,
        tp1_rr=1.5, risk_budget=50.0, max_notional=5000.0, timeframe="1h", signal_ts=0)
    engine._insert(p)
    return p


def bars_for(now, tf="1h", n=200, flat=False):
    seconds = lb.TIMEFRAMES[tf]
    boundary = int(now) // seconds * seconds
    result = []
    for index in range(n):
        stamp = boundary - (n - index - 1) * seconds
        center = 100.0 if flat else 100 + index * 0.1 + math.sin(index / 3)
        result.append([stamp * 1000, center - 0.1, center + 0.5,
                       center - 0.5, center + 0.1, 10.0])
    return result


def signal_frame(side="long"):
    rows = [{"open": 10, "high": 11, "low": 9, "close": 10, "kijun": 9.5,
             "rsi": 55, "atr": 1, "timestamp": index * 3600000} for index in range(12)]
    rows[5]["high"] = 12
    rows[6]["low"] = 8.8
    rows[-1].update(open=9.2, close=10.8)
    df = pd.DataFrame(rows)
    if side == "short":
        original = df.copy()
        for field in ("open", "close", "kijun"):
            df[field] = 20 - original[field]
        df["high"], df["low"] = 20 - original.low, 20 - original.high
        df["rsi"] = 45
    return df


def test_default_schema(cfg):
    assert lb.validate_config(cfg) == cfg


@pytest.mark.parametrize("section,key,value", [
    ("risk_and_exit", "risk_per_trade_pct", 0.0001),
    ("risk_and_exit", "risk_per_trade_pct", 0.051),
    ("risk_and_exit", "tp1_close_pct", 1),
    ("risk_and_exit", "lbank_round_trip_fee", float("nan")),
    ("risk_and_exit", "default_isolated_leverage", True),
    ("strategy_mode", "mode", "INVALID"),
    ("strategy_mode", "htf_trend_timeframe", "1m"),
    ("ichimoku_params", "candle_fetch_limit", 180),
    ("bot_control", "dry_run_mode", False),
    ("al_brooks_filters", "barb_wire_lookback", 1),
])
def test_invalid_config(cfg, section, key, value):
    cfg[section][key] = value
    with pytest.raises(lb.ConfigError):
        lb.validate_config(cfg)


@pytest.mark.parametrize("symbols", [["../../USDT:USDT"], [None], [["BTC"]], [], ["BTC/USDT:USDT"] * 2])
def test_bad_symbols(cfg, symbols):
    cfg["symbols"] = symbols
    with pytest.raises(lb.ConfigError):
        lb.validate_config(cfg)


def test_config_atomic_read_write(system):
    first = system.config.read()
    second = copy.deepcopy(first)
    second["bot_control"]["auto_trade_enabled"] = False
    def writer():
        for _ in range(25):
            system.config.write(first)
            system.config.write(second)
    def reader():
        for _ in range(100):
            assert system.config.read() in (first, second)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(writer)] + [pool.submit(reader) for _ in range(3)]
        for future in futures:
            future.result(timeout=15)
    assert not list(system.config.path.parent.glob("*.tmp"))


def test_wal_and_sqlite_transaction(system):
    with system.db.connect() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with pytest.raises(RuntimeError):
        with system.db.connect() as db:
            db.execute("INSERT INTO runtime VALUES('rollback','true')")
            raise RuntimeError("rollback")
    assert "rollback" not in system.db.runtime_all()


def test_wilder_sma_seed_and_recurrence():
    values = pd.Series([np.nan, 1.0, 2.0, 3.0, 4.0, 8.0])
    actual = lb.wilder(values, 3)
    assert math.isnan(actual.iloc[2])
    assert actual.iloc[3] == pytest.approx(2)
    assert actual.iloc[4] == pytest.approx(8 / 3)
    assert actual.iloc[5] == pytest.approx(40 / 9)


def test_indicators_closed_candle_and_shift(cfg):
    now = 2_000_000_100
    bars = bars_for(now)
    result = lb.indicators(bars, cfg, "1h", now)
    assert len(result) == 199
    changed = copy.deepcopy(bars)
    changed[-1] = [changed[-1][0], 1, 10**9, 0.01, 10**8, 1000]
    pd.testing.assert_frame_equal(result, lb.indicators(changed, cfg, "1h", now))
    t, d = len(result) - 1, cfg["ichimoku_params"]["displacement"]
    expected_kijun = (result.high.iloc[t-59:t+1].max() + result.low.iloc[t-59:t+1].min()) / 2
    assert result.kijun.iloc[t] == pytest.approx(expected_kijun)
    assert result.senkou_a_curr.iloc[t] == result.senkou_a_future.iloc[t-d]
    assert result.senkou_b_curr.iloc[t] == result.senkou_b_future.iloc[t-d]
    assert result.timestamp.iloc[-1] + 3600000 <= now * 1000


def test_rsi_atr_against_independent_loop(cfg):
    now = 2_000_000_100
    df = lb.indicators(bars_for(now), cfg, "1h", now)
    n = 14
    differences = np.diff(df.close.to_numpy())
    gain = np.maximum(differences[:n], 0).mean()
    loss = np.maximum(-differences[:n], 0).mean()
    for delta in differences[n:]:
        gain = (gain * 13 + max(delta, 0)) / 14
        loss = (loss * 13 + max(-delta, 0)) / 14
    assert df.rsi.iloc[-1] == pytest.approx(100 - 100 / (1 + gain / loss))
    ranges = [df.high.iloc[0] - df.low.iloc[0]]
    for k in range(1, len(df)):
        ranges.append(max(df.high.iloc[k]-df.low.iloc[k], abs(df.high.iloc[k]-df.close.iloc[k-1]), abs(df.low.iloc[k]-df.close.iloc[k-1])))
    atr = sum(ranges[:14]) / 14
    for tr in ranges[14:]:
        atr = (atr * 13 + tr) / 14
    assert df.atr.iloc[-1] == pytest.approx(atr)


@pytest.mark.parametrize("delta,expected", [(0, 50), (0.2, 100), (-0.2, 0)])
def test_rsi_zero_loss_and_flat(cfg, delta, expected):
    now = 2_000_000_100
    bars = bars_for(now, flat=True)
    for index, bar in enumerate(bars):
        center = 100 + delta * index
        bar[1:5] = [center, center + .5, center - .5, center]
    result = lb.indicators(bars, cfg, "1h", now)
    assert result.rsi.iloc[-1] == expected


@pytest.mark.parametrize("mutation", ["gap", "duplicate", "nan", "geometry", "negative"])
def test_bad_candles_rejected(cfg, mutation):
    bars = bars_for(2_000_000_100)
    if mutation == "gap":
        del bars[5]
    elif mutation == "duplicate":
        bars[5][0] = bars[4][0]
    elif mutation == "nan":
        bars[5][1] = np.nan
    elif mutation == "geometry":
        bars[5][2] = 1
    else:
        bars[5][4] = -1
    with pytest.raises(ValueError):
        lb.indicators(bars, cfg, "1h", 2_000_000_100)


@pytest.mark.parametrize("side", ["long", "short"])
def test_entry_signal_h2_l2_and_anatomy(cfg, side):
    cfg["al_brooks_filters"]["enable_barb_wire_filter"] = False
    df = signal_frame(side)
    assert lb.entry_signal(df, side, cfg)
    # Remove all prior H1/L1 attempts while retaining a valid signal bar.
    df.loc[:len(df)-2, "high"] = 11
    df.loc[:len(df)-2, "low"] = 9
    assert not lb.entry_signal(df, side, cfg)
    cfg["al_brooks_filters"]["require_h2_l2_pullback"] = False
    assert lb.entry_signal(df, side, cfg)
    df.loc[len(df)-1, "close"] = 10
    assert not lb.entry_signal(df, side, cfg)


def test_barb_wire_filter(cfg):
    df = signal_frame()
    assert not lb.entry_signal(df, "long", cfg)
    cfg["al_brooks_filters"]["enable_barb_wire_filter"] = False
    assert lb.entry_signal(df, "long", cfg)


@pytest.mark.parametrize("side", ["long", "short"])
def test_regime_and_chikou(cfg, side):
    df = pd.DataFrame([dict(close=100, high=101, low=99, tenkan=100, kijun=100,
        senkou_a_future=102, senkou_b_future=98, kumo_top=102, kumo_bottom=98, atr=2)] * 100)
    if side == "long":
        df.loc[99, ["close", "tenkan", "kijun"]] = [110, 108, 105]
    else:
        df.loc[99, ["close", "tenkan", "kijun", "senkou_a_future", "senkou_b_future"]] = [90, 92, 95, 98, 102]
    assert lb.regime(df, cfg) == side
    df.loc[69, "high" if side == "long" else "low"] = 120 if side == "long" else 80
    assert lb.regime(df, cfg) is None


@pytest.mark.parametrize("side", ["long", "short"])
def test_fee_adjusted_size_and_contract_units(cfg, side):
    data = FakeData()
    data.contract_size = .1
    p = lb.size_position(data, "BTC/USDT:USDT", side, signal_frame(side).iloc[-1], 10000, cfg, "1h")
    assert p is not None
    risk = p["qty"] * p["contract_size"] * (abs(p["entry_price"]-p["initial_sl"]) + p["entry_price"] * p["fee_rate"])
    assert risk <= 50 + 1e-8
    assert p["qty"] * p["contract_size"] * p["entry_price"] <= 5000
    direction = 1 if side == "long" else -1
    assert direction * (p["tp1_price"]-p["entry_price"]) == pytest.approx(1.5*abs(p["entry_price"]-p["initial_sl"]))


@pytest.mark.parametrize("side", ["long", "short"])
def test_complete_state_machine(system, side):
    p = setup_position(system, side=side)
    symbol = p["symbol"]
    system.data.prices[symbol] = 100
    system.watchdog(now=1_900_000_000)
    assert system.db.position(symbol)["state"] == lb.INITIAL
    assert system.db.history_summary(1_900_000_000) == (0, 0)
    system.data.prices[symbol] = 116 if side == "long" else 84
    system.watchdog(now=1_900_000_001)
    remainder = system.db.position(symbol)
    assert remainder["state"] == lb.TRAILING
    assert remainder["qty"] == 1
    assert remainder["active_sl"] == 100
    first, count = system.db.history_summary(1_900_000_001)
    assert count == 1
    assert first == pytest.approx(lb.net_pnl(p, system.data.prices[symbol], 1))
    system.data.prices[symbol] = 99 if side == "long" else 101
    system.watchdog(now=1_900_000_002)
    assert system.db.position(symbol) is None
    assert system.db.history_summary(1_900_000_002)[1] == 2


@pytest.mark.parametrize("reason", ["expired", "invalidated", "disabled"])
def test_pending_cancel(system, reason):
    p = setup_position(system)
    now = 1_900_000_000
    if reason == "expired":
        now = p["expiry_ts"]
    elif reason == "invalidated":
        system.data.prices[p["symbol"]] = 89
    else:
        system.config.stop_entries()
    system.watchdog(now)
    assert system.db.positions() == []
    assert system.db.history_summary(now)[1] == 0


def test_gapped_entry_resizes_risk_and_tp(system):
    p = setup_position(system)
    system.data.prices[p["symbol"]] = 150
    system.watchdog(1_900_000_000)
    actual = system.db.position(p["symbol"])
    assert actual["entry_price"] == 150
    assert actual["qty"] < 1
    assert actual["qty"] * (60 + 150 * .0012) <= 50
    assert actual["tp1_price"] == 240


def test_fill_respects_hot_reloaded_risk_limit(system):
    p = setup_position(system)
    cfg = system.config.read()
    cfg["risk_and_exit"]["risk_per_trade_pct"] = .001
    system.config.write(cfg)
    system.watchdog(1_900_000_000)
    actual = system.db.position(p["symbol"])
    assert actual["qty"] * (10 + 100 * .0012) <= 10 + 1e-8


def test_invalid_immediate_fill_is_cancelled(system):
    p = setup_position(system)
    assert not system._activate(p, 80)
    assert system.db.positions() == []
    assert system.db.history_summary(time.time())[1] == 0


def test_tp1_dust_closes_full_position(system):
    p = setup_position(system, state=lb.INITIAL)
    system.data.minimum = 1.5
    system.data.prices[p["symbol"]] = 116
    system.watchdog(1_900_000_000)
    assert system.db.positions() == []
    with system.db.connect() as db:
        row = db.execute("SELECT * FROM trade_history").fetchone()
        assert row["qty"] == 2
        assert row["reason"] == "tp1_full_small_position"


def test_duplicate_close_serialized(system):
    setup_position(system, state=lb.INITIAL)
    def close():
        try:
            return system.close_symbol("BTC/USDT:USDT")
        except KeyError:
            return "already_closed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: close(), range(2)))
    assert results.count("already_closed") == 1
    assert system.db.history_summary(time.time())[1] == 1


def test_two_processes_cannot_double_close(system):
    setup_position(system, state=lb.INITIAL)
    context = multiprocessing.get_context("fork")
    ready, results = context.Event(), context.Queue()
    def close_worker():
        ready.wait(timeout=5)
        try:
            system.close_symbol("BTC/USDT:USDT")
            results.put("closed")
        except KeyError:
            results.put("missing")
    processes = [context.Process(target=close_worker) for _ in range(2)]
    for process in processes:
        process.start()
    ready.set()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join()
        assert process.exitcode == 0
    assert sorted([results.get(timeout=2), results.get(timeout=2)]) == ["closed", "missing"]
    assert system.db.history_summary(time.time())[1] == 1


def test_panic_closes_and_cancels(system):
    setup_position(system, state=lb.INITIAL)
    setup_position(system, symbol="ETH/USDT:USDT")
    result = system.close_all()
    assert len(result["results"]) == 2
    assert not result["errors"]
    assert system.db.positions() == []
    assert system.config.read()["bot_control"]["auto_trade_enabled"] is False
    assert system.db.history_summary(time.time())[1] == 1


def test_panic_preserves_failed_close_and_stops_entries(system):
    setup_position(system, state=lb.INITIAL)
    system.data.fail.add("BTC/USDT:USDT")
    result = system.close_all()
    assert len(result["errors"]) == 1
    assert result["remaining_positions"] == 1
    assert not system.config.read()["bot_control"]["auto_trade_enabled"]
    assert system.db.history_summary(time.time())[1] == 0


def test_live_row_never_deleted_or_paper_closed(system):
    setup_position(system, state=lb.INITIAL)
    with system.db.connect() as db:
        db.execute("UPDATE positions SET dry_run=0")
    with pytest.raises(lb.LiveUnavailable):
        system.close_symbol("BTC/USDT:USDT")
    system.data.prices["BTC/USDT:USDT"] = 80
    system.watchdog(1_900_000_000)
    assert len(system.db.positions()) == 1
    assert system.db.history_summary(time.time())[1] == 0


def test_bad_config_does_not_disable_existing_stop(system):
    setup_position(system, state=lb.INITIAL)
    system.config.path.write_text("{")
    system.data.prices["BTC/USDT:USDT"] = 89
    system.watchdog(1_900_000_000)
    assert not system.db.positions()


def test_pending_rechecks_daily_circuit_breaker(system):
    setup_position(system)
    now = 1_900_000_000
    with system.db.connect() as db:
        db.execute("INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason) "
                   "VALUES('X','long',-300,?,1,100,80,'test')", (now,))
    system.watchdog(now)
    assert not system.db.positions()


def prepare_scan(system, cfg, now):
    for symbol in cfg["symbols"]:
        for tf in ("1h", "4h"):
            system.data.bars[(symbol, tf)] = bars_for(now, tf)


def test_scanner_ranking_slots_and_no_duplicate_candle(system, cfg, monkeypatch):
    now = 1_900_000_003
    prepare_scan(system, cfg, now)
    monkeypatch.setattr(lb, "regime", lambda df, c: "long")
    monkeypatch.setattr(lb, "entry_signal", lambda df, side, c: True)
    ranks = {symbol: score for symbol, score in zip(cfg["symbols"], [6, 5, 4, 3, 2, 1])}
    original = lb.indicators
    # Independent candidates get distinct RSI proximity to exercise ranking.
    for symbol, rank in ranks.items():
        system.data.bars[(symbol, "1h")][0][5] = rank
    def distinct_rsi(bars, c, tf, stamp):
        result = original(bars, c, tf, stamp)
        result.loc[len(result)-1, "rsi"] = 55 + bars[0][5]
        return result
    monkeypatch.setattr(lb, "indicators", distinct_rsi)
    system.scan(now)
    assert {p["symbol"] for p in system.db.positions()} == set(cfg["symbols"][-3:])
    for p in system.db.positions():
        system.close_symbol(p["symbol"])
    system.scan(now + 1)
    assert system.db.positions() == []


def test_stale_candle_blocks_entries(system, cfg, monkeypatch):
    now = 1_900_000_003
    prepare_scan(system, cfg, now - 14400)
    monkeypatch.setattr(lb, "regime", lambda df, c: "long")
    monkeypatch.setattr(lb, "entry_signal", lambda df, side, c: True)
    assert system.scan(now) is False
    assert not system.db.positions()
    assert "Stale" in system.db.runtime_all()["last_error"]


def test_scanner_immediate_entry_and_daily_breaker(system, cfg, monkeypatch):
    now = 1_900_000_003
    cfg["al_brooks_filters"]["require_signal_bar_breakout"] = False
    system.config.write(cfg)
    prepare_scan(system, cfg, now)
    for symbol in cfg["symbols"]:
        system.data.prices[symbol] = 130
    monkeypatch.setattr(lb, "regime", lambda df, c: "long")
    monkeypatch.setattr(lb, "entry_signal", lambda df, side, c: True)
    assert system.scan(now)
    assert len(system.db.positions()) == 3
    assert all(p["state"] == lb.INITIAL and p["entry_price"] == 130 for p in system.db.positions())
    system.close_all(disable=False)
    with system.db.connect() as db:
        db.execute("INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason) "
                   "VALUES('X','long',-400,?,1,100,80,'test')", (now,))
    later = now + 3600
    prepare_scan(system, cfg, later)
    system.scan(later)
    assert not system.db.positions()


@pytest.mark.parametrize("side,broken", [("long", False), ("short", False), ("long", True), ("short", True)])
def test_kijun_trailing_ratchet_and_break(system, cfg, monkeypatch, side, broken):
    c = system.config.read()
    c["bot_control"]["auto_trade_enabled"] = False
    system.config.write(c)
    p = setup_position(system, side=side, state=lb.TRAILING)
    now = 1_900_000_003
    system.data.bars[(p["symbol"], "1h")] = bars_for(now)
    original = lb.indicators
    def frame(bars, c, tf, stamp):
        df = original(bars, c, tf, stamp)
        if side == "long":
            kijun, close = 105, 104 if broken else 106
        else:
            kijun, close = 95, 96 if broken else 94
        df.loc[len(df)-1, ["kijun", "close", "atr"]] = [kijun, close, 2]
        return df
    monkeypatch.setattr(lb, "indicators", frame)
    system.scan(now)
    if broken:
        assert system.db.positions() == []
        assert system.db.history_summary(now)[1] == 1
    else:
        updated = system.db.position(p["symbol"])
        assert updated["active_sl"] == pytest.approx(104.6 if side == "long" else 95.4)
        system.scan(now)
        assert system.db.position(p["symbol"])["active_sl"] == updated["active_sl"]


@pytest.fixture
def client(system, monkeypatch):
    monkeypatch.setenv("BOT_PIN", "test-pin-9384")
    with TestClient(create_app(system)) as api:
        yield api


AUTH = {"X-Bot-Pin": "test-pin-9384"}


def test_api_auth_and_public_html(client):
    assert client.get("/").status_code == 200
    assert 'dir="rtl"' in client.get("/").text
    for route in ("/api/status", "/api/config"):
        assert client.get(route).status_code == 401
        assert client.get(route, headers={"X-Bot-Pin": "wrong"}).status_code == 401
    assert client.post("/api/positions/close-all", json={}).status_code == 401


def test_status_pending_has_zero_pnl(client, system):
    setup_position(system)
    response = client.get("/api/status", headers=AUTH)
    assert response.status_code == 200
    status = response.json()
    assert status["positions"][0]["current_r"] == 0
    assert status["positions"][0]["unrealized_pnl_usd"] == 0
    assert status["total_unrealized_pnl"] == 0
    assert status["live_execution_supported"] is False
    assert response.headers["cache-control"] == "no-store"


def test_status_failed_price_not_reported_as_zero(client, system):
    setup_position(system, state=lb.INITIAL)
    system.data.fail.add("BTC/USDT:USDT")
    result = client.get("/api/status", headers=AUTH).json()
    assert result["total_unrealized_pnl"] is None
    assert result["positions"][0]["live_price"] is None
    assert result["positions"][0]["unrealized_pnl_usd"] is None


def test_config_etag_validation_and_pending_cancel(client, system):
    setup_position(system)
    result = client.get("/api/config", headers=AUTH)
    cfg = result.json()
    tag = result.headers["etag"]
    cfg["bot_control"]["auto_trade_enabled"] = False
    response = client.put("/api/config", headers={**AUTH, "If-Match": tag}, json=cfg)
    assert response.status_code == 200
    assert system.db.positions() == []
    assert client.put("/api/config", headers={**AUTH, "If-Match": tag}, json=cfg).status_code == 409
    cfg["bot_control"]["dry_run_mode"] = False
    assert client.put("/api/config", headers=AUTH, json=cfg).status_code == 422
    assert system.config.read()["bot_control"]["dry_run_mode"] is True


def test_close_api_and_missing_position(client, system):
    setup_position(system)
    result = client.post("/api/positions/close", headers=AUTH, json={"symbol": "BTC/USDT:USDT"})
    assert result.json()["result"] == "cancelled"
    assert client.post("/api/positions/close", headers=AUTH, json={"symbol": "BTC/USDT:USDT"}).status_code == 404
    assert client.post("/api/positions/close", headers=AUTH, json={"symbol": "BTC/USDT:USDT", "extra": True}).status_code == 422


def test_panic_api(client, system):
    setup_position(system, state=lb.INITIAL)
    response = client.post("/api/positions/close-all", headers=AUTH, json={"disable_auto_trade": True})
    assert response.status_code == 200
    assert response.json()["remaining_positions"] == 0
    assert response.json()["auto_trade_disabled"] is True


def test_demo_never_uses_exchange_network(monkeypatch):
    monkeypatch.setenv("PAPER_DATA_MODE", "demo")
    data = lb.MarketData()
    def forbidden(*args, **kwargs):
        pytest.fail("demo mode must not call the exchange")
    monkeypatch.setattr(data.exchange, "load_markets", forbidden)
    monkeypatch.setattr(data.exchange, "fetch_ticker", forbidden)
    monkeypatch.setattr(data.exchange, "fetch_ohlcv", forbidden)
    assert data.price("BTC/USDT:USDT") > 0
    assert len(data.candles("BTC/USDT:USDT", "1h", 200)) == 200
    assert data.precision("BTC/USDT:USDT", .123456789) == .123456


def test_csv_futures_does_not_call_spot_ohlcv(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_DATA_MODE", "csv-lbank")
    monkeypatch.setenv("OHLCV_DIR", str(tmp_path))
    data = lb.MarketData()
    monkeypatch.setattr(data, "market", lambda symbol: {"swap": True})
    def forbidden(*args, **kwargs):
        pytest.fail("futures CSV must never route to spot OHLCV")
    monkeypatch.setattr(data.exchange, "fetch_ohlcv", forbidden)
    with pytest.raises(ValueError, match="Verified futures candles"):
        data.candles("BTC/USDT:USDT", "1h", 200)
    pd.DataFrame(bars_for(1_900_000_003), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_csv(tmp_path / "BTC_USDT_USDT_1h.csv", index=False)
    assert len(data.candles("BTC/USDT:USDT", "1h", 200)) == 200


def test_compose_shared_directory_and_local_bind():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert set(services) == {"lbank-bot", "lbank-dashboard"}   # C3 runs inside lbank-bot (own thread, config and DB)
    for name, service in services.items():
        assert service["volumes"] == ["./runtime:/app/runtime"]
        assert service["restart"] == "unless-stopped"
        assert service["environment"]["BOT_CONFIG"] == "/app/runtime/config.json"
    assert services["lbank-bot"]["environment"]["C3_CONFIG"] == "/app/runtime/c3_config.json"
    assert services["lbank-bot"]["environment"]["C3_DB"] == "/app/runtime/c3_sleeve.db"
    assert services["lbank-dashboard"]["ports"] == ["127.0.0.1:8000:8000"]
