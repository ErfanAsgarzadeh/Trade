"""False-breakout filter 'confirmation' (A: previous bar also closed beyond its breakout level; B: penetration >= 0.25 ATR)."""
import numpy as np

VARIANTS = {'A': {'mode': 'prev_bar_breakout'}, 'B': {'mode': 'penetration', 'atr_mult': 0.25}}


def mask_fn(frames, ix, side, variant):
    out = {}
    for s, sd in side.items():
        f = frames[s]
        c, dh, dl = f['close'].to_numpy(float), f['donchian_high_10'].to_numpy(float), f['donchian_low_10'].to_numpy(float)
        kt, kb, atr = f['kumo_top'].to_numpy(float), f['kumo_bottom'].to_numpy(float), f['atr'].to_numpy(float)
        i = np.asarray(ix[s]).astype(int)
        if variant['mode'] == 'prev_bar_breakout':
            lng = (c > dh) & (c > kt)
            sht = (c < dl) & (c < kb)
            j = i - 1
            ok = j >= 0
            jj = np.clip(j, 0, len(c) - 1)
            lg, st = lng[jj] & ok, sht[jj] & ok
        else:
            ii = np.clip(i, 0, len(c) - 1)
            ok = i >= 0
            m = variant['atr_mult']
            with np.errstate(invalid='ignore'):
                lg = (c[ii] - np.maximum(dh[ii], kt[ii]) >= m * atr[ii]) & ok
                st = (np.minimum(dl[ii], kb[ii]) - c[ii] >= m * atr[ii]) & ok
        out[s] = np.where(sd > 0, lg, np.where(sd < 0, st, True)).astype(bool)
    return out


if __name__ == '__main__':
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from high_cagr import fb_harness as h
    h.run_method('confirmation', VARIANTS, mask_fn, notes='A: prev closed bar also beyond own Donchian10+Kumo; B: penetration >=0.25 ATR beyond max/min(donchian, kumo). NaN -> disallowed.')
