"""Unit tests for the experimental fourth 15m/1h PAPER sleeve and independent collector."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import scalp_sleeve as S
import scalp_candles as K


ROOT = Path(__file__).resolve().parents[1]


def conf(**kwargs):
    obj = json.loads((ROOT / "scalp_config.json").read_text())
    obj.update(kwargs)
    return S.validate(obj)


def bars(period, n, last_open):
    """Continuous candles ending with one deliberately FORMING bar."""
    first = last_open - (n - 1) * period * 1000
    return [
        [first + i * period * 1000, 100.0, 100.6, 99.4, 100.2, 0.0]
        for i in range(n)
    ]


def test_disabled_by_default_and_paper_guard():
    c = conf()
    assert c["enabled"] is False
    assert c["dry_run_mode"] is True
    assert c["timeframe"] == "15m" and c["trend_timeframe"] == "1h"
    with pytest.raises(ValueError):
        conf(dry_run_mode=False)
    with pytest.raises(ValueError):
        conf(timeframe="5m")
    with pytest.raises(ValueError):
        conf(risk_per_trade_pct=0.01)
    with pytest.raises(ValueError):
        conf(max_open_positions=10)
    with pytest.raises(ValueError):
        conf(ema_trend_slow=300, trend_candle_fetch_limit=350)
    with pytest.raises(ValueError):
        S.validate(dict(c, unknown=True))


def test_features_never_expose_forming_bar_or_gaps():
    c = conf()
    last = 1_700_000_000 // 900 * 900 * 1000
    rows = bars(900, 190, last)
    df = S.features(rows, last / 1000 + 4, 900, c)
    assert int(df.timestamp.iloc[-1]) == last - 900 * 1000
    assert len(df) == 189
    gap = rows[:]
    gap.pop(75)
    with pytest.raises(ValueError, match="noncontiguous"):
        S.features(gap, last / 1000 + 4, 900, c)


def test_signal_uses_prior_highs_and_closed_1h_trend():
    c = conf()
    n = 40
    df = pd.DataFrame(
        dict(high=[101.0] * n, low=[99.0] * n,
             close=[100.0] * n, atr=[1.0] * n,
             rsi=[60.0] * n, ema_entry=[100.0] * n)
    )
    df.loc[n - 2, "ema_entry"] = 100.0
    df.loc[n - 1, ["close", "high", "ema_entry"]] = [102.0, 103.0, 101.0]
    trend = pd.DataFrame(
        dict(ema_fast=[105.0] * 350, ema_slow=[100.0] * 350, close=[107.0] * 350)
    )
    assert S.signal(df, trend, c) == "long"
    trend.loc[349, "ema_fast"] = 95.0
    assert S.signal(df, trend, c) is None
    trend.loc[349, "ema_fast"] = 105.0
    df.loc[39, "close"] = 100.5
    assert S.signal(df, trend, c) is None


class Data:
    def __init__(self):
        self.px = 100.0

    def price(self, symbol):
        return self.px

    def market(self, symbol):
        return {"contractSize": 1.0}

    def precision(self, symbol, quantity):
        return round(quantity, 6)

    def tradable(self, symbol, qty, px):
        return qty >= 0.001


class Account:
    def __init__(self, lock):
        self.lock_path = lock
        self.engine = SimpleNamespace(config=SimpleNamespace(
            read=lambda: {"portfolio_risk": {"shared_c3_account": True}}))
        self.margin = 1000.0

    def equity(self):
        return 10000.0

    def available_margin(self, *args, **kwargs):
        return self.margin


def test_entry_capped_by_shared_margin_and_only_one_per_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(S.bot.license_access, "entries_allowed", lambda _: True)
    c = conf(enabled=True)
    store = S.c3.Store(tmp_path / "chabok.db")
    account = Account(tmp_path / "shared.lock")
    data = Data()
    sleeve = S.Sleeve(c, store, data, shared_account=account)
    candle = pd.Series({"close": 100.0, "atr": 1.0, "timestamp": 1700000100000})
    assert sleeve.open(c["symbols"][0], "long", candle, 1700001000)
    pos = store.positions()
    assert len(pos) == 1
    assert pos[0]["entry"] == 100
    assert pos[0]["stop"] == 98
    assert pos[0]["qty"] * 100 <= 10000 * c["max_notional_pct"] + 0.01
    assert pos[0]["qty"] * 100 / c["isolated_leverage"] <= account.margin + 0.01
    assert sleeve.open(c["symbols"][0], "long", candle, 1700001001) is None
    data.px = 97
    sleeve.watchdog(1700001100)
    assert not store.positions()
    with store.db() as db:
        row = db.execute("SELECT reason,pnl FROM trades").fetchone()
    assert row[0] == "stop" and row[1] < 0


def test_paper_runner_refuses_entries_without_shared_account(tmp_path):
    store = S.c3.Store(tmp_path / "chabok.db")
    sl = S.Sleeve(conf(enabled=True), store, Data())
    candle = pd.Series({"close": 100.0, "atr": 1.0, "timestamp": 1700000100000})
    assert sl.open(conf()["symbols"][0], "long", candle, 1700001000) is None
    assert not store.positions()


def test_collector_writes_separate_timeframes_and_zero_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "OUT", tmp_path)
    collector = K.Collector(["BTC/USDT:USDT"])
    start = 1_700_000_000
    collector.step({"BTCUSDT": 100.0}, start)
    collector.step({"BTCUSDT": 104.0}, start + 10)
    collector.flush_all(start + 11)
    assert not list(tmp_path.glob("*_4h.csv"))
    for tf in ("15m", "1h"):
        rows = K.read_rows(K.csv_path("BTC/USDT:USDT", tf))
        assert len(rows) == 1
        assert rows[0][5] == 0.0
        assert rows[0][2] >= rows[0][3]
    collector.step({"BTCUSDT": 108.0}, start + 3600)
    collector.flush_all(start + 3601)
    for tf in ("15m", "1h"):
        rows = K.read_rows(K.csv_path("BTC/USDT:USDT", tf))
        assert len(rows) == 2


def test_disabled_scan_records_fresh_closed_candles_but_never_opens(tmp_path):
    config = conf()
    now_s = 1_700_006_400  # align to 1h boundary explicitly
    now_s = (now_s // 3600) * 3600 + 900 + 4
    tf15last = (now_s // 900) * 900 * 1000
    tf1last = (now_s // 3600) * 3600 * 1000
    r15 = bars(900, 300, tf15last)
    r1h = bars(3600, 350, tf1last)
    data = Data()
    data.candles = lambda symbol, tf, limit: (r15 if tf == "15m" else r1h)[-limit:]
    st = S.c3.Store(tmp_path / "st.db")
    sl = S.Sleeve(config, st, data)
    assert sl.scan(now_s)
    assert sl.scan(now_s + 20)
    with st.db() as db:
        assert db.execute("SELECT COUNT(*) FROM scanned").fetchone()[0] == 2
    assert not st.positions()
