"""pa2_mtf -- multi-timeframe context for the 4h KEYREV trigger (written and declared BEFORE any variant was run).

HYPOTHESIS. Discretionary price-action traders read a 4h signal through higher-timeframe (HTF) context: daily trend and
daily/weekly support-resistance. Two opposite priors exist:
  (a) literature (Bulkowski, TSMOM): a key reversal should be taken only WITH the daily trend (pullback end);
  (b) anatomy diagnostician: C1 pays as an exhaustion reversal, so it should be taken at HTF extremes / against the trend.
MECHANISM. The 4h trigger, entry, stop, 1.1-ATR range filter and the 30-bar time-stop exit are exactly C1 (pabench.run with
target_r=0, side = pabench2.c1_side). Only a per-signal skip (side=0) or risk multiplier (mult) is added, computed from
daily bars built from the coin's own minute data (Q.bars(d,1440), truncation-safe) using ONLY daily bars fully closed at
the close of the 4h signal bar t: last = (t+1)*240//1440 - 1. Weeks are Monday-aligned groups of those closed days.
  dist_20 = distance of the signal-bar extreme from the 20-day extreme on the trade side, in daily ATR14 (Wilder):
            long (low - lowest low of the last 20 closed days)/dATR, short (highest high - high)/dATR.
  dist_pw = same vs the prior completed week's low (long) / high (short).
  ctr     = last closed daily close is on the opposite side of its daily EMA50 from the trade (counter-trend).
  NaN features (warm-up) count as False.

TRAIN-ONLY PRE-PASS (C1 trade list, OTHER20, entries < 2025-01-01, 841 trades, net +36.4% at 0.5% risk; split at the
median entry time into halves H1/H2 = +40.0 / -3.6). No validation or IN15 number was computed or looked at.
  dist_20 <= 1.0 dATR       385 trades net +37.8 (H1 19.8 / H2 18.0)   rest 456 trades -1.4 (20.1 / -21.5)
  dist_pw <= 0.5 dATR       455 trades +29.4 (13.2 / 16.1)             dist_pw > 2 dATR: 107 trades -11.9
  counter daily EMA50       493 trades +32.5 (30.1 / 2.4)              WITH daily EMA50 348 trades +3.9 (9.9 / -6.0)
  Donchian 20/50/100-day midline votes: all 3 against the trade +29.2 on 334; all 3 with the trade -1.7 on 230.
  dist_20<=1 & counter      329 trades +25.9 (8.3 / 17.6);  dist_20<=1 OR dist_pw<=0.5  507 trades +35.1 (20.7 / 14.4)
  sizing 1.5x if dist_20<=1 else 0.5x: +56.0 (39.8 / 16.2);  score 0.5+0.5*[dist_20<=1]+0.5*[ctr]: +53.3 (44.9 / 8.4)
  Not useful in train: prior-day sweep (sweeping the prior-day extreme is the norm, 676/841, and worse), daily EMA20
  slope, close vs the weekly open, position within the 20-day range. ~10 features were looked at -> multiple-testing risk.
  Train already contradicts prior (a): WITH-trend KR is the weak half. It is still run (V6) as the declared test.
  Caveat: re-cuts ignore that a skipped trade frees the coin for another signal; the engine run accounts for that.

VARIANTS (fixed parameters; 8):
  V1 LOC20      skip unless dist_20 <= 1.0              (KR at the 20-day / daily S-R extreme)
  V2 LOC20_SZ   mult 1.5 if dist_20 <= 1.0 else 0.5     (size instead of skip; keeps trade count)
  V3 LOCPW      skip unless dist_pw <= 0.5              (KR at the prior-week extreme)
  V4 LOC_ANY    skip unless dist_20 <= 1.0 or dist_pw <= 0.5
  V5 CTR        skip unless counter to the daily EMA50 trend
  V6 WITH       skip unless WITH the daily EMA50 trend  (literature prior; expected to fail)
  V7 LOC20_CTR  skip unless dist_20 <= 1.0 and counter-trend
  V8 SCORE      mult = 0.5 + 0.5*[dist_20 <= 1.0] + 0.5*[ctr]  (0.5 / 1.0 / 1.5)
PREDICTION. V1/V2/V4 pass Q1 (train-selected); the honest test is Q2 (valid) and Q3 (IN15). V6 fails Q1. If the
location filters fail Q3, HTF location is a train artifact and C1 stays.
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np,pandas as pd
from high_cagr.ideas import pabench2 as Q, pabench as PB

VARIANTS={'V1_LOC20':dict(kind='skip',rule='l20'),'V2_LOC20_SZ':dict(kind='size',rule='l20'),'V3_LOCPW':dict(kind='skip',rule='pw'),
          'V4_LOC_ANY':dict(kind='skip',rule='l20|pw'),'V5_CTR':dict(kind='skip',rule='ctr'),'V6_WITH':dict(kind='skip',rule='with'),
          'V7_LOC20_CTR':dict(kind='skip',rule='l20&ctr'),'V8_SCORE':dict(kind='score',rule='l20+ctr')}
D20,DPW=1.0,0.5

def context(d):
    """Per 4h bar t (signal bar): dist_20, dist_pw (daily ATR units, trade-side for long and short) and daily EMA50 side,
    all from daily bars fully closed at the close of bar t."""
    o,h,l,c=Q.bars(d,1440);nd=len(c);n=d['n']
    side=Q.c1_side(d);t=np.arange(n);last=(t+1)*240//1440-1;ok=(last>=0)&(last<nd);L=np.clip(last,0,max(nd-1,0))
    nan=np.full(n,np.nan)
    if nd==0:return nan,nan,nan,nan,nan
    e50=Q.ema(c,50);a=Q.atr14(h,l,c)
    hh20=pd.Series(h).rolling(20).max().to_numpy();ll20=pd.Series(l).rolling(20).min().to_numpy()
    wk=(np.arange(nd)+1)//7                                   # day 0 = 2021-10-05 (Tuesday); Monday-aligned week id
    W=pd.DataFrame({'w':wk,'h':h,'l':l}).groupby('w').agg(h=('h','max'),l=('l','min'))
    curw=(L+1+1)//7                                           # week of the day that is forming at bar t's close
    pwh=W.h.reindex(curw-1).to_numpy();pwl=W.l.reindex(curw-1).to_numpy()
    dA=np.where(ok,a[L],np.nan)
    d20l=(d['l'][:n]-ll20[L])/dA;d20s=(hh20[L]-d['h'][:n])/dA
    dpwl=(d['l'][:n]-pwl)/dA;dpws=(pwh-d['h'][:n])/dA
    up=np.where(ok,np.where(c[L]>e50[L],1.,-1.),np.nan)
    return d20l,d20s,dpwl,dpws,up

def fn(d,variant):
    side=Q.c1_side(d);n=len(side);d20l,d20s,dpwl,dpws,up=context(d)
    d20=np.where(side==1,d20l,d20s);dpw=np.where(side==1,dpwl,dpws)
    l20=np.nan_to_num(d20,nan=9e9)<=D20;pw=np.nan_to_num(dpw,nan=9e9)<=DPW
    tr=np.nan_to_num(up)*side;ctr=tr<0;wth=tr>0
    r=variant['rule'];k=variant['kind']
    if k=='skip':
        keep={'l20':l20,'pw':pw,'l20|pw':l20|pw,'ctr':ctr,'with':wth,'l20&ctr':l20&ctr}[r]
        s=side.copy();s[~keep]=0;return PB.run(d,side=s,target_r=0.)
    mult=np.where(l20,1.5,.5) if k=='size' else .5+.5*l20+.5*ctr
    return PB.run(d,side=side,mult=mult,target_r=0.)

if __name__=='__main__':
    Q.run_idea('mtf',VARIANTS,fn,notes=__doc__)
