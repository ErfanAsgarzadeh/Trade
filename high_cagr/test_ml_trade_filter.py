"""Offline smoke tests; run without unpacking the five-year minute archive."""
import numpy as np
import pandas as pd
from high_cagr.ml_trade_filter import (LOOKBACK, STEP_MS, sequence, bar_index,
                                        summarize_sequence, apply_gate)


def example_frame():
    n = LOOKBACK + 20
    close = np.linspace(100., 110., n)
    return pd.DataFrame(dict(
        timestamp=np.arange(n, dtype=np.int64) * STEP_MS,
        open=close - .2, high=close + 1., low=close - 1., close=close,
        volume=np.arange(n, dtype=float) + 10.,
        atr=np.full(n, 2.), kijun=close - 1.
    ))


def test_causal_window_excludes_future_and_open_bar():
    f = example_frame()
    ix = bar_index(f, (LOOKBACK + 7) * STEP_MS + 3000)
    assert ix == LOOKBACK + 6
    old = sequence(f, ix, 1, 0)
    f.loc[ix + 1:, ["open", "high", "low", "close", "volume"]] *= 1000
    np.testing.assert_array_equal(old, sequence(f, ix, 1, 0))
    assert old.shape == (LOOKBACK, 14)
    assert summarize_sequence(old).shape == (54,)


def test_direction_symmetry_and_missing_warmup():
    f = example_frame()
    assert sequence(f, LOOKBACK - 1, 1, 0) is None
    long = sequence(f, LOOKBACK + 3, 1, 0)
    short = sequence(f, LOOKBACK + 3, -1, 0)
    np.testing.assert_allclose(long[:, 0], -short[:, 0])
    np.testing.assert_allclose(long[:, 2], short[:, 2])


def test_gating_does_not_change_original_signals_or_other_fields():
    sig = np.zeros((2, 5, 4))
    sig[:, :, 0] = 1
    sig[:, :, 1] = 123.
    probabilities = np.array([.1, .5, .8])
    locations = np.array([[0, 1], [1, 2], [0, 4]])
    filtered = apply_gate(sig, probabilities, locations, .4)
    assert filtered[0, 1, 0] == 0.
    assert filtered[1, 2, 0] == 1.
    assert sig[0, 1, 0] == 1.
    np.testing.assert_array_equal(filtered[:, :, 1:], sig[:, :, 1:])
    np.testing.assert_array_equal(apply_gate(sig, probabilities, locations, 0), sig)
