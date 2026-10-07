"""Idea 2 (pre-declared): ATR regime filter.
atr_rel = ATR of signal bar / median ATR of the 60 closed 4h bars before it (rows ix-60..ix-1). NaN -> low (<1).
A: skip entry if atr_rel < 1.0.  B: half root risk if atr_rel < 1.0."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import bench

def atr_rel(ctx):
    out=[]
    for s in ctx['symbols']:
        f=ctx['frames'][s];a=f['atr'].astype(float)
        med=a.rolling(60).median().shift(1).to_numpy()
        ix=np.asarray(ctx['ix'][s]);ok=ix>=0;ixc=np.clip(ix,0,len(f)-1)
        r=a.to_numpy()[ixc]/med[ixc];r[~ok]=np.nan
        out.append(r)
    return np.stack(out)  # (n_sym, n_bars)

def build(ctx,variant):
    sig=bench.base_sig();rel=atr_rel(ctx)[:,:sig.shape[1]]
    low=~(rel>=variant['thr'])  # NaN -> low
    has=sig[:,:,0]!=0
    if variant['mode']=='skip':
        sig[has&low,0]=0.
        return dict(sig=sig)
    mult=np.where(low,variant['mult'],1.0)[:,:,None]
    return dict(sig=np.concatenate([sig,mult],axis=2))

if __name__=='__main__':
    bench.run_idea('idea2_atr_regime',{'A':dict(mode='skip',thr=1.0),'B':dict(mode='half',thr=1.0,mult=0.5)},build,
        notes='atr_rel = frame atr at ix / rolling(60).median().shift(1) at ix (rows ix-60..ix-1); NaN treated as low. '
              'A: drop signal if atr_rel<1. B: col4 risk multiplier 0.5 if atr_rel<1 else 1.')
