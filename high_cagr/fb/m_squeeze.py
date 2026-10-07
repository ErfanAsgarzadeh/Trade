"""Squeeze filter: breakout allowed only if prior-20-bar range (in ATR units) is low vs its own prior 250 values."""
import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

VARIANTS = {'A': {'max_pct': 0.50}, 'B': {'max_pct': 0.30}}
N_RANGE, N_RANK = 20, 250

def _pct_rank_series(f):
    hi = f['high'].to_numpy(float); lo = f['low'].to_numpy(float); atr = f['atr'].to_numpy(float)
    n = len(f)
    P = np.full(n, np.nan)
    # range of bars i-20..i-1 (shifted rolling)
    rmax = pd.Series(hi).rolling(N_RANGE).max().shift(1).to_numpy()
    rmin = pd.Series(lo).rolling(N_RANGE).min().shift(1).to_numpy()
    W = (rmax - rmin) / atr
    if n <= N_RANK:
        return P
    win = sliding_window_view(W, N_RANK)[:n - N_RANK]   # win[k] = W[k..k+249] -> prior values for i=k+250
    cur = W[N_RANK:]
    ok = ~np.isnan(win).any(axis=1) & ~np.isnan(cur)
    with np.errstate(invalid='ignore'):
        frac = (win < cur[:, None]).mean(axis=1)
    P[N_RANK:] = np.where(ok, frac, np.nan)
    return P

def mask_fn(frames, ix, side, variant):
    out = {}
    thr = variant['max_pct']
    for s, f in frames.items():
        P = _pct_rank_series(f)
        p = P[np.asarray(ix[s])]
        out[s] = np.nan_to_num(p, nan=2.0) <= thr   # NaN -> not allowed
    return out

if __name__ == '__main__':
    from high_cagr import fb_harness as h
    h.run_method('squeeze', VARIANTS, mask_fn, notes='W=(max high - min low of prior 20 bars)/atr[i]; P=fraction of prior 250 W values strictly smaller (needs 250 valid priors); A: P<=0.50, B: P<=0.30. Rows with insufficient history or NaN not allowed.')
