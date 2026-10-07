"""close_location: breakout bar must close near its extreme (long: close near high, short: close near low)."""
import sys
from pathlib import Path
import numpy as np

VARIANTS = {'A': {'min_loc': 0.60}, 'B': {'min_loc': 0.75}}


def mask_fn(frames, ix, side, variant):
    thr = variant['min_loc']
    out = {}
    for s, f in frames.items():
        h = f['high'].to_numpy(float); l = f['low'].to_numpy(float); c = f['close'].to_numpy(float)
        rng = h - l
        ok = rng > 0
        safe = np.where(ok, rng, 1.0)
        long_loc = (c - l) / safe
        short_loc = (h - c) / safe
        i = np.clip(np.asarray(ix[s]), 0, len(f) - 1)
        sd = np.asarray(side[s])
        good = ok[i] & np.where(sd > 0, long_loc[i] >= thr, short_loc[i] >= thr)
        out[s] = np.where(sd == 0, True, good).astype(bool)
    return out


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from high_cagr import fb_harness as h
    h.run_method('close_location', VARIANTS, mask_fn,
                 notes='Close-location filter on the breakout bar (row ix[sym][b]); high==low blocks entry; side 0 bars left True.')
