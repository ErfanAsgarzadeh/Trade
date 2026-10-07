"""POST-HOC robustness of idea 2A: neighbouring thresholds and median windows (not pre-declared)."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench
def build(ctx,v):
    sig=bench.base_sig()
    for j,s in enumerate(bench.SYMBOLS):
        f=ctx['frames'][s];ix=ctx['ix'][s];md=f.atr.rolling(v['win']).median().shift(1).to_numpy()[ix];r=f.atr.to_numpy()[ix]/md
        low=~(np.isfinite(r)&(r>=v['thr']));on=sig[j,:,0]!=0;sig[j,on&low,0]=0;sig[j,on&low,3]=-np.inf
    return dict(sig=sig)
if __name__=='__main__':
    V={f"thr{t}_win{w}":dict(thr=t,win=w) for t in (0.9,0.95,1.0,1.05,1.1,1.2) for w in (40,60,90)}
    bench.run_idea('posthoc_atr_sensitivity',V,build,notes='POST-HOC neighbourhood of idea 2A')
