"""pa_opt_regime: regime and hedge behaviour of the PA sleeve (4h KEYREV, TP2, 30-bar stop) on OTHER20.

HYPOTHESIS. PA is ~uncorrelated with the other two bots (TWO = main trend + C3), so its value to the account may be a hedge:
size it up when TWO is in a drawdown (when diversifying P&L is most valuable), down when TWO is at a high; and PA, a
reversal strategy, may work better when BTC regime is bearish / when entries are aligned with the BTC 200-EMA side.
MECHANISM. mult array per 4h bar t (risk multiplier on the 0.15% sleeve risk), from information known at the close of signal
bar t: TWO daily equity over COMPLETE days before bar t closes (days 0..D-1, D=(t+1)*240//1440) and BTC 4h close/EMA200 at bar t.

TRAIN-ONLY DIAGNOSTIC (baseline OTHER20 trades, entry < 2024-12-31, 1104 trades, mean R 0.046; decision features at entry-bar start):
 TWO drawdown at entry: ==0 (new high): n70 meanR -0.338 | (0,5%]: n166 +0.218 | (5,10%]: n248 -0.259 | (10,20%]: n529 +0.107 | >20%: n91 +0.498
   (non-monotone, but new-high is clearly worst and the deepest bucket best; TWO is in DD>10% on 52% of train days, >5% on 76%)
 TWO trailing 30d return quartiles: lowest(<-3.1%) +0.269 | -0.090 | +0.131 | highest(>11.7%) -0.126 (weak: negative-30d better)
 BTC close>EMA200: up n597 -0.003 vs down n507 +0.102. BTC EMA50>EMA200: -0.016 vs +0.112.
 side x BTC: short&BTC up n324 -0.084 (the bad cell); short&down +0.126; long&up +0.094; long&down +0.077.
 aligned with BTC EMA200 side (long when up, short when down): n538 +0.110 vs misaligned n566 -0.015.
 BTC ATR/price vs own 180-bar median, quartiles: +0.255, -0.033, -0.108, +0.070 (U-shape, no usable monotone rule).
 Year: 2021 +0.008 (n49), 2022 +0.214, 2023 -0.174, 2024 +0.092. Month: noisy, no seasonal rule used.
 Diagnostic cues are mild and non-monotone; variants below are mechanism-driven with round parameters.

VARIANTS (fixed; DD = 1 - TWO equity / running max, TWO = bot + c3 daily series):
 A hedge15      mult 1.5 if DD>10% else 1
 B hedge2       mult 2.0 if DD>10% else 1
 C hedge_tier   mult 1.0 (DD<=10%), 1.5 (10-20%), 2.0 (>20%)
 D high_cut     mult 0.5 if DD<2% (TWO at/near new high) else 1
 E hedge_both   mult 1.5 if DD>10%, 0.5 if DD<2%, else 1
 F btc_align    mult 0.5 for trades misaligned with BTC close vs EMA200 (long when BTC<EMA200, short when BTC>EMA200), else 1
 G skip_short_up  drop shorts while BTC close>EMA200 (no mult)
 H hedge_align  A x F
Report-only: mean daily PA (0.15%) and TWO return on TRAIN days split by TWO DD>10% vs not (hedge check, not a variant).
Gates: pabench P1-P5. Run once; no tuning.
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr.ideas import pabench as PB

VARIANTS={'A_hedge15':dict(k='dd',a=1.5),'B_hedge2':dict(k='dd',a=2.0),'C_hedge_tier':dict(k='tier'),'D_high_cut':dict(k='hi'),
    'E_hedge_both':dict(k='both'),'F_btc_align':dict(k='al'),'G_skip_short_up':dict(k='skip'),'H_hedge_align':dict(k='dd',a=1.5,al=1)}

def two_dd():
    b,c=PB.two();e=np.cumprod(1+b+c);return 1-e/np.maximum.accumulate(e)

def fn(d,v):
    n=len(d['sig']['side']);t=np.arange(n);D=(t+1)*240//1440;dd=two_dd()
    x=dd[np.clip(D-1,0,len(dd)-1)];x=np.where(D>=1,x,0.)
    k=v['k'];m=np.ones(n);side=np.asarray(d['sig']['side'],np.int8).copy()
    up=d['btc']['c'][:n]>d['btc']['e200'][:n]
    if k=='dd':m=np.where(x>.10,v['a'],1.)
    elif k=='tier':m=np.where(x>.20,2.,np.where(x>.10,1.5,1.))
    elif k=='hi':m=np.where(x<.02,.5,1.)
    elif k=='both':m=np.where(x>.10,1.5,np.where(x<.02,.5,1.))
    elif k=='skip':side[(side==-1)&up]=0
    if k=='al' or v.get('al'):
        mis=((side==1)&~up)|((side==-1)&up);m=m*np.where(mis,.5,1.)
    return PB.run(d,side=side,mult=m)

def diag_hedge():
    b,c=PB.two();tw=b+c;o,_=PB.series(PB.base_fn,None,PB.OTHER20);o=o*PB.PA_SCALE;S=PB.X.SPLIT
    dd=two_dd();prev=np.concatenate([[0.],dd[:-1]]);hi=prev[:S]>.10
    print('DIAG(train days) TWO dd>10%: n',hi.sum(),'PA mean/day %.5f TWO mean/day %.5f | else: n'%(o[:S][hi].mean(),tw[:S][hi].mean()),(~hi).sum(),
          'PA %.5f TWO %.5f'%(o[:S][~hi].mean(),tw[:S][~hi].mean()),'| corr(PA,TWO) hi %.3f lo %.3f'%(np.corrcoef(o[:S][hi],tw[:S][hi])[0,1],np.corrcoef(o[:S][~hi],tw[:S][~hi])[0,1]))
    print('DIAG PA@0.15%% on days after TWO 1-day loss: mean %.5f (train)'%o[1:S][tw[:S-1]<0].mean())

def main():
    diag_hedge();PB.run_idea('regime',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
