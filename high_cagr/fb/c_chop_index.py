"""CHOP study method chop_index: allow entry only if Choppiness Index(14) on the 4h frame at the signal row < max_ci."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np

VARIANTS = {'A': {'max_ci': 61.8}, 'B': {'max_ci': 50.0}}
N = 14


def _ci(f):
    h = f['high'].to_numpy(float); l = f['low'].to_numpy(float); c = f['close'].to_numpy(float)
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    trs = np.full(len(f), np.nan); hh = trs.copy(); ll = trs.copy()
    for i in range(N - 1, len(f)):
        trs[i] = tr[i - N + 1:i + 1].sum(); hh[i] = h[i - N + 1:i + 1].max(); ll[i] = l[i - N + 1:i + 1].min()
    rng = hh - ll
    with np.errstate(divide='ignore', invalid='ignore'):
        ci = 100 * np.log10(trs / rng) / np.log10(N)
    ci[~(rng > 0)] = np.nan
    return ci


def mask_fn(frames, ix, side, variant):
    out = {}
    for s in side:
        ci = _ci(frames[s]); i = np.asarray(ix[s]); ok = i >= 0
        v = np.full(len(i), np.nan); v[ok] = ci[np.clip(i, 0, len(ci) - 1)][ok]
        out[s] = np.nan_to_num(v, nan=np.inf) < variant['max_ci']
    return out


def build_fn(ctx, variant):
    from high_cagr import chop_harness as h
    from high_cagr import fb_harness as fh
    sig = h.base_sig(); m = mask_fn(ctx['frames'], ctx['ix'], ctx['side'], variant)
    for k, s in enumerate(fh.SYMBOLS):
        sig[k, ~np.asarray(m[s], bool), 0] = 0
    return {'sig': sig}


if __name__ == '__main__':
    from high_cagr import fb_harness
    print(fb_harness.check_causal(mask_fn, VARIANTS['A']), flush=True)
    ctx = fb_harness.load()
    for v, var in VARIANTS.items():
        m = mask_fn(ctx['frames'], ctx['ix'], ctx['side'], var)
        kept = sum(int(((ctx['side'][s] != 0) & m[s]).sum()) for s in fb_harness.SYMBOLS)
        tot = sum(int((ctx['side'][s] != 0).sum()) for s in fb_harness.SYMBOLS)
        print(f'variant {v}: signal bars kept {kept}/{tot} = {kept/tot*100:.1f}%', flush=True)
    from high_cagr import chop_harness as h
    h.run_idea('chop_index', VARIANTS, build_fn, notes='Choppiness Index(14) on 4h frame at ix; NaN/zero range -> blocked; A<61.8, B<50. Zeroes sig side column where not allowed.')
