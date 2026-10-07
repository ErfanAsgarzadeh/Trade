"""C3 agent 2 -- exit/stop-side fixes for SLOW_FAILURE losers and INITIAL_STOP exits.

Declared BEFORE any run (fixed round-number parameters, no tuning after results):

Baseline C3 = 4h PULL entry, no weekend entries, mode 6 exit (2 ATR initial stop on intrabar high/low, then a
4.5 ATR chandelier on closes). 1R = initial stop distance = 2 ATR. The chandelier only rises above the initial
stop once the best close is > 2.5 ATR (1.25R) past entry, so trades that make 0.5-1R and roll over (SLOW_FAILURE,
median 18 bars) give back the full -1R.

Variants (each changes exactly one thing vs the baseline engine, everything else identical):
  A STALE12  : stale-trade exit. At the close of the 12th bar in the trade (48h), if no 4h close since entry
               has reached +1R, exit at that close. Mechanism: a pullback entry is a bet that the trend resumes
               quickly; if it has not resumed in 2 days the edge has decayed and the trade drifts to the stop.
  B SWING10  : structure-based initial stop. Stop = lowest low of the last 10 bars (signal bar included) minus
               0.5 ATR for longs (highest high + 0.5 ATR for shorts), distance clamped to [1.5, 3.0] ATR.
               Sizing still 0.5% risk on that distance. Mechanism: a PULL entry sits just after a pullback;
               placing the stop beyond the pullback extreme instead of a fixed 2 ATR avoids being stopped by
               noise inside the swing (INITIAL_STOP exits), while R adapts to the actual structure.
  C DERISK1R : partial de-risking. Once intrabar MFE reaches +1R (high for longs, low for shorts), the stop is
               raised to entry - 0.5R (applies from the next bar; chandelier still active above it). Mechanism:
               caps SLOW_FAILURE losses (MFE 0.5-1R reached 1R intrabar in part) at -0.5R while leaving 1.5R
               (3 ATR) of room so winners are not shaken out as with a true breakeven stop.

Engine: copy of mtf_search.engine mode 6, same output format
[entry_bar, exit_bar, side, net_frac, price_R, qty, entry_fill, exit_fill, cost], base 1e4, 0.5% risk,
fee .0006/side, slippage .0002, funding via d['fb'], warm 300. With all switches off it reproduces the baseline.
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,al,as_,fee,slip,fcum,warm,stale_n,stale_r,swing_lb,swing_pad,smin,smax,de_trig,de_lvl):
    n=len(c);out=np.zeros((n,9));k=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        if swing_lb>0:
            j0=max(0,t-swing_lb+1)
            if side==1:
                ext=l[j0];
                for q in range(j0,t+1):ext=min(ext,l[q])
                sd=entry-(ext-swing_pad*a)
            else:
                ext=h[j0]
                for q in range(j0,t+1):ext=max(ext,h[q])
                sd=(ext+swing_pad*a)-entry
            sd=min(max(sd,smin*a),smax*a);stop=entry-side*sd
        else:
            stop=entry-side*2.*a
        dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e;tw=4.5
        bestc=-1e18;derisked=False
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            bestc=max(bestc,side*(c[j]-entry)/dist)
            if stale_n>0 and j-e==stale_n-1 and bestc<stale_r:xraw=c[j];x=j;break
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
            if side*(ns-stop)>0:stop=ns
            if de_trig>0 and not derisked:
                mfe=side*((h[j] if side==1 else l[j])-entry)/dist
                if mfe>=de_trig:
                    derisked=True;ds=entry-side*de_lvl*dist
                    if side*(ds-stop)>0:stop=ds
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;k+=1
        t=x if x>t else t+1
    return out[:k]

BASE=dict(stale_n=0,stale_r=0.,swing_lb=0,swing_pad=0.,smin=0.,smax=0.,de_trig=0.,de_lvl=0.)
VARIANTS={'A_STALE12':dict(BASE,stale_n=12,stale_r=1.),
          'B_SWING10':dict(BASE,swing_lb=10,swing_pad=.5,smin=1.5,smax=3.),
          'C_DERISK1R':dict(BASE,de_trig=1.,de_lvl=.5)}

def trades_fn(d,variant):
    v=variant or BASE;le,se,_,_=d['sig']['PULL']
    return engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],.0006,.0002,d['fb'],300,
                  int(v['stale_n']),float(v['stale_r']),int(v['swing_lb']),float(v['swing_pad']),float(v['smin']),float(v['smax']),float(v['de_trig']),float(v['de_lvl']))

if __name__=='__main__':
    # sanity: all switches off must reproduce the baseline engine exactly
    for s in B.MAIN10[:3]:
        d=B.coin(s);a=trades_fn(d,BASE);b=B.baseline_trades(d);assert a.shape==b.shape and np.allclose(a,b),s
    print('engine copy == baseline on 3 coins',flush=True)
    B.run('a2_stops',VARIANTS,trades_fn,notes=__doc__)
