"""Volume filter: signal-bar volume >= k x mean volume of the previous 20 closed bars."""
import numpy as np

VARIANTS = {'A': {'mult': 1.2, 'n': 20}, 'B': {'mult': 1.5, 'n': 20}}


def mask_fn(frames, ix, side, variant):
    n, mult = variant['n'], variant['mult']
    out = {}
    for s, f in frames.items():
        v = f['volume'].to_numpy(float)
        prev = np.full(len(v), np.nan)
        # rolling mean of rows i-n..i-1 (strict past); NaN if any NaN in window
        w = np.lib.stride_tricks.sliding_window_view(v, n).mean(axis=1) if len(v) >= n else np.array([])
        prev[n:] = w[:len(v) - n]
        j = np.asarray(ix[s])
        vol, mu = v[j], prev[j]
        with np.errstate(invalid='ignore'):
            ok = np.isfinite(mu) & (mu > 0) & np.isfinite(vol) & (vol >= mult * mu)
        out[s] = ok & (j >= 0)
    return out


if __name__ == '__main__':
    from high_cagr import fb_harness as h
    h.run_method('volume', VARIANTS, mask_fn, notes='signal-bar volume >= k x mean of previous 20 closed bars (rows ix-20..ix-1); NaN/0 mean -> blocked')
