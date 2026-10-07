"""C3 agent 5 -- TREND-FILTER LAG.

Cause (C3_DIAGNOSIS.md): inside big trends 19.2% of the move happens while C3's own trend filter
(EMA50 vs EMA200 on 4h) still points the other way: the 200-EMA cross is slow at trend starts.
Trades taken within 30 bars of a fresh EMA cross are the best cohort (+1.05R, 46% win), i.e. the
earliest part of a trend is the most valuable part, and the slow filter gives some of it away.

Mechanism: keep the PULL trigger (RSI14 re-cross up through 40 for longs / down through 60 for shorts),
mode 6 exit (2 ATR initial stop, 4.5 ATR chandelier), weekend mask d['wk'] on the signal bar, warm 300,
fees/slip identical to the baseline. Only the TREND DEFINITION that gates the trigger changes.
All parameters are round numbers fixed here before any run; no tuning afterwards.

Variants (pre-declared):
  V1 'ema20_100'  -- replace EMA50>EMA200 by EMA20>EMA100 (same 1:4 ratio, half the length).
                     Flips roughly twice as fast; risk: more whipsaw flips in chop.
  V2 'slope_union'-- long trend = (EMA50>EMA200) OR (close>EMA200 AND EMA50 rising vs 10 bars ago);
                     short mirror. Catches the stretch where price has already reclaimed EMA200 and the
                     50 is turning, but the 50/200 cross has not happened yet. Baseline trades are a
                     subset of the signal set (only extra early-trend entries are added, though the
                     single-position engine can shift later trades).
  V3 'don55_union'-- long trend = (EMA50>EMA200) OR Donchian-55 regime long (state set by close above the
                     prior 55-bar high, kept until close below the prior 55-bar low); short mirror.
                     A 55-bar (~9 day) breakout is a structural trend-start marker that does not wait
                     for averages to cross.
Causality: every indicator is an EMA / rolling window / state machine over bars <= t (Donchian levels use
shift(1)); entries fill at o[t+1] inside the engine.
"""
from pathlib import Path
import sys
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from high_cagr.ideas import c3bench as B, ltf_search as L, mtf_search as M

VARIANTS = {'ema20_100': 'ema20_100', 'slope_union': 'slope_union', 'don55_union': 'don55_union'}


def don_regime(h, l, c, N=55):
    hh = pd.Series(h).rolling(N).max().shift(1).to_numpy(); ll = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    st = np.zeros(len(c)); s = 0.
    for i in range(len(c)):
        if c[i] > hh[i]: s = 1.
        elif c[i] < ll[i]: s = -1.
        st[i] = s
    return st


def trades_fn(d, variant):
    c, h, l = d['c'], d['h'], d['l']; n = len(c)
    r14 = L.rsi(c, 14)
    up40 = L.cross_up(r14, np.full_like(r14, 40.)); dn60 = L.cross_dn(r14, np.full_like(r14, 60.))
    e50, e200 = L.ema(c, 50), L.ema(c, 200)
    if variant == 'ema20_100':
        a, b = L.ema(c, 20), L.ema(c, 100); tl, ts = a > b, a < b
    elif variant == 'slope_union':
        prev = np.concatenate([np.full(10, np.nan), e50[:-10]])
        tl = (e50 > e200) | ((c > e200) & (e50 > prev)); ts = (e50 < e200) | ((c < e200) & (e50 < prev))
    elif variant == 'don55_union':
        st = don_regime(h, l, c, 55); tl = (e50 > e200) | (st == 1); ts = (e50 < e200) | (st == -1)
    else:
        raise ValueError(variant)
    le = np.nan_to_num((tl & up40).astype(float)) > 0; se = np.nan_to_num((ts & dn60).astype(float)) > 0
    z = np.zeros(n, bool)
    return M.engine(d['o'], h, l, c, d['atr'], le, se, z, z, d['wk'], d['wk'], 6, .0006, .0002, d['fb'], 300)


if __name__ == '__main__':
    B.run('a5_trendlag', VARIANTS, trades_fn,
          notes='Trend-filter lag: faster/union trend definitions gating the unchanged PULL trigger; mode 6; wk mask.')
