"""C3 round 2, agent 3: RE-ENTRY after a profitable trail exit while the trend is intact (PRE-DECLARED before any run).

Base = C3 + D (c3bench_d.confirm_signals entries, mode 6 exit: 2 ATR initial stop, 4.5 ATR chandelier on closes).
Problem: big trends shake C3 out on a deep pullback (close 4.5 ATR off the best close), then continue without a new
RSI 40/60 PULL signal, so C3 sits flat for the rest of the move (baseline captures ~32% of big-trend moves).

Mechanism shared by all variants: when a trade (normal or re-entry) exits with net > 0, the engine is 'armed' in the
same direction for 30 bars (5 days of 4h bars) after the exit bar. While armed, a re-entry is taken at the next open
if its trigger fires on a weekday bar AND EMA50 vs EMA200 still agrees with the side. Exit, stop (2 ATR of the
decision bar), sizing and costs are identical to normal trades. A losing exit disarms (the trend-continuation thesis
failed), so chop cannot produce a chain of re-entries; a profitable re-entry re-arms (rides multi-leg trends).
Normal D entries keep priority. Every trigger uses only closes/indicators <= decision bar (causal).

Variants (fixed round numbers):
  RECLAIM  trigger: close beyond the BEST close of the trade just exited (long: c > prior peak close).
           Mechanism: a new trend extreme after the shakeout is direct proof the trend resumed; it re-enters
           late (pays back the pullback) but almost never in a broken trend.
  RSI50    trigger: shallow pullback reset - RSI14 crosses back above 50 (short: below 50), then a D-style
           confirmation: a close beyond that cross bar's close within the next 3 bars.
           Mechanism: in strong trends pullbacks rarely reach RSI 40, so the PULL signal never re-fires; the
           50-line reset is the strong-trend version of the same pullback entry, with D's follow-through check.
  EITHER   RECLAIM or RSI50, whichever fires first (tests whether the two triggers add up).
Gates R1-R5 frozen in c3bench_d.py.
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench_d as BD
B=BD.B

VARIANTS={'RECLAIM':dict(win=30,reclaim=1,rsi50=0),'RSI50':dict(win=30,reclaim=0,rsi50=1),'EITHER':dict(win=30,reclaim=1,rsi50=1)}

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,wk,e50,e200,r14,fee,slip,fcum,warm,win,reclaim,rsi50):
    n=len(c);out=np.zeros((n,9));k=0;t=warm;tw=4.5
    arm=0;arm_end=-1;peak=0.;pend=-1;plev=0.
    while t<n-2:
        side=1 if (le[t] and wk[t]) else (-1 if (se[t] and wk[t]) else 0)
        if side==0 and arm!=0:
            if t>arm_end:arm=0;pend=-1
            else:
                trend=(e50[t]>e200[t]) if arm==1 else (e50[t]<e200[t])
                fire=False
                if rsi50==1:
                    if pend>=0 and t>pend+3:pend=-1
                    if pend>=0 and arm*(c[t]-plev)>0:fire=True
                    cr=(r14[t-1]<50. and r14[t]>=50.) if arm==1 else (r14[t-1]>50. and r14[t]<=50.)
                    if cr and not fire:pend=t;plev=c[t]
                if reclaim==1 and arm*(c[t]-peak)>0:fire=True
                if fire and trend and wk[t]:side=arm
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
            if side*(ns-stop)>0:stop=ns
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;k+=1
        if win>0 and net>0:arm=side;arm_end=x+win;peak=best;pend=-1
        else:arm=0;pend=-1
        t=x if x>t else t+1
    return out[:k]

def trades_fn(d,v):
    le,se=BD.confirm_signals(d)
    return engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['e50'],d['e200'],d['r14'],.0006,.0002,d['fb'],300,
                  v['win'],v['reclaim'],v['rsi50'])

if __name__=='__main__':
    off=dict(win=0,reclaim=0,rsi50=0)
    for s in B.MAIN10[:3]:
        d=B.coin(s);assert np.allclose(trades_fn(d,off),BD.d_trades(d)),s
    print('engine copy == C3+D baseline OK',flush=True)
    BD.run('r2_a3_reentry',VARIANTS,trades_fn,notes='Agent 3 R2: re-entry within 30 bars after a profitable exit while EMA50/200 agrees; RECLAIM (close beyond prior peak close), RSI50 (RSI 50 re-cross + 3-bar close confirmation), EITHER.')
