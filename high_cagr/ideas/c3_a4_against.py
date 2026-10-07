"""C3 agent 4 - cause AGAINST: C3 holds positions against big (>=30%) trends ~20% of the move.

MECHANISM. PULL takes direction only from EMA50 vs EMA200. After a sharp reversal EMA50 stays on the old side
of EMA200 for weeks, so PULL keeps shorting RSI(14) re-crosses of 60 inside a fresh rally (and longing dips while a
top forms). In such a rally price is already back above EMA200 and above the midpoint of its multi-week range, while
the EMA cross still lags. Requiring a second, faster-reacting-but-still-slow trend witness on the trade side should
remove the entries that fight the new move without touching entries inside an established trend.

PRE-DECLARED VARIANTS (fixed round parameters, one round, no tuning):
  V1_ema200   entry filter: longs only if close[t] > EMA200[t], shorts only if close[t] < EMA200[t]
              (price must agree with the slow EMA, not just the EMA50/200 cross).
  V2_don240   entry filter: longs only if close[t] > midline of the 240-bar (40-day) Donchian channel
              (max high + min low over bars t-239..t)/2, shorts only if below it.
  V3_don240x  V2 filter + regime-flip exit: if a bar closes on the wrong side of the 240-bar Donchian midline
              (long: close < mid, short: close > mid) the position is closed at the next bar open
              (stop and 4.5 ATR chandelier from mode 6 still apply).
Everything else = baseline C3 (PULL, mode 6 TRAILW, no weekend entries, costs .0006/.0002, funding, warm 300).
All filters use data <= signal bar only.
"""
from pathlib import Path
import sys
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B, mtf_search as M

@njit(cache=True)
def engine_x(o,h,l,c,atr,le,se,al,as_,xl,xs,fee,slip,fcum,warm):
    """Copy of mtf_search.engine mode 6 plus a regime-flip exit: xl[j] (xs[j]) closes a long (short) at o[j+1]."""
    n=len(c);out=np.zeros((n,9));k=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e;tw=4.5
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            if ((side==1 and xl[j]) or (side==-1 and xs[j])) and j+1<n:xraw=o[j+1];x=j+1;break
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
            if side*(ns-stop)>0:stop=ns
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;k+=1
        t=x if x>t else t+1
    return out[:k]

def don_mid(d,w):
    m=(pd.Series(d['h']).rolling(w).max()+pd.Series(d['l']).rolling(w).min()).to_numpy()/2
    return m  # NaN for the first w-1 bars -> comparisons False -> no entries there (warm is 300 anyway)

def trades_fn(d,variant):
    le,se,_,_=d['sig']['PULL'];c=d['c'];wk=d['wk'];z=np.zeros(d['n'],bool)
    if variant['filter']=='ema200':up=c>d['e200'];dn=c<d['e200']
    else:mid=don_mid(d,variant['win']);up=c>mid;dn=c<mid
    al=wk&up;as_=wk&dn
    if variant.get('flip_exit'):
        return engine_x(d['o'],d['h'],d['l'],c,d['atr'],le,se,al,as_,dn.copy(),up.copy(),.0006,.0002,d['fb'],300)
    return M.engine(d['o'],d['h'],d['l'],c,d['atr'],le,se,z,z,al,as_,6,.0006,.0002,d['fb'],300)

VARIANTS={'V1_ema200':dict(filter='ema200'),'V2_don240':dict(filter='don',win=240),'V3_don240x':dict(filter='don',win=240,flip_exit=True)}

if __name__=='__main__':
    b=B.baseline();print('baseline',{k:{p:[round(x,2) for x in v] for p,v in b[k].items()} for k in ('main','other','port')},b['trades'],flush=True)
    B.run('a4_against',VARIANTS,trades_fn,notes=__doc__)
