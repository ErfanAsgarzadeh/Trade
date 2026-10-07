"""r3_a5_stat: statistical regime masks. Exploration (OLD5 H1 only) found no measure with clear separation (max AUC 0.564 for r2_30);
thresholds are OLD5-H1 percentiles of the measure at entry, fixed constants. Blocks sig[:,:,0] where not allowed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr.fb.r3_a5_measures import measures
VARIANTS = {
 'A_r2_30_ge_0.034': {'r2_30': 0.034},   # block bottom-20% (H1) R2 of 30-bar log-price fit: no linear trend
 'B_r2_30_ge_0.07': {'r2_30': 0.07},     # block bottom-30%
 'C_ac6_ge_-0.15': {'ac6': -0.15},       # block strong lag-6 negative autocorrelation (mean-reverting, 120 bars)
 'D_r2_and_ac6': {'r2_30': 0.034, 'ac6': -0.15},
}
_cache = {}
def _m(sym, frame):
    k = (sym, len(frame), float(frame['close'].iloc[-1]))
    if k not in _cache: _cache[k] = measures(frame['close'])
    return _cache[k]
def build_fn(U, variant):
    sig = U['sig'].copy()
    for k, s in enumerate(U['symbols']):
        m = _m(s, U['frames'][s]); i = np.asarray(U['ix'][s]); ok = np.ones(len(i), bool)
        for name, thr in variant.items():
            v = np.full(len(i), np.nan); g = i >= 0; v[g] = m[name][i[g]]
            ok &= np.nan_to_num(v, nan=-9.) >= thr  # NaN (warm-up) blocked
        sig[k, ~ok, 0] = 0
    return {'sig': sig}
if __name__ == '__main__':
    from high_cagr import r3_harness as h
    h.run_method('r3_a5_stat', 'chop', VARIANTS, build_fn, notes='R2(30) of log-price fit and lag-6 autocorr(120) of 4h returns as entry masks; thresholds = OLD5-H1 20/30th percentiles. Weak exploration separation (AUC<=0.56).')
