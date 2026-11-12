"""Unit-level checks for the Shahin FX research adapter (offline, no real data)."""
import math
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

from optimize_shahin import (
    Settings, compute_bars, fill_price, grid, pip_size, position_size,
    run_period, score, signal, usd_per_quote,
)


def synthetic_minutes(start="2025-01-02", bars=300, delta=0.0):
    beginning = pd.Timestamp(start, tz="UTC").value // 1_000_000
    ts = beginning + np.arange(bars * 240, dtype=np.int64) * 60_000
    close = 1.10 + delta + np.arange(len(ts)) * 0.0000001
    return pd.DataFrame({"timestamp": ts, "open": close, "high": close + 0.00003,
                         "low": close - 0.00003, "close": close, "volume": 2.0})


class ForexShahinTests(unittest.TestCase):
    def test_currency_conversion_and_pips(self):
        self.assertEqual(pip_size("USDJPY"), .01)
        self.assertEqual(pip_size("EURUSD"), .0001)
        self.assertAlmostEqual(usd_per_quote("USDJPY", 150), 1/150)
        self.assertEqual(usd_per_quote("GBPUSD", 1.3), 1.0)

    def test_execution_side_is_adverse(self):
        self.assertGreater(fill_price(1.1002, 1, 1), 1.1002)
        self.assertLess(fill_price(1.1000, -1, 1), 1.1000)

    def test_size_converts_usdjpy_risk_to_usd(self):
        qty = position_size(10_000, 150.0, 149.0, 150.0, "USDJPY",
                            .01, 5, .8, 0, 1000)
        self.assertEqual(qty, 15_000)  # $100 risk / ($1/150 per USD of base)
        qty2 = position_size(10_000, 1.1, 1.09, 1.1, "EURUSD",
                             .01, 5, .8, 0, 1000)
        self.assertEqual(qty2, 10_000)

    def test_ohlcv_4h_and_no_signal_on_partial_bars(self):
        bid = synthetic_minutes(bars=300)
        ask = bid.copy()
        for col in ("open", "high", "low", "close"):
            ask[col] += .0002
        # Remove one minute, so the first 4h group is explicitly incomplete
        bid = bid.drop(index=[0]).reset_index(drop=True)
        ask = ask.drop(index=[0]).reset_index(drop=True)
        bars = compute_bars(bid, ask, "standard", 10)
        self.assertEqual(len(bars), 299)
        self.assertEqual(int(bars.timestamp.iloc[0]),
                         int(bid.timestamp.iloc[0] // 14_400_000 + 1) * 14_400_000)
        self.assertTrue(bars.kumo_top.iloc[100:].notna().any())

    def test_no_same_bar_fill_or_lookahead(self):
        # No real signal can be formed in 2 days: lack of indicator warmup.
        bid = synthetic_minutes(bars=12)
        ask = bid.copy()
        for col in ("open", "high", "low", "close"):
            ask[col] += .0002
        bars = compute_bars(bid, ask, "standard", 10)
        r = run_period("EURUSD", bid, ask, bars, Settings(), "2025-01-02", "2025-01-04")
        self.assertEqual(r["trades"], 0)
        self.assertEqual(r["net_usd"], 0)

    def test_score_penalizes_drawdown(self):
        a = {"EURUSD": {"return_pct": 10, "max_daily_dd_pct": 5},
             "GBPUSD": {"return_pct": 10, "max_daily_dd_pct": 5},
             "USDJPY": {"return_pct": 10, "max_daily_dd_pct": 5}}
        b = {k: {**v, "max_daily_dd_pct": 10} for k, v in a.items()}
        self.assertGreater(score(a), score(b))

    def test_grid_unique(self):
        cases = grid()
        self.assertEqual(len(cases), 48)
        self.assertEqual(len(set(cases)), 48)


if __name__ == "__main__":
    unittest.main()
