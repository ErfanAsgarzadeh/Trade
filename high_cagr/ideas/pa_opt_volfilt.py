"""pa_opt_volfilt: volatility filters on the PA sleeve (4h KEYREV, TP2, 30-bar stop).

HYPOTHESIS. KEYREV pays when the signal bar is a real, expanded-range reversal in a normal-to-active volatility regime.
Reversals on compressed bars (small range vs ATR, ATR below its recent norm, tight stop) are noise: tight stops get
hit by ordinary noise and costs eat the 2R target. Extreme-ATR (panic) regimes may also be bad (gaps, no reversal).
MECHANISM. Skip (or half-size) signals in the weak volatility buckets; fewer, better trades; cost/stop-noise drag falls.

TRAIN-ONLY DIAGNOSTIC (baseline trades 2021-10..2024-12 on OTHER20, 1104 trades, quintiles, mean R): everything is noisy
and mostly non-monotonic; the only consistent pattern is the weakest bottom bucket: atr_rel<0.82 -> R -0.067,
range/ATR<1.09 -> -0.045, stop/ATR<1.2 -> -0.045, stop% <2.8 -> -0.027 (next bucket also -0.073), top atr_rel
quintile >1.16 -> -0.023. No monotone edge; the diagnostic only fixes the cut points below (rounded).

Features (causal, bar t = signal bar): atr_rel = ATR[t]/median(ATR[t-60..t-1]); rng = (high-low)/ATR[t];
stop% = |entry level - stop| / entry level.
VARIANTS (fixed):
 A skip_atr_low   skip if atr_rel < 0.85
 B skip_rng_small skip if rng < 1.1
 C skip_stop_tight skip if stop% < 3.0
 D skip_atr_high  skip if atr_rel > 1.3
 E skip_A_or_B    skip if A or B
 F half_A_or_B    risk x0.5 if A or B
 G half_tails     risk x0.5 if A or B or D
 H skip_A_B_C     skip if A or B or C
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np,pandas as pd
from high_cagr.ideas import pabench as PB

VARIANTS={'A_skip_atr_low':dict(m='skip',a=.85),'B_skip_rng_small':dict(m='skip',r=1.1),'C_skip_stop_tight':dict(m='skip',s=3.0),
    'D_skip_atr_high':dict(m='skip',ah=1.3),'E_skip_A_or_B':dict(m='skip',a=.85,r=1.1),'F_half_A_or_B':dict(m='half',a=.85,r=1.1),
    'G_half_tails':dict(m='half',a=.85,r=1.1,ah=1.3),'H_skip_A_B_C':dict(m='skip',a=.85,r=1.1,s=3.0)}

def fn(d,v):
    a=d['atr'];n=len(a);med=pd.Series(a).rolling(60).median().shift(1).to_numpy()
    with np.errstate(all='ignore'):
        rel=a/med;rng=(d['h']-d['l'])/a;lev=d['sig']['lev'][:n];stp=np.abs(lev-d['sig']['stp'][:n])/lev*100
    bad=np.zeros(n,bool)
    if 'a' in v:bad|=~(rel>=v['a'])
    if 'r' in v:bad|=~(rng>=v['r'])
    if 's' in v:bad|=~(stp>=v['s'])
    if 'ah' in v:bad|=(rel>v['ah'])
    if v['m']=='skip':return PB.run(d,side=np.where(bad,0,d['sig']['side']).astype(np.int8))
    return PB.run(d,mult=np.where(bad,.5,1.))

def main():PB.run_idea('volfilt',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
