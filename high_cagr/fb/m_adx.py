"""Method adx: allow breakout only if Wilder ADX(14) on the 4h frame at the signal row >= threshold."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import lbank_bot

VARIANTS = {'A': {'min_adx': 20.0}, 'B': {'min_adx': 25.0}}


def mask_fn(frames, ix, side, variant):
    out = {}
    for s in side:
        adx = lbank_bot.adx_wilder(frames[s], 14).to_numpy(dtype=float)
        i = np.asarray(ix[s])
        ok = i >= 0
        v = np.full(len(i), np.nan)
        v[ok] = adx[np.clip(i, 0, len(adx) - 1)][ok]
        out[s] = np.nan_to_num(v, nan=-1.0) >= variant['min_adx']
    return out


if __name__ == '__main__':
    from high_cagr import fb_harness as h
    h.run_method('adx', VARIANTS, mask_fn, notes='Wilder ADX(14) via lbank_bot.adx_wilder on full 4h frame, indexed at ix; NaN -> blocked; A>=20, B>=25.')
