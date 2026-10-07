"""Idea 1_volume (pre-declared): vol_rel = signal-bar volume / mean volume of the 20 closed 4h bars before it.
A: skip entry if vol_rel < 1.5.  B: half root risk if vol_rel < 1.5.  NaN / zero mean -> treated as low volume."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import bench

THRESH=1.5

def vol_rel(ctx):
    out=[]
    for s in ctx['symbols']:
        v=ctx['frames'][s]['volume'].astype(float)
        mean20=v.rolling(20,min_periods=20).mean().shift(1)  # rows ix-20..ix-1
        rel=(v/mean20.where(mean20>0)).to_numpy()
        ix=np.asarray(ctx['ix'][s]);r=np.full(ix.shape,np.nan);ok=(ix>=0)&(ix<len(rel))
        r[ok]=rel[ix[ok]];out.append(r)
    return np.stack(out)  # (n_sym, n_bars); NaN = low volume

def build(ctx,variant):
    sig=bench.base_sig();vr=vol_rel(ctx)
    low=~(vr>=THRESH)  # NaN -> low
    if variant['mode']=='skip':
        sig[:,:,0]=np.where(low&(sig[:,:,0]!=0),0.,sig[:,:,0])
    else:
        mult=np.where(low,0.5,1.0)[:,:,None]
        sig=np.concatenate([sig,np.ones_like(sig[:,:,:1])],axis=2);sig[:,:,4:5]=mult
    return dict(sig=sig)

if __name__=='__main__':
    bench.run_idea('idea1_volume',{'A':{'mode':'skip','thresh':THRESH},'B':{'mode':'half_risk','thresh':THRESH}},build,
                   notes='vol_rel = volume[ix] / mean(volume[ix-20..ix-1]) on closed 4h bars; NaN/zero mean -> low. '
                         'A: side=0 where vol_rel<1.5. B: risk col 4 = 0.5 where vol_rel<1.5 else 1.0.')
