import numpy as np
import pandas as pd
from numba import njit

from ..wave_engine import between, cross, ema, fractals, lag, zigzag

NAMES = (
    "Wave 2 Completion", "Wave 1 Breakout", "Wave 4 Completion", "Wave 3 Breakout",
    "Wave 5 Reversal", "Wave B Completion", "Wave C Completion", "Zigzag Correction",
    "Regular Flat", "Expanded Flat", "Running Flat", "Contracting Triangle", "Expanding Triangle",
    "Double Zigzag", "Triple Zigzag", "Double Three", "Triple Three", "Ending Diagonal",
    "Leading Diagonal", "Truncated Fifth", "Miner Dual Timeframe Momentum", "Miner Time/Price Projection",
    "AO Zero Cross", "AO Twin Peaks", "AO Saucer", "Alligator + Fractals", "NEoWave",
    "Wolfe Waves", "Dow Market Structure", "ZigZag Breakout", "ZigZag Pullback", "Weis Wave Volume",
    "Wyckoff Spring", "Wyckoff Upthrust", "Wyckoff LPS", "Wyckoff LPSY", "Hurst Cycle",
    "Gann Swing", "Ichimoku N Wave", "Ichimoku V Wave", "Wavelet Analysis", "AB=CD", "Gartley",
    "Bat", "Butterfly", "Crab", "Deep Crab", "Alternate Bat", "Shark", "Five-O", "Three Drives", "Cypher")
NOT_TESTED = {
    14: "Requires validated lower-degree W-X-Y segmentation",
    15: "Requires validated lower-degree W-X-Y-X-Z segmentation",
    16: "Requires validated mixed corrective subwave segmentation",
    17: "Requires validated mixed corrective subwave segmentation",
    27: "No validated deterministic implementation of NEoWave",
}
PROXIES = {1, 2, 3, 4, 5, 6, 7, 12, 13, 18, 19, 21, 22, 26, 28, 29, 32, 33, 34, 35, 36, 37, 38,
           39, 40, 41, 49, 50, 51}


