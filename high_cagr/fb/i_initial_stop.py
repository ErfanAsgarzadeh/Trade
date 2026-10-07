"""Idea initial_stop: initial stop = price - side*k*ATR(4h at signal row) instead of k=2 (A: 1.5, B: 2.5)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr import fb_harness as fh

VARIANTS = {'A': {'k': 1.5}, 'B': {'k': 2.5}}


def rebuild_stop(ctx, k):
    sig = ctx['sig'].copy()
    for j, s in enumerate(fh.SYMBOLS):
        atr = ctx['frames'][s].atr.to_numpy(dtype=float)
        i = np.asarray(ctx['ix'][s])
        a = atr[np.clip(i, 0, len(atr) - 1)]
        on = sig[j, :, 0] != 0
        sig[j, on, 2] = sig[j, on, 1] - sig[j, on, 0] * k * a[on]
    return sig


def build_fn(ctx, variant):
    return {'sig': rebuild_stop(ctx, variant['k'])}


if __name__ == '__main__':
    from high_cagr import imp_harness as h
    h.run_idea('initial_stop', VARIANTS, build_fn, notes='Initial stop = entry - side*k*ATR(4h frame row at signal bar), only on bars with side!=0; A k=1.5, B k=2.5; kernel sizing/min-stop rejection unchanged.')
