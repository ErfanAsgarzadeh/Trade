"""C3 round 2, agent 2 -- PYRAMIDING into winners (baseline = C3 + D, bench high_cagr/ideas/c3bench_d.py).

Declared BEFORE any run (fixed round parameters, no tuning after results).

Base trade = unchanged C3+D (D confirmation entries, 2 ATR initial stop, 4.5 ATR chandelier on closes, 0.5% risk).
1R = base initial stop distance. All units share ONE stop and exit together at the base trade's exit.
Add sizing: each add risks 0.25% of the 1e4 base (half a unit) on its own distance (add entry fill -> shared stop at
the add), qty = 25/(dist + entry*(2 fee + 2 slip)), notional cap 0.4 x base per row, skipped if that distance < 0.4% of
price. Decision on the close of bar j (after the stop check and chandelier update), entry at the open of j+1.
"Never turn a winner into a net loser" lock: when the k-th add is decided, the shared stop is raised to at least
entry + 0.5R x k (base fill). Each add can lose at most its 0.5R (the stop only moves in its favour afterwards), so at
the stop the base unit's locked profit >= the adds' combined maximum loss (before gaps and costs).

Variants:
  A ADD3R_BREAKOUT : one add when a close first reaches +3R (6 ATR) beyond entry. Mechanism: a trade that runs 3R has
                     proven it is in a real trend (big winners are the whole edge: top 10% = 173% of net R); at +3R
                     the 4.5 ATR chandelier already sits near +0.75R, so the +0.5R lock rarely tightens anything and
                     the add gets the full 4.5 ATR breathing room.
  B ADD2R_PULL     : one add on a NEW C3+D resumption signal (confirm bar on the trade side, weekday) while the open
                     trade's best close is >= +2R. Mechanism: add on a pullback-and-resume inside a proven trend --
                     the same edge as the base entry, but with the trend already confirmed by 2R of progress; the
                     pullback entry is closer to the shared stop, so the add risk buys more quantity.
  C ADD2X_PULL     : as B but up to two adds: 1st needs best close >= +2R, 2nd needs best close >= +4R and another new
                     resumption signal after the 1st add. Lock = entry + 0.5R per add. Mechanism: longer trends offer
                     several pullbacks; scaling twice concentrates risk on the rare 8R+ runs.

Output rows: bench format [entry_bar, exit_bar, side, net_frac, price_R, qty, entry_fill, exit_fill, cost];
the base unit and each add are separate rows (same exit bar / exit price), so mark-to-market is exact.
With adds off the engine reproduces c3bench_d.d_trades exactly (asserted before the run).
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench_d as BD
B=BD.B

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,al,as_,fee,slip,fcum,warm,mode,max_adds,trig1,trig2,lock,add_risk):
    """mode 0 = no adds, 1 = breakout add at close >= trig1 R, 2 = add on new resumption signal (le/se & al/as_)."""
    n=len(c);out=np.zeros((3*n,9));k=0;t=warm
    ae=np.zeros(4,np.int64);araw=np.zeros(4);adist=np.zeros(4);aqty=np.zeros(4)
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e;tw=4.5
        na=0;pend=False;bestR=-1e18;last_add=-1
        while j<n:
            if pend:
                # add fills at this bar's open; shared stop already includes the lock
                r0=o[j];ad=side*(r0*(1+side*slip)-stop)
                if ad>0 and ad/r0>=.004:
                    ae[na]=j;araw[na]=r0;adist[na]=ad;aqty[na]=min(add_risk*1e4/(ad+r0*(1+side*slip)*(2*fee+2*slip)),.4*1e4/r0);na+=1;last_add=j
                pend=False
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
            if side*(ns-stop)>0:stop=ns
            bestR=max(bestR,side*(c[j]-entry)/dist)
            if mode>0 and na<max_adds and j+1<n:
                need=trig1 if na==0 else trig2;go=False
                if bestR>=need:
                    if mode==1:go=True
                    elif j>last_add and ((side==1 and le[j] and al[j]) or (side==-1 and se[j] and as_[j])):go=True
                if go:
                    lk=entry+side*lock*dist*(na+1)
                    if side*(lk-stop)>0:stop=lk
                    pend=True
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip)
        fund=-side*raw*qty*(fcum[x]-fcum[e]);net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;k+=1
        for i in range(na):
            if ae[i]>x:continue
            r0=araw[i];en=r0*(1+side*slip);q=aqty[i]
            fund=-side*r0*q*(fcum[x]-fcum[ae[i]]);net=side*(xp-en)*q-(en+xp)*q*fee+fund
            out[k,0]=ae[i];out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-r0)/adist[i];out[k,5]=q;out[k,6]=en;out[k,7]=xp;out[k,8]=(en+xp)*q*fee-fund;k+=1
        t=x if x>t else t+1
    return out[:k]

OFF=dict(mode=0,max_adds=0,trig1=0.,trig2=0.)
VARIANTS={'A_ADD3R_BREAKOUT':dict(mode=1,max_adds=1,trig1=3.,trig2=0.),
          'B_ADD2R_PULL':dict(mode=2,max_adds=1,trig1=2.,trig2=0.),
          'C_ADD2X_PULL':dict(mode=2,max_adds=2,trig1=2.,trig2=4.)}

def trades_fn(d,variant):
    v=variant or OFF;le,se=BD.confirm_signals(d)
    return engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],.0006,.0002,d['fb'],300,
                  int(v['mode']),int(v['max_adds']),float(v['trig1']),float(v['trig2']),.5,.0025)

if __name__=='__main__':
    for s in B.MAIN10[:3]:
        d=B.coin(s);a=trades_fn(d,OFF);b=BD.d_trades(d);assert a.shape==b.shape and np.allclose(a,b),s
    print('engine copy (adds off) == C3+D baseline on 3 coins',flush=True)
    BD.run('r2_a2_pyramid',VARIANTS,trades_fn,notes=__doc__)