@njit(cache=True)
def pivot_rules(piv, vscan, signals, tol):
    for j in range(2, len(piv)):
        t = int(piv[j, 1])
        s = -int(piv[j, 2])
        c = s * piv[j, 3]
        b = s * piv[j-1, 3]
        a = s * piv[j-2, 3]
        if b <= a or b <= c:
            continue
        pull = (b - c) / (b - a)
        if a < c and between(pull, .382, .786, tol):
            signals[0, t] = s
            if j >= 3:
                dt = piv[j, 0] - piv[j-1, 0]
                prev = piv[j-1, 0] - piv[j-2, 0]
                if prev and between(dt / prev, .618, 1.618, tol):
                    signals[21, t] = s
            signals[30, t] = s
        if j < 3:
            continue
        o = s * piv[j-3, 3]
        impulse = o - a
        if impulse > 0:
            b_retr = (b - a) / impulse
            c_ext = (b - c) / impulse
            if c < a and between(b_retr, .382, .786, tol) and between(c_ext, .618, 1.618, tol):
                signals[7, t] = s
            if between(b_retr, .9, 1.05, tol) and c <= a and between(c_ext, .9, 1.382, tol):
                signals[8, t] = s
            if b_retr > 1.05 and c < a and between(c_ext, 1.236, 1.786, tol):
                signals[9, t] = s
            if b_retr > 1.05 and a < c < b and between(c_ext, .618, 1.272, tol):
                signals[10, t] = s
            if j >= 5 and c < a and b_retr < 1 and between(c_ext, .618, 1.618, tol):
                signals[6, t] = s
            if between(b_retr, .382, .886, tol) and between(c_ext, 1, 1, tol) and between(c_ext / b_retr, 1.13, 2.618, tol):
                signals[41, t] = s
        if o > b and c < a:
            signals[28, t] = -s
        elif o < b and c > a:
            signals[28, t] = s
            if .382 <= pull <= .618:
                signals[38, t] = s
            if .786 <= pull < 1:
                signals[39, t] = s
        if o > b and a < c < b:
            signals[5, t] = s
        if j < 4:
            continue
        x = s * piv[j-4, 3]
        if x < a < c and x < b and o < c < b:
            signals[2, t] = s
        if x < a < c and x < b < o:
            signals[11, t] = s
        if c < a < x and x < o < b:
            signals[12, t] = s
        if (c < a < x and o < b
                and c <= a + (a - x) * (piv[j, 0] - piv[j-2, 0]) / (piv[j-2, 0] - piv[j-4, 0])):
            signals[27, t] = s
        if x < o and x < a < o and a < b < o and c < b:
            xa, ab, bc, cd = o - x, o - a, b - a, b - c
            rb, rc, rd, rx = ab/xa, bc/ab, cd/bc, (o-c)/xa
            if between(rc, .382, .886, tol):
                # AB/XA, BC/AB, CD/BC, AD/XA; D must be beyond B.
                specifications = (
                    (.618, .618, 1.13, 1.618, .786, .786),
                    (.382, .5, 1.618, 2.618, .886, .886),
                    (.786, .786, 1.618, 2.618, 1.272, 1.618),
                    (.382, .618, 2.618, 3.618, 1.618, 1.618),
                    (.886, .886, 2., 3.618, 1.618, 1.618),
                    (.236, .382, 2., 3.618, 1.13, 1.13))
                for k in range(6):
                    ab0, ab1, cd0, cd1, xa0, xa1 = specifications[k]
                    if c < a and between(rb, ab0, ab1, tol) and between(rd, cd0, cd1, tol) and between(rx, xa0, xa1, tol):
                        signals[42 + k, t] = s
        if x < o and x < a < o and b > o and x < c < b:
            if between((o-a)/(o-x), .382, .618, tol) and between((b-x)/(o-x), 1.272, 1.414, tol) and between((b-c)/(b-x), .786, .786, tol):
                signals[51, t] = s
            if between((b-a)/(o-a), 1.13, 1.618, tol) and between((b-c)/(b-a), 1.618, 2.24, tol) and between((b-c)/(o-x), .886, 1.13, tol):
                signals[48, t] = s
        if j < 5:
            continue
        z = s * piv[j-5, 3]
        # Six pivots running down into the last low in mirrored coordinates.
        if c < a < x and z > o > b:
            w1, w3, w5 = z-x, o-a, b-c
            if x > b and w3 >= min(w1, w5):
                signals[4, t] = s
            if x < b and w1 > w3 > w5 and z > o > b:
                signals[17, t] = s
            if x < b and w1 < w3 < w5:
                signals[18, t] = s
            if c < a and .618 <= (z-o)/w1 <= .786 and .618 <= (o-b)/w3 <= .786:
                if between(w3/(o-x), 1.272, 1.618, tol) and between(w5/(b-a), 1.272, 1.618, tol):
                    signals[50, t] = s
            i0, i1 = int(piv[j-2, 0]), int(piv[j, 0])
            i2 = int(piv[j-4, 0])
            v1, v2 = vscan[i0 + 1] - vscan[i2 + 1], vscan[i1 + 1] - vscan[i0 + 1]
            if v1 > 0 and v2 * (i0-i2) < .8 * v1 * (i1-i0):
                signals[31, t] = s
        if a < c < b < x < o < z and o-a >= min(z-x, b-c):
            signals[19, t] = s
        # Six points 0-X-A-B-C-D: B extends XA; C extends AB past A; D retraces BC.
        if z > x < o and a < x < o < b and a < c < b:
            if between((o-a)/(o-x), 1.13, 1.618, tol) and between((b-a)/(o-a), 1.618, 2.24, tol):
                if between((b-c)/(b-a), .5, .5, tol) and between((b-c)/(o-a), 1, 1, tol):
                    signals[49, t] = s


@njit(cache=True)
def breaks(close, piv, signals):
    j = 0
    high, low = np.inf, -np.inf
    oldhigh, oldlow = np.inf, -np.inf
    high_armed, low_armed = False, False
    for t in range(1, len(close)):
        while j < len(piv) and piv[j, 1] <= t:
            if piv[j, 2] > 0:
                oldhigh, high = high, piv[j, 3]
                high_armed = True
            else:
                oldlow, low = low, piv[j, 3]
                low_armed = True
            j += 1
        if high_armed and close[t-1] <= high < close[t]:
            signals[29, t] = 1
            if j >= 3:
                signals[3 if high > oldhigh and low > oldlow else 1, t] = 1
            high_armed = False
        if low_armed and close[t-1] >= low > close[t]:
            signals[29, t] = -1
            if j >= 3:
                signals[3 if low < oldlow and high < oldhigh else 1, t] = -1
            low_armed = False


