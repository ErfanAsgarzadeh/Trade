"""R3 batch 2 (lead, after the team meeting). Funding robustness. VARIANTS declared before running:
 F1_pct80_fix : A2-B (7d mean funding vs the symbol's own trailing 180d distribution, block long > 80th pct, short < 20th pct)
                with the warm-up artefact fixed: while fewer than 60d of history exist the signal is ALLOWED, not blocked.
 F2_pct90_fix : same, 90/10 (neighbour, rarer).
 F3_pct70_fix : same, 70/30 (neighbour, more frequent).
 F4_short_neg : first-principles crowding on the short side only: block shorts when the 3d mean funding < 0 (shorts paying
                longs = crowded shorts). Longs untouched.
Falsification (declared): F1 must pass the bench gate AND its 3-universe mean Calmar must exceed the random-thinning null
p90 for the matching thinning level; F2 and F3 must each be within 0.03 mean Calmar of F1 or pass themselves. Otherwise
the A2-B pass is treated as thinning + warm-up artefact. Any survivor still needs the fresh 10-symbol holdout."""
import numpy as np, pandas as pd
from high_cagr import r3_harness as h
from high_cagr.fb.r3_a2_positioning import fund_avg
VARIANTS={'F1_pct80_fix':dict(kind='pct',n=21,q=.2,win=1080),
          'F2_pct90_fix':dict(kind='pct',n=21,q=.1,win=1080),
          'F3_pct70_fix':dict(kind='pct',n=21,q=.3,win=1080),
          'F4_short_neg':dict(kind='short',n=9,lo=0.)}
def build_fn(U,var):
    sig=U['sig'].copy()
    for k,s in enumerate(U['symbols']):
        side=sig[k,:,0]
        if var['kind']=='pct':
            a=fund_avg(U,k,var['n']);sr=pd.Series(a)
            lo=sr.rolling(var['win'],min_periods=360).quantile(var['q']).shift(1).to_numpy()
            hi=sr.rolling(var['win'],min_periods=360).quantile(1-var['q']).shift(1).to_numpy()
            bad=((side>0)&(a>hi))|((side<0)&(a<lo))          # NaN comparisons are False -> allowed
        else:
            a=fund_avg(U,k,var['n']);bad=(side<0)&(a<var['lo'])
        sig[k,bad&(side!=0),0]=0
    return dict(sig=sig)
if __name__=='__main__':
    h.run_method('r3_lead_funding_b2','fb',VARIANTS,build_fn,notes='batch 2 after meeting: warm-up fixed A2-B, neighbours, short-side crowding')
