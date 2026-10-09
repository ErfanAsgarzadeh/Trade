"""pa2_confluence - CONFLUENCE SCORE ("A+ setups") for Ghoghnous C1. Pre-declared before any variant of this file was run,
and before any validation (2025+) or IN15 number for these factors was looked at.

HYPOTHESIS. Discretionary price-action traders do not take every key reversal the same: they size up the A+ setups where
several independent conditions agree and skip the C setups. If C1's thin edge (+0.087R per train trade, fat tail) is
concentrated in signals where the context is right, a causal confluence score at the signal bar should (a) let us skip
the losing low-score signals and/or (b) move risk from low-score to high-score signals at the SAME average risk, which
raises mean R per unit risk and Calmar on TRAIN, VALID and IN15.

MECHANISM. Signal = C1 unchanged (pabench2.c1_side, buy/sell stop at the extreme, stop beyond the bar, no target, 30-bar
time stop). At the signal bar t (all inputs known at t's close; only this coin's own bars and BTC's 4h bars up to t):
  F1 VOL   volrank < 0.354      volrank = share of the previous 500 4h bars whose ATR14/close is below bar t's (low vol)
  F2 EXH   slope < 0.146        slope = side*(EMA50[t]-EMA50[t-6])/ATR[t]  (EMA50 NOT already running in trade direction)
  F3 BAR   size >= 1.476        size = (high-low)/ATR of the signal bar (bar quality: decisive outside bar)
  F4 MKT   btc6 < 0.0114        btc6 = side*(BTC close[t]/BTC close[t-6]-1)  (BTC not already up 1.1%+ in trade direction)
score = F1+F2+F3+F4 in 0..4 (NaN -> factor 0). Cut-offs are TRAIN quantiles of the C1 train trades on OTHER20 (q40 for
volrank and size, q80 for slope and btc6), fixed here. Risk per signal = 0.5% x mult[score]; mult 0 = skip (coin stays free).
"Same average risk" multipliers are normalised so the mean mult over the 841 C1 TRAIN trades equals 1 (train score counts
0..4 = 9/68/289/371/104).

TRAIN-ONLY PRE-PASS (OTHER20, C1 trades with entry < 2025-01-01, 841 trades, mean +0.087R; H1/H2 = halves of train by
entry date; scripts in the session scratchpad conf/prepass*.py). Mean net R by train quintile (low -> high):
  volrank   +0.433 / +0.128 / -0.002 / +0.007 / -0.093   (lowest quintile best in both halves: H1 0.40, H2 0.49)
  slope     +0.132 / +0.078 / +0.165 / +0.187 / -0.130   (top quintile worst in both halves)
  ret60     +0.158 / +0.136 / +0.108 / +0.068 / -0.038   (Spearman 0.82 with slope, 0.97 stretch -> redundant, not used)
  size      -0.010 / -0.011 / +0.240 / +0.153 / +0.061   (two lowest quintiles weak in both halves)
  btc6      +0.247 / -0.024 / +0.127 / +0.156 / -0.079   (top quintile worst in both halves)
  relvol, close location, BTC vs EMA50: flat or sign flips between halves -> not used.
  level (20/50/100/200-bar extreme count): Spearman -0.67 with slope, non-monotone -> not used.
  cross-coin same-side breadth (t-2..t): non-monotone in train (0: +0.09, 1: -0.11, 2: +0.29, 3-4: +0.06, 5+: +0.15),
     H2 of 3-4 others = -0.51 -> not used (it looked good in VALID per the anatomy report, which we must not use).
  In-sample score (cut-offs fitted on these same trades, so OPTIMISTIC): score 0: 9 tr -0.03R | 1: 68 tr -0.25 |
     2: 289 tr -0.10 | 3: 371 tr +0.15 | 4: 104 tr +0.61 ; score 4 positive in every train year (2021-2024).
  CAVEAT declared up front: about 12 factors were looked at on train and 4 kept; in-sample monotonicity is guaranteed
  by construction. VALID and IN15 are the only honest judges.

VARIANTS (fixed; mult indexed by score 0..4):
  skip_le1   mult [0,0,1,1,1]                         skip C setups (score <= 1), others at normal risk
  skip_le2   mult [0,0,0,1,1]                         trade only score >= 3
  aplus_only mult [0,0,0,0,1]                         A+ only (score 4)
  tilt       mult [0,0,.5,1,2] x 1.1624               skip <=1, half at 2, double at 4, same average risk
  lin        mult score x 0.38667                     risk proportional to score, same average risk
  aplus2     mult [0,0,0,1,2] x 1.4525                skip <=2, A+ double, same average risk
  vol_only   mult F1 only ([0,1] on volrank<0.354)    control: is the score more than its best single factor?
  lin_med    mult score_med x 0.50511                 robustness: same 4 factors, cut-offs at train MEDIANS
                                                      (volrank<0.469, slope<-0.2444, size>=1.5905, btc6<-0.000269)
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from numba import njit
from high_cagr.ideas import pabench2 as Q, pabench as PB

CUT=dict(q=(.354,.146,1.476,.0114),med=(.469,-.24444157520568818,1.590499397178143,-.0002686303014980407))
VARIANTS={'skip_le1':('q',[0,0,1,1,1]),'skip_le2':('q',[0,0,0,1,1]),'aplus_only':('q',[0,0,0,0,1]),
          'tilt':('q',[x*1.162404975812025 for x in (0,0,.5,1,2)]),'lin':('q',[x*.38666666666666666 for x in range(5)]),
          'aplus2':('q',[x*1.4525043177892918 for x in (0,0,0,1,2)]),'vol_only':('vol',[0,1]),
          'lin_med':('med',[x*.5051051051051051 for x in range(5)])}

@njit(cache=True)
def prank(x,w):
    n=len(x);out=np.full(n,np.nan)
    for t in range(w,n):
        v=x[t];c=0;k=0
        for j in range(t-w,t):
            if x[j]==x[j]:
                k+=1
                if x[j]<v:c+=1
        if k>0:out[t]=c/k
    return out

def feats(d,side):
    n=d['n'];h,l,c,a,e50=(d[k][:n] for k in ('h','l','c','atr','e50'));bc=d['btc']['c'][:n]
    vr=prank(a/c,500)
    sl=np.full(n,np.nan);sl[6:]=(e50[6:]-e50[:-6])/a[6:];sl*=side
    sz=(h-l)/a
    b6=np.full(n,np.nan);b6[6:]=bc[6:]/bc[:-6]-1;b6*=side
    return vr,sl,sz,b6

def fn(d,variant):
    kind,w=variant;side=Q.c1_side(d);vr,sl,sz,b6=feats(d,side)
    with np.errstate(invalid='ignore'):
        if kind=='vol':score=(vr<CUT['q'][0]).astype(int)
        else:
            c=CUT[kind];score=(vr<c[0]).astype(int)+(sl<c[1]).astype(int)+(sz>=c[2]).astype(int)+(b6<c[3]).astype(int)
    mult=np.asarray(w,float)[score];mult[side==0]=0.
    return PB.run(d,side=side,mult=mult,target_r=0.)

if __name__=='__main__':
    Q.run_idea('confluence',VARIANTS,fn,notes=__doc__)