def generate(bars, a, multiple, tolerance):
    _, hi, lo, close, volume = bars.T
    piv = zigzag(close, a * multiple)
    signals = np.zeros((len(NAMES), len(close)), np.int8)
    pivot_rules(piv, np.r_[0., volume.cumsum()], signals, tolerance)
    breaks(close, piv, signals)
    series = pd.Series(close)
    median = pd.Series((hi + lo) / 2)
    ao = (median.rolling(5).mean() - median.rolling(34).mean()).to_numpy()
    signals[22] = cross(ao, 0)
    p1, p2, p3 = lag(ao, 1), lag(ao, 2), lag(ao, 3)
    signals[24] = ((ao > p1) & (p1 < p2) & (p2 < p3) & (p1 > 0)).astype(np.int8) - (
        (ao < p1) & (p1 > p2) & (p2 > p3) & (p1 < 0))
    troughs = np.flatnonzero((p2 > p1) & (ao > p1) & (p1 < 0))
    peaks = np.flatnonzero((p2 < p1) & (ao < p1) & (p1 > 0))
    for sign, loc in ((1, troughs), (-1, peaks)):
        x, y = loc[:-1], loc[1:]
        # A zero crossing invalidates the divergence between the two extrema.
        counts = np.cumsum(sign * ao >= 0)
        valid = (sign * (p1[y] - p1[x]) > 0) & (counts[y] == counts[x])
        signals[23, y[valid]] = sign
    f = fractals(hi, lo, 2)
    fractal_high, fractal_low = np.full(len(close), np.nan), np.full(len(close), np.nan)
    for kind, output in [(1, fractal_high), (-1, fractal_low)]:
        rows = f[f[:, 2] == kind]
        output[rows[:, 1].astype(int)] = rows[:, 3]
    jaw, teeth, lips = (lag(median.ewm(alpha=1/n, adjust=False).mean().to_numpy(), shift)
                         for n, shift in [(13, 8), (8, 5), (5, 3)])
    fh, fl = (pd.Series(x).ffill().to_numpy() for x in (fractal_high, fractal_low))
    signals[25] = ((cross(close, fh) == 1) & (lips > teeth) & (teeth > jaw)).astype(np.int8) - (
        (cross(close, fl) == -1) & (lips < teeth) & (teeth < jaw))
    # The higher-timeframe EMA only updates at the close of each four-bar group.
    indices = np.arange(3, len(close), 4)
    htf = np.full(len(close), np.nan)
    htf[indices] = close[indices] - ema(close[indices], 13)
    momentum = ema(close, 8) - ema(close, 21)
    signal = cross(momentum, ema(momentum, 5))
    signals[20] = np.where(signal * pd.Series(htf).ffill().to_numpy() > 0, signal, 0)
    prior_hi = pd.Series(hi).rolling(24).max().shift().to_numpy()
    prior_lo = pd.Series(lo).rolling(24).min().shift().to_numpy()
    signals[32] = np.where((lo < prior_lo) & (close > prior_lo), 1, 0)
    signals[33] = np.where((hi > prior_hi) & (close < prior_hi), -1, 0)
    slow = ema(close, 34)
    signals[34] = np.where((close > slow) & (lo < slow) & (lag(close, 1) > lag(slow, 1)), 1, 0)
    signals[35] = np.where((close < slow) & (hi > slow) & (lag(close, 1) < lag(slow, 1)), -1, 0)
    cycle = series.rolling(10).mean().to_numpy() - series.rolling(40).mean().to_numpy()
    signals[36] = cross(cycle - lag(cycle, 1), 0)
    up, dn = (hi > lag(hi, 1)) & (lo > lag(lo, 1)), (hi < lag(hi, 1)) & (lo < lag(lo, 1))
    signals[37] = (up & (lag(up, 1) == 1) & (lag(up, 2) != 1)).astype(np.int8) - (
        dn & (lag(dn, 1) == 1) & (lag(dn, 2) != 1))
    # Causal undecimated Haar detail at the 8-bar scale.
    short = series.rolling(4).mean().to_numpy()
    signals[40] = cross(short - lag(short, 4), 0)
    return signals, piv
