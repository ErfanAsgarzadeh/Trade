"""Idea trail_width: trailing-stop channel = opposite extreme of last n closed 4h bars (current included).
Longs: low.rolling(n).min() (bb col 0); shorts: high.rolling(n).max() (bb col 3). Baseline n=10."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr import fb_harness as fh

VARIANTS = {'A': {'n': 20}, 'B': {'n': 5}}


def _cols(ctx, n):
    nb = ctx['bb'].shape[1]
    lo = np.full((len(fh.SYMBOLS), nb), np.nan)
    hi = np.full((len(fh.SYMBOLS), nb), np.nan)
    for k, s in enumerate(fh.SYMBOLS):
        f = ctx['frames'][s]
        l = f['low'].rolling(n).min().to_numpy(dtype=float)
        h = f['high'].rolling(n).max().to_numpy(dtype=float)
        i = np.asarray(ctx['ix'][s])
        ok = i >= 0
        j = np.clip(i, 0, len(l) - 1)
        lo[k, :len(i)][ok] = l[j][ok]
        hi[k, :len(i)][ok] = h[j][ok]
    return lo, hi


def build_fn(ctx, variant):
    lo, hi = _cols(ctx, variant['n'])
    bb = ctx['bb'].copy()
    bb[:, :, 0] = lo
    bb[:, :, 3] = hi
    return {'bb': bb}


if __name__ == '__main__':
    from high_cagr import imp_harness as h
    h.run_idea('trail_width', VARIANTS, build_fn, notes='bb col0=low.rolling(n).min(), col3=high.rolling(n).max() sampled at ix; A n=20, B n=5; baseline n=10.')
