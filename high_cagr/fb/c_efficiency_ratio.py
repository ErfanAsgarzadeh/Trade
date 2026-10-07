"""Chop idea efficiency_ratio: allow entry only if Kaufman ER(20) on 4h closes at the signal row >= min_er (A 0.30, B 0.40)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np

VARIANTS = {'A': {'min_er': 0.30}, 'B': {'min_er': 0.40}}
N = 20


def er_series(close):
    c = np.asarray(close, dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) <= N:
        return out
    d = np.abs(np.diff(c))  # d[j-1] = |c_j - c_{j-1}|
    cs = np.concatenate([[0.0], np.cumsum(d)])  # cs[k] = sum of first k diffs
    # row i uses diffs for j=i-19..i  -> d[i-20..i-1] -> cs[i]-cs[i-20]
    den = cs[N:] - cs[:-N]
    num = np.abs(c[N:] - c[:-N])
    with np.errstate(divide='ignore', invalid='ignore'):
        er = np.where(den > 0, num / den, np.nan)
    out[N:] = er
    return out


def mask_fn(frames, ix, side, variant):
    out = {}
    for s in side:
        er = er_series(frames[s]['close'].to_numpy(dtype=float))
        i = np.asarray(ix[s])
        v = np.full(len(i), np.nan)
        ok = i >= 0
        v[ok] = er[np.clip(i, 0, len(er) - 1)][ok]
        out[s] = np.nan_to_num(v, nan=-1.0) >= variant['min_er']
    return out


def build_fn(ctx, variant):
    from high_cagr import chop_harness as h
    sig = h.base_sig()
    m = mask_fn(ctx['frames'], ctx['ix'], ctx['side'], variant)
    for k, s in enumerate(h.SYM):
        sig[k, ~np.asarray(m[s], bool), 0] = 0
    return {'sig': sig}


if __name__ == '__main__':
    from high_cagr import fb_harness
    print(fb_harness.check_causal(mask_fn, VARIANTS['A']), flush=True)
    from high_cagr import chop_harness as h
    h.run_idea('efficiency_ratio', VARIANTS, build_fn, notes='Kaufman ER(20) on 4h closes at ix row (|c_i-c_{i-20}|/sum|dc| over 20 bars); NaN/zero denominator blocked; A>=0.30, B>=0.40; zeroes sig[:,:,0] where not allowed.')
