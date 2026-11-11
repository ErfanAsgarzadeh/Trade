"""Momentum-rank sizing (momentum.py): rank arithmetic, safe fallbacks, candle alignment, research parity, bot sizing."""
import json
from pathlib import Path
import numpy as np
import pytest
import momentum as M
import lbank_bot as lb
import c3_sleeve as C
from test_system import cfg, system, bars_for

DAY = 86400
NOW = 1_800_000_000 // DAY * DAY + 5 * 3600 + 3      # 05:00:03 UTC on some day


class Candles:
    """data.candles() stand-in: per symbol a 4h series (open time ms) whose close is `start` before the 30-day boundary
    and `end` from there on."""
    def __init__(self, moves, missing=()):
        self.moves, self.missing, self.calls = moves, set(missing), []

    def candles(self, s, tf, limit):
        self.calls.append((s, tf, limit))
        if s in self.missing:
            raise ValueError("no candles")
        a, b = self.moves[s]
        day_end = NOW // DAY * DAY;first = day_end - 31 * DAY;rows = []
        for t in range(first, NOW // (4 * 3600) * 4 * 3600 + 1, 4 * 3600):   # last row = the forming candle
            close = a if t + 4 * 3600 <= day_end - 30 * DAY else b
            rows.append([t * 1000, close, close, close, close, 1.])
        return rows[-limit:]


@pytest.fixture(autouse=True)
def fresh_cache():
    M._cache.clear();yield;M._cache.clear()


def moves(n=12):
    return {f"C{i}/USDT:USDT": (100., 100. * (1 + i / 100)) for i in range(n)}   # C0 weakest ... C11 strongest


def test_rank_and_multiplier_follow_the_research_formula(monkeypatch):
    d = Candles(moves());syms = list(d.moves)
    r = M.ranks(d, NOW, syms)
    assert r["C11/USDT:USDT"] == pytest.approx(1.0) and r["C0/USDT:USDT"] == pytest.approx(1 / 12)
    assert all(lim >= 6 * 30 + 1 for _, tf, lim in d.calls) and {tf for _, tf, _ in d.calls} == {"4h"}
    monkeypatch.setattr(M, "universe", lambda: syms)
    assert M.multiplier(d, "C11/USDT:USDT", "long", NOW) == pytest.approx(1.5)
    assert M.multiplier(d, "C11/USDT:USDT", "short", NOW) == pytest.approx(0.5)
    assert M.multiplier(d, "C0/USDT:USDT", "long", NOW) == pytest.approx(0.5 + 1 / 12)
    assert M.multiplier(d, "C0/USDT:USDT", "short", NOW) == pytest.approx(1.5 - 1 / 12)
    assert M.multiplier(d, "C5/USDT:USDT", "long", NOW, enabled=False) == 1.0
    n = len(d.calls);M.multiplier(d, "C3/USDT:USDT", "long", NOW + 3600);assert len(d.calls) == n   # cached for the UTC day


def test_ties_are_averaged_like_pandas():
    mv = {f"T{i}": (100., 110.) for i in range(4)} | {f"U{i}": (100., 90.) for i in range(8)}
    r = M.ranks(Candles(mv), NOW, list(mv))
    assert r["T0"] == pytest.approx((8 + 2.5) / 12) and r["U0"] == pytest.approx(4.5 / 12)


def test_safe_fallbacks(monkeypatch):
    mv = moves(12);syms = list(mv)
    monkeypatch.setattr(M, "universe", lambda: syms)
    few = Candles(mv, missing=syms[:4])                         # only 8 coins with history: no change at all
    assert M.multiplier(few, syms[-1], "long", NOW) == 1.0
    M._cache.clear()
    d = Candles(mv, missing=[syms[0]])                          # the coin itself has no history: no change
    assert M.multiplier(d, syms[0], "long", NOW) == 1.0 and M.multiplier(d, "OTHER/USDT:USDT", "long", NOW) == 1.0


def test_uses_the_close_of_the_candle_ending_at_utc_midnight():
    rows = [[(10 * DAY - 4 * 3600) * 1000, 1, 1, 1, 7., 1], [(10 * DAY) * 1000, 1, 1, 1, 9., 1]]
    assert M._close_at(rows, 10 * DAY) == 7. and M._close_at(rows, 10 * DAY + 4 * 3600) == 9. and M._close_at(rows, 9 * DAY) is None


def test_default_universe_is_the_three_bots_symbols():
    u = M.universe();here = Path(__file__).parents[1]
    want = set()
    for f in ("config.json", "c3_config.json", "pa_config.json"):want |= set(json.loads((here / f).read_text())["symbols"])
    assert set(u) == want and len(u) == 35


def test_matches_research_ranks_when_data_is_present():
    """Same rank as high_cagr/ideas/scorer/data.mom on the prepared 1m data (35 coins)."""
    root = Path(__file__).parents[2]
    prep = root / "high_cagr/prepared_stage2"
    if not (prep / "LINKUSDT/prices.npy").exists():pytest.skip("research data not restored")
    import sys;sys.path.insert(0, str(root))
    from high_cagr.ideas.scorer import data as D
    start = 1633392000 * 1000      # rs.START
    class Prepared:
        def candles(self, s, tf, limit):
            sym = s.split("/")[0] + "USDT";sym = "1000SHIBUSDT" if sym == "SHIBUSDT" else sym
            P = np.load(prep / sym / "prices.npy", mmap_mode="r");day = (NOW_R * 1000 - start) // 60000
            out = []
            for k in range(limit, 0, -1):
                m = day // 240 * 240 - k * 240
                out.append([start + m * 60000, 0, 0, 0, float(P[m + 239, 3]), 0])
            return out
    for NOW_R in (1700000000, 1750000000, 1780000000):
        minute = (NOW_R * 1000 - start) // 60000;M._cache.clear()
        for s in ("LINK/USDT:USDT", "BTC/USDT:USDT", "SHIB/USDT:USDT", "AAVE/USDT:USDT"):
            sym = s.split("/")[0] + "USDT";sym = "1000SHIBUSDT" if sym == "SHIBUSDT" else sym
            for side, sgn in (("long", 1), ("short", -1)):
                assert M.multiplier(Prepared(), s, side, NOW_R) == pytest.approx(0.5 + D.mom(sym, sgn, minute), abs=1e-9)


def test_mojsavar_entry_size_scales_with_the_multiplier(tmp_path, monkeypatch):
    import test_c3_sleeve as T
    conf = T.cfg(skip_weekend=False, confirm_bars=0, momentum_sizing_enabled=True);c = T.uptrend_with_dip()
    sizes = {}
    for mult in (1.0, 1.5, 0.5):
        rows, now, side, df = T.find_signal_end(c, conf);st = C.Store(tmp_path / f"c3_{mult}.db")
        sl = C.Sleeve({**conf, "max_notional_pct": 1.0}, st, T.FakeData(rows, float(c[-1])));sl.c["symbols"] = ["AVAX/USDT:USDT"]
        monkeypatch.setattr(C.momentum, "multiplier", lambda data, s, sd, n, en, m=mult: m if en else 1.0)
        sl.scan(now);sizes[mult] = st.positions()[0]["qty"]
    assert sizes[1.5] == pytest.approx(1.5 * sizes[1.0], rel=1e-4) and sizes[0.5] == pytest.approx(0.5 * sizes[1.0], rel=1e-4)


def run_main(system, monkeypatch, mult, enabled=True):
    c = lb.validate_config(json.loads((Path(__file__).parents[1] / "config.json").read_text()))
    c["symbols"] = ["ETH/USDT:USDT"];c["risk_and_exit"]["max_open_positions"] = 2
    c["strategy_settings"].update(momentum_sizing_enabled=enabled, late_entry_filter_enabled=False, atr_regime_filter_enabled=False,
                                  btc_regime_filter_enabled=False, stop_width_filter_enabled=False)
    system.config.write(c);now = 1_800_000_003
    bars = bars_for(now, "4h", n=300);bars[-2][4] = 110;bars[-2][2] = max(bars[-2][2], 111);bars[-2][3] = min(bars[-2][3], 109)
    system.data.bars["ETH/USDT:USDT", "4h"] = bars;system.data.prices["ETH/USDT:USDT"] = 110.
    original = lb.indicators
    def indicators(raw, cfg_, tf, when):
        f = original(raw, cfg_, tf, when);last = len(f) - 1;f.loc[last, ["kijun", "donchian_high_10", "donchian_low_10", "atr", "kumo_top", "kumo_bottom"]] = [90, 100, 85, 2, 100, 85];return f
    monkeypatch.setattr(lb, "indicators", indicators);monkeypatch.setattr(lb, "regime", lambda df, c: "long");monkeypatch.setattr(lb, "entry_signal", lambda *a: True)
    seen = []
    def fake(data, s, side, n, en):
        seen.append((s, side, en));return mult if en else 1.0
    monkeypatch.setattr(lb.momentum, "multiplier", fake)
    system.scan(now);return system.db.positions()[0], seen


def test_shahin_entry_risk_scales_with_the_multiplier(system, monkeypatch):
    base, seen = run_main(system, monkeypatch, 1.0)
    assert seen == [("ETH/USDT:USDT", "long", True)]
    with system.db.connect() as db:db.execute("DELETE FROM positions");db.execute("DELETE FROM scanned_candles")
    big, _ = run_main(system, monkeypatch, 1.4)
    assert big["risk_budget"] == pytest.approx(1.4 * base["risk_budget"], rel=1e-6)
    with system.db.connect() as db:db.execute("DELETE FROM positions");db.execute("DELETE FROM scanned_candles")
    off, seen = run_main(system, monkeypatch, 1.4, enabled=False)
    assert seen[-1][2] is False and off["risk_budget"] == pytest.approx(base["risk_budget"], rel=1e-6)


def test_switch_is_on_by_default_everywhere():
    here = Path(__file__).parents[1]
    assert lb.validate_config(json.loads((here / "config.json").read_text()))["strategy_settings"]["momentum_sizing_enabled"] is True
    old = json.loads((here / "config.json").read_text());old["strategy_settings"].pop("momentum_sizing_enabled")
    assert lb.validate_config(old)["strategy_settings"]["momentum_sizing_enabled"] is True          # existing runtime configs too
    import pa_sleeve as P
    for mod, f in ((C, "c3_config.json"), (P, "pa_config.json")):
        c = json.loads((here / f).read_text());assert mod.validate(c)["momentum_sizing_enabled"] is True
        c.pop("momentum_sizing_enabled");assert mod.validate(c)["momentum_sizing_enabled"] is True
        with pytest.raises(ValueError):mod.validate({**c, "momentum_sizing_enabled": 1})


def test_insufficient_history_is_retried_at_most_every_15_minutes(monkeypatch):
    mv = moves(12);syms = list(mv);monkeypatch.setattr(M, "universe", lambda: syms)
    d = Candles(mv, missing=syms)
    assert M.multiplier(d, syms[0], "long", NOW) == 1.0;n = len(d.calls)
    assert M.multiplier(d, syms[0], "long", NOW + 600) == 1.0 and len(d.calls) == n        # not re-fetched within 15 minutes
    d.missing = set()
    assert M.multiplier(d, syms[-1], "long", NOW + 901) == pytest.approx(1.5)             # retried after 15 minutes


def test_incomplete_ranks_after_midnight_are_provisional(monkeypatch):
    """At the UTC midnight close the feed publishes coins over a few minutes: ranks from a partial set are not kept all day."""
    mv = moves(12) | {f"D{i}/USDT:USDT": (100., 100. * (1 + (i + 20) / 100)) for i in range(2)};syms = list(mv)
    monkeypatch.setattr(M, "universe", lambda: syms)
    d = Candles(mv, missing=syms[-2:])                          # the two strongest coins not published yet: 12/14
    first = M.multiplier(d, "C11/USDT:USDT", "long", NOW);assert first == pytest.approx(1.5)
    n = len(d.calls);M.multiplier(d, "C11/USDT:USDT", "long", NOW + 600);assert len(d.calls) == n
    d.missing = set()
    assert M.multiplier(d, "C11/USDT:USDT", "long", NOW + 901) == pytest.approx(0.5 + 12 / 14)     # recomputed on the full set
    n = len(d.calls);M.multiplier(d, "C11/USDT:USDT", "long", NOW + 3 * 3600);assert len(d.calls) == n   # complete: cached
    M._cache.clear()
    sparse = Candles(mv, missing=syms[:4])                      # 10/14 < 80% coverage: no change
    assert M.multiplier(sparse, "C11/USDT:USDT", "long", NOW) == 1.0
