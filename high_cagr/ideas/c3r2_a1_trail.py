"""Round 2, agent 1 - runner-friendly trailing exit for C3+D (entries = c3bench_d.confirm_signals, unchanged).

Baseline exit (mode 6): initial stop 2 ATR[signal], chandelier = best CLOSE - 4.5 ATR[j], ratchet only.
Problem: winners keep only 16-60% of their peak and big-trend capture is ~32%. The 4.5 ATR chandelier is a fixed
volatility band; in a strong trend the normal 4h pullbacks (often 3-5 ATR) shake the trade out early, while weak trades
need the tight band to limit giveback. All variants keep the initial 2 ATR stop and the 4.5 ATR chandelier until the
condition below holds, so losers and small winners behave exactly like the baseline.

Variants declared BEFORE any run (fixed round parameters, no tuning afterwards):

A  'regime6' - regime-aware width. On each bar j the chandelier multiplier is 6.0 ATR when the trend is strong at bar j
   (long: close > EMA50 and EMA50 > EMA50 10 bars earlier; short mirrored), otherwise 4.5 ATR. Mechanism: when price is
   holding above a rising EMA50 the trend is intact and pullbacks are noise, so give them room; when price loses the
   EMA50 or it flattens, the trend is weakening and the normal band applies again (stop never loosens: ratchet only).

B  'step3R_6' - profit-tiered width. Once the best close has reached +3R (R = initial stop distance), the chandelier
   multiplier switches permanently to 6.0 ATR. Mechanism: a trade that has run 3R is statistically a runner (fat right
   tail: top 10% of trades = 173% of net R); a runner's value is in staying for the trend, while the giveback problem
   sits mostly in the 1-3R trades, which keep the 4.5 ATR band.

C  'step3R_don60' - structure trail for runners. Once the best close has reached +3R, the trailing level becomes
   max(current stop, lowest low of the last 60 bars = 10 days) for longs (short: highest high), ratchet only, and the
   ATR chandelier is no longer tightened. Mechanism: a trend is intact until it makes a 10-day low; a structural level
   ignores single-bar volatility spikes that an ATR band reacts to and follows the trend's own swing lows.

Engine: copy of mtf_search.engine (same output format, costs .0006/.0002, funding via fb, base 1e4, 0.5% risk,
one position per coin, stop checked intrabar before the trail is updated on the bar's close). All exit inputs at bar j
use data <= j and only affect the stop from bar j+1 on.
"""
from pathlib import Path
import sys
import numpy as np, pandas as pd
from numba import njit
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import c3bench_d as BD


@njit(cache=True)
def engine(o, h, l, c, atr, le, se, al, as_, fee, slip, fcum, warm, kind, wide, rthr, strong_l, strong_s, lowN, highN):
    n = len(c); out = np.zeros((n, 9)); k = 0; t = warm
    while t < n - 2:
        side = 1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side == 0 or not atr[t] > 0: t += 1; continue
        e = t + 1; raw = o[e]; entry = raw * (1 + side * slip); a = atr[t]
        stop = entry - side * 2. * a; dist = side * (entry - stop)
        if dist / entry < .004: t += 1; continue
        qty = min(.005 * 1e4 / (dist + entry * (2 * fee + 2 * slip)), .4 * 1e4 / entry); best = c[t]; xraw = 0.; x = e; j = e
        runner = False
        while j < n:
            if side == 1:
                if l[j] <= stop: xraw = min(o[j], stop); x = j; break
            else:
                if h[j] >= stop: xraw = max(o[j], stop); x = j; break
            best = max(best, c[j]) if side == 1 else min(best, c[j])
            if side * (best - entry) >= rthr * dist: runner = True
            tw = 4.5
            if kind == 1:
                st = strong_l[j] if side == 1 else strong_s[j]
                if st: tw = wide
            elif kind == 2:
                if runner: tw = wide
            if kind == 3 and runner:
                ns = lowN[j] if side == 1 else highN[j]
            else:
                ns = best - side * tw * atr[j]
            if side * (ns - stop) > 0: stop = ns
            j += 1
        if xraw == 0.: xraw = c[n - 1]; x = n - 1
        xp = xraw * (1 - side * slip); fund = -side * raw * qty * (fcum[x] - fcum[e])
        net = side * (xp - entry) * qty - (entry + xp) * qty * fee + fund
        out[k, 0] = e; out[k, 1] = x; out[k, 2] = side; out[k, 3] = net / 1e4; out[k, 4] = side * (xraw - raw) / dist; out[k, 5] = qty
        out[k, 6] = entry; out[k, 7] = xp; out[k, 8] = (entry + xp) * qty * fee - fund; k += 1
        t = x if x > t else t + 1
    return out[:k]


KIND = {'base': 0, 'regime': 1, 'step': 2, 'don': 3}


def trades_fn(d, variant):
    le, se = BD.confirm_signals(d); n = d['n']; c = d['c']; e50 = d['e50']
    prev = np.concatenate([np.full(10, np.nan), e50[:-10]])
    strong_l = (c > e50) & (e50 > prev); strong_s = (c < e50) & (e50 < prev)
    N = variant.get('don', 60)
    lowN = pd.Series(d['l']).rolling(N, min_periods=1).min().to_numpy(); highN = pd.Series(d['h']).rolling(N, min_periods=1).max().to_numpy()
    return engine(d['o'], d['h'], d['l'], c, d['atr'], le, se, d['wk'], d['wk'], .0006, .0002, d['fb'], 300,
                  KIND[variant['kind']], float(variant.get('wide', 4.5)), float(variant.get('r', 1e9)), strong_l, strong_s, lowN, highN)


if __name__ == '__main__':
    V = {'A': dict(kind='regime', wide=6.0), 'B': dict(kind='step', wide=6.0, r=3.0), 'C': dict(kind='don', r=3.0, don=60)}
    # sanity: kind base must reproduce the C3+D baseline exactly
    dd = BD.B.coin('AVAXUSDT'); x0 = trades_fn(dd, dict(kind='base')); x1 = BD.d_trades(dd)
    print('engine copy reproduces baseline:', x0.shape == x1.shape and np.allclose(x0, x1), flush=True)
    BD.run('c3r2_a1_trail', V, trades_fn, notes='Round2 agent1: runner trail. A regime 6ATR when close>rising EMA50; B 6ATR after +3R; C 60-bar low/high trail after +3R.')
