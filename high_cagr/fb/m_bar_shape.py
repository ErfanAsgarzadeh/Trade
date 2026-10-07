"""bar_shape: A = range <= 2.5*ATR; B = body >= 50% of range and bar closes in trade direction."""
import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
import numpy as np
VARIANTS={'A':{'max_range_atr':2.5},'B':{'min_body_frac':0.5}}

def mask_fn(frames,ix,side,variant):
    out={}
    for s,fr in frames.items():
        r=np.asarray(ix[s]);sd=np.asarray(side[s])
        o,h,l,c,a=[fr[k].to_numpy(float)[r] for k in ('open','high','low','close','atr')]
        rng=h-l
        with np.errstate(invalid='ignore'):
            ok=np.isfinite(rng)&(rng>0)
            if 'max_range_atr' in variant:
                m=ok&np.isfinite(a)&(rng<=variant['max_range_atr']*a)
            else:
                body=np.abs(c-o);dirn=((sd>0)&(c>o))|((sd<0)&(c<o))
                m=ok&np.isfinite(body)&(body>=variant['min_body_frac']*rng)&dirn
        out[s]=np.asarray(m,bool)
    return out

if __name__=='__main__':
    from high_cagr import fb_harness as h
    h.run_method('bar_shape',VARIANTS,mask_fn,notes='A: range<=2.5*ATR of signal row; B: body>=50% range and close in trade direction (side[sym][b]); high==low/NaN -> disallowed.')
