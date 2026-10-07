"""A1 entry mechanics (target fb). Variants declared before running:
 A  retest limit at breakout level (bb 8/9), valid 3 bars (12h), stop = level -/+ 2.0 ATR (same distance as baseline, anchored at the level)
 B  same limit, but keep baseline stop (2 ATR from signal close) -> smaller distance, larger size at same % risk
 C  market entry, stop anchored to structure: level -/+ 1.0 ATR (invalidation = full ATR back through the level); sig-only
 D  limit halfway between level and signal close (50% pullback of the penetration), 3 bars, stop level -/+ 2.0 ATR
"""
import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]));sys.path.insert(0,str(pathlib.Path(__file__).parent))
import numpy as np
from high_cagr import r3_harness as h
from high_cagr.fb import r3k_a1
VARIANTS={'A':dict(kind='limit',frac=0.,stop_atr=2.),'B':dict(kind='limit',frac=0.,stop_atr=0.),
          'C':dict(kind='stop',stop_atr=1.),'D':dict(kind='limit',frac=.5,stop_atr=2.)}
def build_fn(U,v):
    if v['kind']=='limit':
        return dict(simulate=r3k_a1.simulate,kwargs=dict(retest_bars=3,retest_frac=v['frac'],retest_stop_atr=v['stop_atr']))
    sig=U['sig'].copy();bb=U['bb'];sd=sig[:,:,0]
    lvl=np.where(sd>0,bb[:,:,8],bb[:,:,9]);st=lvl-sd*v['stop_atr']*bb[:,:,1]
    ok=(sd!=0)&np.isfinite(st)
    sig[:,:,2]=np.where(ok,st,sig[:,:,2]);sig[:,:,0]=np.where((sd!=0)&~np.isfinite(st),0,sd)
    return dict(sig=sig)
if __name__=='__main__':
    h.run_method('r3_a1_entry','fb',VARIANTS,build_fn,notes='retest limit / structure stop')
