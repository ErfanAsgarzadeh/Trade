"""C3 round 2, agent 5 -- TREND-END EXIT (capture more of big trends).

Baseline = C3 + D (c3bench_d): PULL entry confirmed by a close beyond the signal-bar close within 3 bars,
mode 6 exit = 2 ATR initial stop, 4.5 ATR chandelier on the best close. The baseline captures only ~32% of
big-trend moves; the 4.5 ATR chandelier exits on ordinary mid-trend pullbacks and the bot then needs a new
PULL+D signal to get back in (often never, or much later).

Mechanism: once a trade has PROVEN itself (best close >= entry + 2R, R = initial stop distance), stop managing
it by price distance and hold it until the TREND itself ends. Before +2R everything is identical to the
baseline (2 ATR stop, 4.5 ATR chandelier), so losers and early givebacks are unchanged. After arming, the
chandelier widens to 8 ATR (catastrophic stop, still ratchets on the best close, never loosens), and a
trend-end rule decides the exit at the next bar's open. Parameters are fixed round numbers, declared before
any run; no tuning afterwards.

Variants:
  V1 'ema50'   -- trend end = a 4h close beyond EMA50 against the trade (long: c < EMA50).
                  Fastest trend-end definition; risk: EMA50 is where PULL pullbacks live, may exit on dips.
  V2 'don20d'  -- trend end = a DAILY close (every 6th 4h bar, UTC day close) beyond the 20-day Donchian
                  against the trade (long: daily close < lowest low of the previous 20 full days).
                  Classic turtle-style structural exit; slower, lets multi-week trends run.
  V3 'xcross'  -- trend end = EMA50 crosses back through EMA200 (C3's own regime flip), evaluated on 4h close.
                  Slowest; the 8 ATR catastrophic chandelier will usually be the binding exit.
Engine: own numba copy of mtf_search.engine mode 6 (bench row format, fee .0006, slip .0002, funding d['fb'],
base 1e4, 0.5% risk, 40% notional cap, min stop .4%, warm 300); entries = c3bench_d.confirm_signals(d) with
the weekend mask d['wk']. Trend-exit signals use only bars <= j and fill at o[j+1].
"""
from pathlib import Path
import sys
import numpy as np, pandas as pd
from numba import njit
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from high_cagr.ideas import c3bench_d as BD, ltf_search as L

VARIANTS = {'ema50': 'ema50', 'don20d': 'don20d', 'xcross': 'xcross'}
ARM_R, TW0, TW1 = 2.0, 4.5, 8.0


@njit(cache=True)
def engine_te(o, h, l, c, atr, le, se, al, as_, xl, xs, fee, slip, fcum, warm, arm_r, tw0, tw1):
    """mode 6 + trend-end exit after +arm_r R. xl[j]/xs[j]: trend ended against a long/short at close j."""
    n = len(c); out = np.zeros((n, 9)); k = 0; t = warm
    while t < n - 2:
        side = 1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side == 0 or not atr[t] > 0: t += 1; continue
        e = t + 1; raw = o[e]; entry = raw * (1 + side * slip); a = atr[t]
        stop = entry - side * 2. * a; dist = side * (entry - stop)
        if dist / entry < .004: t += 1; continue
        qty = min(.005 * 1e4 / (dist + entry * (2 * fee + 2 * slip)), .4 * 1e4 / entry)
        best = c[t]; xraw = 0.; x = e; j = e; armed = False
        while j < n:
            if side == 1:
                if l[j] <= stop: xraw = min(o[j], stop); x = j; break
            else:
                if h[j] >= stop: xraw = max(o[j], stop); x = j; break
            best = max(best, c[j]) if side == 1 else min(best, c[j])
            if not armed and side * (best - entry) >= arm_r * dist: armed = True
            if armed and ((side == 1 and xl[j]) or (side == -1 and xs[j])) and j + 1 < n:
                xraw = o[j + 1]; x = j + 1; break
            ns = best - side * (tw1 if armed else tw0) * atr[j]
            if side * (ns - stop) > 0: stop = ns
            j += 1
        if xraw == 0.: xraw = c[n - 1]; x = n - 1
        xp = xraw * (1 - side * slip); fund = -side * raw * qty * (fcum[x] - fcum[e])
        net = side * (xp - entry) * qty - (entry + xp) * qty * fee + fund
        out[k, 0] = e; out[k, 1] = x; out[k, 2] = side; out[k, 3] = net / 1e4; out[k, 4] = side * (xraw - raw) / dist
        out[k, 5] = qty; out[k, 6] = entry; out[k, 7] = xp; out[k, 8] = (entry + xp) * qty * fee - fund; k += 1
        t = x if x > t else t + 1
    return out[:k]


def trend_end(d, variant):
    c, h, l = d['c'], d['h'], d['l']; n = len(c)
    e50, e200 = L.ema(c, 50), L.ema(c, 200)
    if variant == 'ema50':
        return c < e50, c > e50
    if variant == 'xcross':
        return e50 < e200, e50 > e200
    if variant == 'don20d':
        # previous 20 full UTC days = 4h bars [j-125, j-6] for a day-close bar j (j % 6 == 5)
        lo = pd.Series(l).rolling(120).min().shift(6).to_numpy(); hi = pd.Series(h).rolling(120).max().shift(6).to_numpy()
        dc = (np.arange(n) % 6) == 5
        return np.nan_to_num((dc & (c < lo)).astype(float)) > 0, np.nan_to_num((dc & (c > hi)).astype(float)) > 0
    raise ValueError(variant)


def trades_fn(d, variant):
    le, se = BD.confirm_signals(d); xl, xs = trend_end(d, variant)
    return engine_te(d['o'], d['h'], d['l'], d['c'], d['atr'], le, se, d['wk'], d['wk'], xl, xs,
                     .0006, .0002, d['fb'], 300, ARM_R, TW0, TW1)


if __name__ == '__main__':
    # sanity: with the trend exit never firing and tw1 == tw0 the engine must reproduce the C3+D baseline
    d = BD.B.coin('AVAXUSDT'); le, se = BD.confirm_signals(d); z = np.zeros(d['n'], bool)
    a = engine_te(d['o'], d['h'], d['l'], d['c'], d['atr'], le, se, d['wk'], d['wk'], z, z, .0006, .0002, d['fb'], 300, ARM_R, TW0, TW0)
    b = BD.d_trades(d); print('engine copy reproduces baseline:', a.shape == b.shape and np.allclose(a, b), flush=True)
    BD.run('r2_a5_trendexit', VARIANTS, trades_fn,
           notes='Trend-end exit after +2R (EMA50 close / 20-day daily Donchian / EMA50-200 cross back), 8 ATR catastrophic chandelier.')
