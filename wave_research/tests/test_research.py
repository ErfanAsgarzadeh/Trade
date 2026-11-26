import unittest

import numpy as np

from wave_research.backtest_engine import execute
from wave_research.data_loader import aggregate
from wave_research.portfolio import replay
from wave_research.strategies import generate
from wave_research.wave_engine import atr, fractals, zigzag


class ResearchTest(unittest.TestCase):
    def test_confirmed_pivot_time(self):
        x = np.array([10., 11., 13., 12., 11., 12.])
        p = zigzag(x, np.ones(len(x))*2)
        np.testing.assert_array_equal(p, [[0, 2, -1, 10], [2, 4, 1, 13]])
        price = np.array([10., 11., 13., 11., 10.])
        np.testing.assert_array_equal(fractals(price, price, 2), [[2, 4, 1, 13]])

    def test_signal_prefix_and_conservative_fill(self):
        rng = np.random.default_rng(411)
        c = 100 + rng.normal(0, 1, 900).cumsum()
        p = np.column_stack((c, c + .5, c - .5, c, np.ones(len(c))))
        bars = aggregate(p, 3)
        a = atr(bars, 14)
        all_, piv = generate(bars, a, 1.5, .05)
        for cut in (100, 199, 245):
            partial, short_piv = generate(bars[:cut], a[:cut], 1.5, .05)
            np.testing.assert_array_equal(partial, all_[:, :cut])
            np.testing.assert_array_equal(short_piv, piv[piv[:, 1] < cut])
        duel = np.array([[100., 100., 100., 100., 1.], [100., 110., 90., 100., 1.]])
        fills = execute(duel, np.zeros(3), duel, np.ones(2), np.array([1, 0], np.int8),
                        1, 13, 4, 2., 18, 0., 0., .002)
        self.assertEqual(tuple(fills[0, :2]), (1, 1))
        self.assertEqual(fills[0, 4], 99.)

    def test_same_minute_accounting(self):
        leg = np.array([[0, 0, 100, .01, -1, .005, 0, 0]])
        cfg = {"friction":{"leverage":5, "margin_cap":.8, "fee_per_side":0., "slippage_per_fill":0.}}
        curve, pnl, actual = replay([leg], 1, cfg)
        self.assertEqual(len(actual), 1)
        self.assertEqual(curve[-1], 10000. + pnl.sum())
        self.assertEqual(curve[-1], 9950.)


if __name__ == "__main__":
    unittest.main()
