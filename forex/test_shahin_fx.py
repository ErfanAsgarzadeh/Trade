"""Offline tests for the Shahin-FX engine (synthetic minutes, no network)."""
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shahin_fx as fx  # noqa: E402

T0 = fx.ms("2022-01-03") + fx.SESSION_OFFSET_MS - fx.DAY_MS  # Sunday 22:00 UTC session open


def synthetic(days=80, drift=(2e-6, 2e-6, -2e-6), seed=1):
    """Weekday-only minutes with a trend; weekends are left out like real FX."""
    rng = np.random.default_rng(seed)
    t = np.arange(T0, T0 + days * fx.DAY_MS, fx.MINUTE_MS)
    dow = ((t // fx.DAY_MS) + 3) % 7
    hour = (t % fx.DAY_MS) // fx.HOUR_MS
    keep = ~((dow == 5) | ((dow == 4) & (hour >= 22)) | ((dow == 6) & (hour < 22)))
    t = t[keep]
    frames = {}
    for p, (pair, start) in enumerate(zip(fx.PAIRS, (1.10, 1.30, 110.0))):
        steps = drift[p] + rng.normal(0, 8e-5, len(t))
        close = start * np.exp(np.cumsum(steps))
        open_ = np.r_[start, close[:-1]]
        hi = np.maximum(open_, close) * (1 + 2e-5)
        lo = np.minimum(open_, close) * (1 - 2e-5)
        frames[pair] = pd.DataFrame({"timestamp": t, "open": open_, "high": hi, "low": lo,
                                     "close": close, "volume": 0.0})
    ohlc = np.stack([np.stack([frames[p][c].to_numpy() for p in fx.PAIRS])
                     for c in ("open", "high", "low", "close")])
    return fx.Prepared(t, ohlc, frames)


class BarsTest(unittest.TestCase):
    def test_bars_aligned_to_fx_session(self):
        pr = synthetic(days=14)
        bars = fx.make_bars(pr.frames["EURUSD"], "4h")
        hours = set(((bars.open_ms // fx.HOUR_MS) % 24).tolist())
        self.assertEqual(hours, {22, 2, 6, 10, 14, 18})
        d1 = fx.make_bars(pr.frames["EURUSD"], "D1")
        self.assertTrue(((d1.open_ms - fx.SESSION_OFFSET_MS) % fx.DAY_MS == 0).all())
        self.assertFalse(((d1.open_ms // fx.DAY_MS + 3) % 7 == 5).any())  # no Saturday stub

    def test_indicators_are_causal(self):
        pr = synthetic(days=40)
        bars = fx.make_bars(pr.frames["EURUSD"], "4h")
        a = fx.indicators(bars, "standard", 20)
        b = fx.indicators(bars.iloc[:150].copy(), "standard", 20)
        for k in ("don_hi", "kumo_top", "atr", "atr_med"):
            np.testing.assert_allclose(a[k][:150], b[k], equal_nan=True)


class SwapTest(unittest.TestCase):
    def test_carry_sign_follows_rate_differential(self):
        t = np.array([fx.ms("2023-06-01"), fx.ms("2023-06-30")])
        d0, long_, short = fx.swap_tables(t, 0.5)
        jpy = fx.PAIRS.index("USDJPY")
        i = (fx.ms("2023-06-15") // fx.DAY_MS) - d0
        self.assertGreater(long_[jpy, i], 0.04)   # USD ~5.1 % vs JPY -0.1 %
        self.assertLess(short[jpy, i], -0.05)
        self.assertTrue((long_ + short < 0).all())  # broker markup always costs


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.pr = synthetic()
        self.zero = fx.Costs(spread_pips=(0, 0, 0), slippage_pips=0, commission_rt_per_100k=0,
                             swap_markup_pct=0)

    def test_trend_is_captured_and_risk_is_bounded(self):
        cfg = fx.Config(tf="4h", preset="none", donchian=20, trail="DON20", atr_gate=False,
                        pyramid=False, min_stop_pips=0)
        r = fx.run(self.pr, cfg, self.zero, "2022-01-02", "2022-03-25", detail=True)
        self.assertGreater(r["trades"], 0)
        self.assertGreater(r["return_pct"], 0)
        for tr in r["trade_list"]:
            self.assertGreaterEqual(tr["r_multiple"], -1.3)  # 1R stop, minute-level fills
        longs = [t for t in r["trade_list"] if t["pair"] == "EURUSD"]
        self.assertTrue(all(t["side"] == "long" for t in longs))

    def test_costs_reduce_result(self):
        cfg = fx.Config(tf="4h", preset="none", donchian=20, trail="DON20", atr_gate=False,
                        pyramid=False, min_stop_pips=0)
        free = fx.run(self.pr, cfg, self.zero, "2022-01-02", "2022-03-25")
        paid = fx.run(self.pr, cfg, fx.Costs(spread_pips=(3, 3, 3), slippage_pips=1,
                                             commission_rt_per_100k=10), "2022-01-02", "2022-03-25")
        self.assertLess(paid["final_equity"], free["final_equity"])

    def test_crypto_percent_min_stop_blocks_fx_sized_stops(self):
        cfg = fx.crypto_shahin_as_is()
        r = fx.run(self.pr, cfg, self.zero, "2022-01-02", "2022-03-25")
        self.assertEqual(r["trades"], 0)  # 2xATR on 4h FX is far below 1.2 % of price

    def test_usd_cap_limits_same_direction_exposure(self):
        base = fx.Config(tf="4h", preset="none", donchian=20, trail="DON20", atr_gate=False,
                         pyramid=False, min_stop_pips=0)
        many = fx.run(self.pr, base, self.zero, "2022-01-02", "2022-03-25")
        one = fx.run(self.pr, fx.Config(**{**base.__dict__, "usd_cap": 1}), self.zero,
                     "2022-01-02", "2022-03-25")
        self.assertLessEqual(one["trades"], many["trades"])


if __name__ == "__main__":
    unittest.main()
