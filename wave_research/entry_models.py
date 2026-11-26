import numpy as np

from .wave_engine import cross, ema, lag


def confirmations(bars, mode):
    op, high, low, close, _ = bars.T
    if mode == 2:
        p_open, p_close = lag(op, 1), lag(close, 1)
        long = (p_close < p_open) & (close > op) & (op <= p_close) & (close >= p_open)
        short = (p_close > p_open) & (close < op) & (op >= p_close) & (close <= p_open)
    elif mode == 3:
        span = high-low
        body = abs(close-op)
        long = (span > 0) & (body <= .35*span) & (np.minimum(close, op)-low >= .55*span) & (close > low+.65*span)
        short = (span > 0) & (body <= .35*span) & (high-np.maximum(close, op) >= .55*span) & (close < high-.65*span)
    elif mode == 9:
        macd = ema(close, 12)-ema(close, 26)
        return cross(macd, ema(macd, 9))
    elif mode == 11:
        p_hi, p_lo = lag(high, 1), lag(low, 1)
        long = (low < p_lo) & (close > p_lo) & (close > op)
        short = (high > p_hi) & (close < p_hi) & (close < op)
    else:
        return np.empty(0, np.int8)
    return long.astype(np.int8)-short.astype(np.int8)
