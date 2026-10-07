import numpy as np, pandas as pd
VARIANTS = {'A': {'kind': 'daily_ema20', 'span': 20, 'slope_lag': 5, 'min_days': 25},
            'B': {'kind': 'mid100', 'window': 100}}
H4 = 4 * 3600 * 1000; DAY = 86400000

def _mask_A(f, ix, side, v):
    ts = f.timestamp.to_numpy(np.int64); cl = f.close.to_numpy(float)
    last = np.where((ts % DAY) == 20 * 3600 * 1000)[0]   # row of each day's final 4h bar (day complete)
    dclose = cl[last]
    ema = pd.Series(dclose).ewm(alpha=2 / (v['span'] + 1), adjust=False).mean().to_numpy()
    r = np.asarray(ix)
    k = np.searchsorted(last, r, side='right') - 1       # last completed day whose final bar row <= r
    ok = k + 1 >= v['min_days']
    kc = np.clip(k, v['slope_lag'], None)
    c, e, e5 = dclose[np.clip(k, 0, None)], ema[np.clip(k, 0, None)], ema[kc - v['slope_lag']]
    up = (c > e) & (e > e5); dn = (c < e) & (e < e5)
    return ok & ((side > 0) & up | (side < 0) & dn)

def _mask_B(f, ix, side, v):
    w = v['window']
    hi = f.high.rolling(w).max().to_numpy(); lo = f.low.rolling(w).min().to_numpy(); cl = f.close.to_numpy()
    r = np.asarray(ix); mid = (hi[r] + lo[r]) / 2; c = cl[r]
    ok = ~np.isnan(mid)
    return ok & ((side > 0) & (c > mid) | (side < 0) & (c < mid))

def mask_fn(frames, ix, side, variant):
    fn = _mask_A if variant['kind'] == 'daily_ema20' else _mask_B
    return {s: np.asarray(fn(frames[s], ix[s], np.asarray(side[s]), variant), bool) for s in side}

if __name__ == '__main__':
    import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from high_cagr import fb_harness as h
    h.run_method('htf_trend', VARIANTS, mask_fn, notes='A: last completed UTC day (final 4h bar at 20:00 UTC present, row<=signal row), daily EMA20 alpha=2/21, close vs EMA and EMA vs EMA 5 completed days earlier, >=25 days. B: close vs midpoint of 100-bar HL range incl. current row.')
