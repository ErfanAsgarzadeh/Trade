"""pa2_ltfentry -- lower-timeframe (1h) execution of the 4h KEYREV setup (variants declared BEFORE any of them was run on
validation or IN15; only the TRAIN pre-pass below was looked at).

HYPOTHESIS. C1 buys the break of the 4h signal-bar extreme with a stop beyond the far end of the signal bar (median stop
4.7%), so it pays the whole bar range as risk. A discretionary PA trader instead waits for a pullback into the signal bar
and enters on a 1h trigger, risking only the pullback low: same 4h idea, tighter stop, better price, larger size per R.
MECHANISM. Setup = C1 4h signal on bar T (pabench2.c1_side: KEYREV, range >= 1.1 ATR, bars >= 250). From the close of the
last 1h bar of T (1h bar j0 = 4T+3) a state machine runs on 1h bars j0..j0+W-1 (built from the coin's minute data,
Q.bars(d,60), truncation-safe), long side (mirror for shorts):
  pl = lowest 1h low since j0; setup dies if pl <= the C1 4h stop (signal low - 0.1 ATR4h), or if a 1h high reaches the
  signal high BEFORE the dip happened (that is a C1 breakout, not a pullback); dipped = pl <= H - dep x (H - L).
  RECLAIM trigger (mode 3): first 1h bar j > j0 after the dip that CLOSES above the previous 1h high -> market buy at the
     open of 1h bar j+1. One trigger per setup.
  BREAK trigger (mode 1): after the dip, every 1h bar with a lower high than the bar before -> buy-stop at its high valid
     for the next 1h bar (re-entries possible within the window).
  Stop (stopmode 0) = pl - buf x ATR14(1h);  stopmode 1 = the C1 4h stop (control: same timing, C1 risk).
Exit = C1 logic: no target, stop, or time stop after 120 1h bars (= 30 4h bars, counted from the 1h entry bar instead of
the 4h entry bar, up to 3h different). Engine pabench.engine2 via Q.run_tf(bm=60, warm=1000 1h bars = 250 4h bars), same
costs, risk 0.5% of 1e4, CAP 1x, MINSTOP 0.4%. Replica check (mode 0 = C1 order placed on the 1h grid, 4 1h bars valid):
TRAIN 841 trades, 73.3R, train Calmar 0.29 vs C1 841 / 72.8R / 0.28 -> the conversion is faithful.

TRAIN-ONLY PRE-PASS (OTHER20, trades entered < 2025-01-01, train-period Calmar; nothing from 2025+ or IN15 was looked at;
C1 = 841 trades, +72.8R net, mean 0.087R, cost 24.9R, Calmar 0.28 CAGR 10.0 DD 35.9):
  BREAK  W4  dep0   769 tr 114.2R mean .149 win 19.5% cost 52.4R  Calmar 0.20 DD 65.4 (median notional 2.5x C1's)
  BREAK  W8  dep0  1200 tr 154.4R cost 83.2R Calmar 0.25 DD 65.0 ; W8 dep.25 1082 tr 108.8R Calmar 0.18 DD 63.0
  BREAK  W8  dep.5  513 tr 110.6R mean .216 cost 28.8R Calmar 0.75 DD 21.7 ; W12 dep.5 592 tr 120.6R Calmar 0.65 ; W16 0.49
  BREAK  W8 dep.25 / dep.5 with the 4h stop: Calmar 0.15 / 0.26
  1h KEYREV in the setup direction within 8/12/24h: 2 / 20 / 74 trades, ~0R -> too rare, dropped.
  RECLAIM W8 dep.25 780 tr 96.5R Calmar 0.28 DD 45.1 ; W8 dep.5 376 tr 99.9R Calmar 0.72 ; W12 dep.5 443 tr 135.8R
          mean .307 win 27.8% cost 19.6R Calmar 1.26 CAGR 21.6 DD 17.1 ; W16 1.10 ; W24 0.98 ; W12 dep.4 0.78 ; dep.6 1.41
          (294 tr) ; buf 0 1.59 ; buf .5 1.43 ; W12 dep.5 with the 4h stop 441 tr 90.5R Calmar 0.82.
  Reading: shallow pullbacks + 1h break churn (many re-entries, cost x2-3, DD 60%+). Waiting for a pullback to the signal
  bar's MIDPOINT is what helps; the 1h stop then adds on top of the selection (0.82 -> 1.26). ~25 train configs were looked
  at -> multiple-testing risk; the neighbourhood (W 8-24, dep .4-.6, buf 0-.5) is smooth, which is the only defence.

VARIANTS (fixed; 8):
  V1 RECLAIM          mode 3, W 12, dep .5, buf .2, 1h stop          (core)
  V2 RECLAIM_W8       mode 3, W 8,  dep .5, buf .2                   (window robustness)
  V3 RECLAIM_D40      mode 3, W 12, dep .4                           (shallower pullback)
  V4 RECLAIM_D60      mode 3, W 12, dep .6                           (deeper pullback, fewer trades)
  V5 RECLAIM_BUF0     mode 3, W 12, dep .5, buf 0 (stop at the 1h pullback low itself; train best, cost/5bps risk)
  V6 RECLAIM_4HSTOP   mode 3, W 12, dep .5, C1 stop                  (control: selection+timing only, C1 risk)
  V7 BREAK_D50        mode 1, W 12, dep .5, buf .2                   (1h stop-order trigger)
  V8 BREAK_D25        mode 1, W 8,  dep .25, buf .2  (literal brief: shallow pullback + 1h break; expected to FAIL Q1)
PREDICTION. V1-V5 pass Q1 (train-selected). Honest tests: Q2 valid, Q3 IN15, Q5 5 bps (tighter stops -> ~1.6x notional,
more fee per R). V6 shows how much is selection vs the tighter stop. V8 fails.
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from numba import njit
from high_cagr.ideas import pabench2 as Q, pabench as PB

VARIANTS={'V1_RECLAIM':dict(mode=3,W=12,dep=.5,buf=.2),'V2_RECLAIM_W8':dict(mode=3,W=8,dep=.5,buf=.2),
          'V3_RECLAIM_D40':dict(mode=3,W=12,dep=.4,buf=.2),'V4_RECLAIM_D60':dict(mode=3,W=12,dep=.6,buf=.2),
          'V5_RECLAIM_BUF0':dict(mode=3,W=12,dep=.5,buf=0.),'V6_RECLAIM_4HSTOP':dict(mode=3,W=12,dep=.5,buf=.2,stopmode=1),
          'V7_BREAK_D50':dict(mode=1,W=12,dep=.5,buf=.2),'V8_BREAK_D25':dict(mode=1,W=8,dep=.25,buf=.2)}

@njit(cache=True)
def gen(mode,W,dep,kill,stopmode,buf,o,h,l,c,a1,s4,H4,L4,C4,S4,A4,warm4):
    n1=len(c);side=np.zeros(n1,np.int8);kind=np.ones(n1,np.int8);lev=np.zeros(n1);stp=np.zeros(n1);val=np.ones(n1,np.int64)
    for T in range(warm4,len(s4)):
        s=s4[T]
        if s==0:continue
        j0=4*T+3
        if j0>=n1:break
        if mode==0:
            side[j0]=s;lev[j0]=H4[T] if s==1 else L4[T];stp[j0]=S4[T];val[j0]=4;continue
        rng=H4[T]-L4[T];ext=h[j0] if s==1 else l[j0];pl=l[j0] if s==1 else h[j0];dipped=False
        for j in range(j0,min(j0+W,n1-1)):
            if j>j0:
                if s==1:
                    pl=min(pl,l[j])
                    if l[j]<=S4[T]:break
                else:
                    pl=max(pl,h[j])
                    if h[j]>=S4[T]:break
            if s==1:
                if pl<=L4[T]+kill*rng:break
                if pl<=H4[T]-dep*rng:dipped=True
            else:
                if pl>=H4[T]-kill*rng:break
                if pl>=L4[T]+dep*rng:dipped=True
            if j>j0 and ((s==1 and h[j]>=H4[T]) or (s==-1 and l[j]<=L4[T])) and not dipped:break  # broke out without pullback: C1-type trade, not ours
            if mode==1:   # pullback bar -> stop order at its extreme, valid 1h
                pb=(h[j]<h[j-1]) if s==1 else (l[j]>l[j-1])
                if dipped and pb:
                    side[j]=s;lev[j]=h[j] if s==1 else l[j];val[j]=1
                    stp[j]=(pl-buf*a1[j] if s==1 else pl+buf*a1[j]) if stopmode==0 else S4[T]
            elif mode==2: # 1h key reversal in the setup direction
                if j>j0 and j>=11:
                    ok=True
                    r=h[j]-l[j]
                    if r<=0:ok=False
                    elif s==1:
                        if not (h[j]>h[j-1] and l[j]<l[j-1] and c[j]>c[j-1] and (c[j]-l[j])/r>=.75):ok=False
                        for q in range(j-10,j):
                            if l[q]<l[j]:ok=False
                    else:
                        if not (h[j]>h[j-1] and l[j]<l[j-1] and c[j]<c[j-1] and (h[j]-c[j])/r>=.75):ok=False
                        for q in range(j-10,j):
                            if h[q]>h[j]:ok=False
                    if ok:
                        side[j]=s;lev[j]=h[j] if s==1 else l[j];val[j]=1
                        stp[j]=(l[j]-buf*a1[j] if s==1 else h[j]+buf*a1[j]) if stopmode==0 else S4[T]
            elif mode==3: # dip then 1h close back above prior 1h high -> market next open
                if dipped and j>j0 and ((s==1 and c[j]>h[j-1]) or (s==-1 and c[j]<l[j-1])):
                    side[j]=s;kind[j]=2;lev[j]=0.
                    stp[j]=(pl-buf*a1[j] if s==1 else pl+buf*a1[j]) if stopmode==0 else S4[T]
                    break
    return side,kind,lev,stp,val

def arrays(d,v):
    o,h,l,c=Q.bars(d,60);a1=Q.atr14(h,l,c);s4=Q.c1_side(d);n=len(s4)
    H4=d['h'][:n];L4=d['l'][:n];C4=d['c'][:n];g=d['sig'];S4=g['stp'][:n];A4=d['atr'][:n]
    return (o,h,l,c,a1)+gen(v['mode'],v.get('W',8),v.get('dep',0.),v.get('kill',-1.),v.get('stopmode',0),v.get('buf',.2),o,h,l,c,a1,s4.astype(np.int8),H4,L4,C4,S4,A4,250)

def fn(d,v):
    o,h,l,c,a1,side,kind,lev,stp,val=arrays(d,v)
    return Q.run_tf(d,60,side,kind,lev,stp,val,a1,hold=v.get('hold',120),warm=1000)

if __name__=='__main__':
    Q.run_idea('ltfentry',VARIANTS,fn,notes=__doc__)
