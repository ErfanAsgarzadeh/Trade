import numpy as np
import pandas as pd
from numba import njit


def ema(values, period):
    return pd.Series(values).ewm(span=period, adjust=False, min_periods=period).mean().to_numpy()


def atr(bars, period):
    prev = np.r_[bars[0, 3], bars[:-1, 3]]
    hi, lo = bars[:, 1], bars[:, 2]
    tr = np.maximum(hi - lo, np.maximum(abs(hi - prev), abs(lo - prev)))
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


@njit(cache=True)
def zigzag(close, thresholds):
    """Columns: occurrence bar, confirmation bar, kind (+1 high), price."""
    out = np.empty((len(close), 4))
    direction, extreme, occurrence, n = 0, close[0], 0, 0
    for t in range(len(close)):
        threshold = thresholds[t]
        value = close[t]
        if not np.isfinite(threshold) or threshold <= 0:
            continue
        if direction == 0 and abs(value - extreme) >= threshold:
            direction = 1 if value > extreme else -1
            out[n, 0], out[n, 1], out[n, 2], out[n, 3] = occurrence, t, -direction, extreme
            n += 1
            extreme, occurrence = value, t
        elif direction and direction * (value - extreme) > 0:
            extreme, occurrence = value, t
        elif direction and direction * (extreme - value) >= threshold:
            out[n, 0], out[n, 1], out[n, 2], out[n, 3] = occurrence, t, direction, extreme
            n += 1
            extreme, occurrence, direction = value, t, -direction
    return out[:n]


@njit(cache=True)
def fractals(high, low, window):
    out = np.empty((len(high), 4))
    n = 0
    for i in range(window, len(high) - window):
        h, l = True, True
        for j in range(i - window, i + window + 1):
            if j != i:
                h = h and high[i] > high[j]
                l = l and low[i] < low[j]
        if h != l:
            out[n, 0], out[n, 1] = i, i + window
            out[n, 2], out[n, 3] = (1, high[i]) if h else (-1, low[i])
            n += 1
    return out[:n]


@njit(cache=True)
def between(value, lo, hi, tolerance=0.):
    return lo * (1 - tolerance) <= value <= hi * (1 + tolerance)


def lag(values, n):
    out = np.full(len(values), np.nan)
    if n < len(values):
        out[n:] = values[:-n]
    return out


def cross(x, y):
    other = x - y
    previous = lag(other, 1)
    return ((other > 0) & (previous <= 0)).astype(np.int8) - ((other < 0) & (previous >= 0)).astype(np.int8)
