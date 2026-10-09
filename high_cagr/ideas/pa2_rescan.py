"""pa2_rescan -- re-scan ALL pa_bot entry families with the C1 exit (written and declared BEFORE any validation/IN15 run).

HYPOTHESIS. The original 228-config search (pa_bot.py) judged every family only with TP1/TP2/TRAIL exits. C1's exit (no
target, time stop at the close of the 30th 4h bar, stop only) and the 1.1-ATR signal-range filter were found later and
only applied to KEYREV. If C1's improvement came from the exit (letting the fat tail run for 5 days) and not from the
key-reversal pattern itself, then other families -- especially the in-trend ones (H2, INSIDE) that the literature
favours over counter-trend reversals -- may do as well or better with the same exit, and an OR-combination of weakly
correlated families should add trades (CAGR) without adding much drawdown.
MECHANISM. Same engine, costs, sizing and exit as C1 (pabench2.run_tf on 4h, kind 1 stop-entry / kind 2 market at next
open, target_r=0, hold=30, risk 0.5% of 1e4, CAP 1, MINSTOP 0.4%). Signals = pa_bot.detect on 4h bars built from the
coin's own minute data (Q.bars -> truncation-safe), long side first, shorts the exact mirror (pa_bot.signals logic),
signal bar range >= 1.1 x ATR14 (Wilder) required for EVERY family. Combos: families are OR-ed per bar in the listed
priority order (first family that fires on a bar sets side/kind/level/stop/validity); one position per coin (engine).

TRAIN-ONLY PRE-PASS (entries < 2025-01-01; OTHER20; no validation or IN15 number was computed or looked at).
19 families x {no range filter, range >= 1.1 ATR} = 38 singles with the C1 exit. KEYREV|rng reproduces C1 (841 train
trades, train Calmar 0.279). Train Calmar (CAGR %, DD %, trades, mean R):
  INSIDE|rng 0.855 (14.4, 16.9, 399, 0.284)   CHOCH|rng 0.753 (15.8, 21.0, 1391, 0.098)   H2|rng 0.627 (10.7, 17.0, 530, 0.205)
  DOUBLE|rng 0.514 (9.2, 17.9, 1316, 0.080)   EMAREJ|rng 0.426 (24.6, 57.7)   SFP|rng 0.404   CHOCH|none 0.363
  DOUBLE|none 0.355  BOS|none 0.338  BOS|rng 0.309  KEYREV|none 0.308  KEYREV|rng 0.279  BOX|none 0.258  WEDGE|rng 0.257
  everything else < 0.17 (PIN, FVG, ENGULF, FAKEY, TRAP, FLAG, RETEST, CLIMAX, NR7 <= ~0); 'none' is worse than 'rng'
  for 15 of 19 families, so the range filter is kept for all.
Combos (train Calmar, CAGR, DD, trades, Calmar of the two train halves):
  IN+CH 0.986 (29.4, 29.8, 1652, 0.38/4.28)  IN+H2 0.988 (22.2, 22.5, 859, 0.03/3.05)  IN+CH+H2 0.960 (29.8, 31.1, 1987)
  IN+CH+H2+KR 0.948 (38.2, 40.2, 2408, 0.77/1.76)  CH+KR 0.773 (24.8, 32.0, 1894, 0.94/0.97)  IN+KR 0.687
  IN+CH+H2+DB 0.544  KR+SFP+ENG 0.354 (43.8 DD).  Train daily-series correlation INSIDE-KEYREV 0.09, CHOCH-KEYREV 0.29,
  INSIDE-H2 0.51, CHOCH-DOUBLE 0.64. Warning seen in train: INSIDE/H2 make most of their train money in 2024 (first
  train half Calmar 0.48 / -0.17), C1 the opposite (1.62 / -0.12); ~51 train configs were tried -> winner's curse likely.

VARIANTS (fixed, chosen by TRAIN Calmar only; 8):
  V1 INSIDE      best single (in-trend inside bar, stop above mother bar, 2-bar validity)
  V2 CHOCH       2nd single (change of character, market entry)
  V3 H2          3rd single (Brooks High-2 in trend)
  V4 IN_CH       INSIDE > CHOCH
  V5 IN_H2       INSIDE > H2 (pure in-trend pair)
  V6 IN_CH_H2    INSIDE > CHOCH > H2
  V7 IN_CH_H2_KR INSIDE > CHOCH > H2 > KEYREV (highest train CAGR, adds C1)
  V8 CH_KR       CHOCH > KEYREV (most even train halves)
PREDICTION. Most likely outcome given the multiple testing: Q1 passes for all (train-selected), Q2/Q3 decide; at least
one combo passes Q2 if the effect is real. A clear failure of Q2/Q3 means the C1 exit is not a general key.
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from high_cagr.ideas import pabench2 as Q, pabench as PB
from high_cagr.ideas import pa_bot as PBOT

VARIANTS={'V1_INSIDE':['INSIDE'],'V2_CHOCH':['CHOCH'],'V3_H2':['H2'],'V4_IN_CH':['INSIDE','CHOCH'],'V5_IN_H2':['INSIDE','H2'],
          'V6_IN_CH_H2':['INSIDE','CHOCH','H2'],'V7_IN_CH_H2_KR':['INSIDE','CHOCH','H2','KEYREV'],'V8_CH_KR':['CHOCH','KEYREV']}
RNG=1.1

def signals(d,fams):
    """OR of pa_bot families on 4h (priority = list order), long first then mirrored short, range >= RNG x ATR14."""
    o,h,l,c=Q.bars(d,240);a=Q.atr14(h,l,c);n=len(c);big=(h-l)>=RNG*a
    pre=[]
    for sg in (1,-1):
        oo,hh,ll,cc=(o,h,l,c) if sg==1 else (-o,-l,-h,-c)
        pre.append((sg,oo,hh,ll,cc,PBOT.ema(cc,20),PBOT.ema(cc,50))+PBOT.last_pivots(hh,ll,3))
    side=np.zeros(n,np.int8);kind=np.zeros(n,np.int8);lev=np.full(n,np.nan);stp=np.full(n,np.nan);val=np.ones(n,np.int64)
    for fam in fams:
        for (sg,oo,hh,ll,cc,e20,e50,PH,PHI,PL,PLI) in pre:
            k,lv,st,v=PBOT.detect(PBOT.FAMS.index(fam),oo,hh,ll,cc,a,e20,e50,PH,PHI,PL,PLI)
            m=(k>0)&(side==0)&big;side[m]=sg;kind[m]=k[m];lev[m]=sg*lv[m];stp[m]=sg*st[m];val[m]=v[m]
    return side,kind,lev,stp,val,a

def fn(d,variant):
    side,kind,lev,stp,val,a=signals(d,variant)
    return Q.run_tf(d,240,side,kind,lev,stp,val,a,target_r=0.,hold=30)

if __name__=='__main__':
    Q.run_idea('rescan',VARIANTS,fn,notes=__doc__)
