"""pa2_htf - Ghoghnous on HIGHER TIMEFRAMES (8h / 12h / 1d). Pre-declared before any validation or IN15 result was seen.

HYPOTHESIS. Price action on 8h, 12h and daily bars gives fewer, larger moves, so the fixed cost per trade (fee 0.06%/side
+ 2 bps + funding) is a smaller share of R, and the patterns that matter most to discretionary traders (daily key
reversals, daily ranges breaking, daily change of character) are less noisy than on 4h. A higher-timeframe sleeve, or a
small ensemble of uncorrelated higher-timeframe pattern legs, should beat C1 (4h KEYREV) on TRAIN, VALID and IN15.

MECHANISM. Signals from pa_bot.detect (family code unchanged, long + exact short mirror) on bm-minute bars built from the
minute data (pa_bot.signals(d['P'], bm, fam), so check_causal truncation is respected). C1-style exits: NO target, stop
at the family's own stop, time stop at the close of the hold-th bar after the entry bar. Engine = pabench2.run_tf
(minute fills, same costs, 0.5% risk of the fixed 1e4 base, cap 1x, MINSTOP 0.4%). Ensembles = independent legs (each
its own one-position-per-coin book) with the risk split equally between legs (mult = 1/k); daily series are summed.

TRAIN-ONLY PRE-PASS (OTHER20, minute data physically truncated at 2025-01-01; scripts in the session scratchpad):
 P1 19 families x {8h,12h,1d} x hold {120h clock-matched, 30 bars} (+ KEYREV with C1's 1.1 ATR size filter) = 120
    cells. Train Calmar (C1 4h = 0.28): 8h KEYREV/120h 1.46, 1d CHOCH/30 bars 1.40, 1d BOX/120h 1.16, 8h BOX/30b 1.07,
    1d WEDGE/30b 1.57 (but WEDGE is negative in 4 of its other 5 cells -> rejected as an isolated spike). KEYREV is
    positive in all 6 tf x hold cells; the 1.1 ATR size filter hurts on 8h/1d (8h 1.46 -> 0.37, 1d bars 0.54 -> -0.27).
    NR7, INSIDE, FAKEY, PIN, FLAG, SFP, TRAP, RETEST mostly negative.
 P2 Hold sweep 80..720h for KEYREV, ENGULF, EMAREJ, BOX, CHOCH on 8h/12h/1d. Stable plateaus (train Calmar):
    8h KEYREV 80-180h 1.21-1.52 (cliff after 240h: 0.35); 12h KEYREV 240h 0.92 (0.30-0.65 around it);
    1d BOX 120-240h 1.10-1.29; 1d CHOCH 120-360h 0.79-1.39; 8h ENGULF 360h 1.02 (DD 42%); EMAREJ DD 40-80% (dropped).
 P3 Train correlations of daily series: kr8 vs box1d 0.06, vs choch1d 0.09, vs C1 0.31; box1d vs choch1d 0.51.
    Equal-risk ensembles, train Calmar: KEYREV 8h+12h+1d 1.83; kr8+box1d+choch1d 2.63; all six legs 2.42.
 CAVEAT declared up front: about 225 train cells were looked at, so every pick below carries a winner's-curse bias;
 the validation and IN15 numbers are the only honest judges.

VARIANTS (fixed; hold in bars of the variant's own timeframe):
 kr8      8h KEYREV, no size filter, hold 15 (120h = C1's clock length)
 kr8_f    8h KEYREV with C1's 1.1 ATR signal-bar filter, hold 15 (C1 transplanted literally, control)
 kr12     12h KEYREV, no filter, hold 20 (240h)
 kr_ens   KEYREV ensemble: 8h/15 + 12h/20 + 1d/15, risk 1/3 each
 box1d    1d BOX (20-day range < 4 ATR, close breaks out, market entry, stop at box middle), hold 7 (168h)
 choch1d  1d CHOCH (lower highs and lows, first close above the last pivot high, market entry), hold 10
 htf3     kr8 + box1d + choch1d, risk 1/3 each
 htf6     kr8 + kr12 + 1d KEYREV/15 + box1d + choch1d + 8h ENGULF/45, risk 1/6 each
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from high_cagr.ideas import pabench2 as Q, pabench as PB
from high_cagr.ideas import pa_bot as PBOT

LEG={'kr8':(480,'KEYREV',15,0.),'kr8_f':(480,'KEYREV',15,1.1),'kr12':(720,'KEYREV',20,0.),'kr1d':(1440,'KEYREV',15,0.),
     'box1d':(1440,'BOX',7,0.),'choch1d':(1440,'CHOCH',10,0.),'eng8':(480,'ENGULF',45,0.)}
VARIANTS={'kr8':['kr8'],'kr8_f':['kr8_f'],'kr12':['kr12'],'kr_ens':['kr8','kr12','kr1d'],'box1d':['box1d'],'choch1d':['choch1d'],
          'htf3':['kr8','box1d','choch1d'],'htf6':['kr8','kr12','kr1d','box1d','choch1d','eng8']}
_SIG={}

def _sig(d,bm,fam):
    k=(d['name'],len(d['P']),bm,fam)
    if k not in _SIG:
        if len(_SIG)>64:_SIG.clear()
        _SIG[k]=PBOT.signals(np.asarray(d['P']),bm,fam)
    return _SIG[k]

def leg(d,name,mult):
    bm,fam,hold,minr=LEG[name];g=_sig(d,bm,fam);side=g['side'].copy()
    if minr>0:
        _,h,l,_=PBOT.bars_of(np.asarray(d['P']),bm);side[(h-l)<minr*g['atr']]=0
    return Q.run_tf(d,bm,side,g['kind'],g['lev'],g['stp'],g['val'],g['atr'],mult=np.full(len(side),mult),hold=hold)

def fn(d,variant):
    legs=variant;out=[]
    for i,nm in enumerate(legs):
        t=leg(d,nm,1./len(legs))
        if len(t):t=t.copy();t[:,9]+=100000*i;out.append(t)
    return np.concatenate(out) if out else np.zeros((0,10))

if __name__=='__main__':
    Q.run_idea('htf',VARIANTS,fn,notes=__doc__)
