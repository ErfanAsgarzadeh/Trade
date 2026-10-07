"""C3 agent 3: GIVEBACK trade management (PRE-DECLARED before any run; no post-hoc changes).

Cause: 281 losers first reached >= 1R (20% of loss R); winners with peak 2-4R exit at 0.9R, 4-8R at 2.9R.
Constraint: net R comes from the tail (top 10% = 173% of net R), so every variant below is built so that it does
NOT bind on large runners (the 4.5 ATR chandelier stays the binding stop once a trade is far in profit).

Engine = exact copy of mtf_search.engine mode 6 (2 ATR initial stop, 4.5 ATR chandelier on closes, stop checked
intrabar, new stop effective from the next bar) with three optional add-ons. R = initial stop distance (dist);
'peak' = best CLOSE since entry measured in R (same close-based extreme the chandelier uses; known at bar close,
so any new stop level applies from the next bar -> causal).

Variants (fixed round numbers, mechanism in brackets):
  BE1R     [breakeven floor]  once peak >= 1.0R, stop >= entry + 0.1R (covers round-trip costs).
           Targets GIVEBACK_GE1R losers directly. Risk: scratches trades that dip and then become winners.
  LOCKHALF [profit-lock floor that fades out for big winners] once peak >= 2.0R, stop >= entry + 0.5*peak R.
           Mid winners (peak 2-4R, today exit 0.9R) keep >= 1-2R; for peak >~ 9R the chandelier
           (peak - 2.25R in ATR terms) is already higher, so the tail is untouched.
  PART2R   [partial take-profit] close 1/3 of the position at a +2.0R limit (intrabar, after the stop check,
           fill max(open,tp) for longs, slippage+fee charged); remaining 2/3 keeps the unchanged mode-6 exit.
           Emitted as TWO rows (partial leg + runner leg, same entry_bar) so m2m marks each correctly; this
           inflates the printed trade count / win%. Calmar gates are unaffected by row splitting.
Gates G1-G5 are the frozen ones in c3bench.py.
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B

VARIANTS={'BE1R':dict(be_trig=1.0,be_lock=0.1,lk_trig=0.,lk_frac=0.,pt_r=0.,pt_frac=0.),
          'LOCKHALF':dict(be_trig=0.,be_lock=0.,lk_trig=2.0,lk_frac=0.5,pt_r=0.,pt_frac=0.),
          'PART2R':dict(be_trig=0.,be_lock=0.,lk_trig=0.,lk_frac=0.,pt_r=2.0,pt_frac=1/3)}

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,al,as_,fee,slip,fcum,warm,be_trig,be_lock,lk_trig,lk_frac,pt_r,pt_frac):
    n=len(c);out=np.zeros((2*n,9));k=0;t=warm;tw=4.5
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e
        tp=entry+side*pt_r*dist;ptq=0.;ptx=-1;ptraw=0.
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            if pt_r>0 and ptx<0:
                if side==1 and h[j]>=tp:ptraw=max(o[j],tp);ptx=j
                elif side==-1 and l[j]<=tp:ptraw=min(o[j],tp);ptx=j
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
            if side*(ns-stop)>0:stop=ns
            pk=side*(best-entry)/dist
            if be_trig>0 and pk>=be_trig:
                fl=entry+side*be_lock*dist
                if side*(fl-stop)>0:stop=fl
            if lk_trig>0 and pk>=lk_trig:
                fl=entry+side*lk_frac*pk*dist
                if side*(fl-stop)>0:stop=fl
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        q2=qty
        if ptx>=0 and ptx<=x:
            q1=qty*pt_frac;q2=qty-q1;xp=ptraw*(1-side*slip);fund=-side*raw*q1*(fcum[ptx]-fcum[e])
            net=side*(xp-entry)*q1-(entry+xp)*q1*fee+fund
            out[k,0]=e;out[k,1]=ptx;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(ptraw-raw)/dist;out[k,5]=q1;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*q1*fee-fund;k+=1
        xp=xraw*(1-side*slip);fund=-side*raw*q2*(fcum[x]-fcum[e])
        net=side*(xp-entry)*q2-(entry+xp)*q2*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=q2;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*q2*fee-fund;k+=1
        t=x if x>t else t+1
    return out[:k]

def trades_fn(d,v):
    le,se,_,_=d['sig']['PULL']
    return engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],.0006,.0002,d['fb'],300,
                  v['be_trig'],v['be_lock'],v['lk_trig'],v['lk_frac'],v['pt_r'],v['pt_frac'])

if __name__=='__main__':
    # sanity: with every add-on off this engine must reproduce the baseline exactly
    off=dict(be_trig=0.,be_lock=0.,lk_trig=0.,lk_frac=0.,pt_r=0.,pt_frac=0.)
    for s in B.MAIN10[:3]:
        d=B.coin(s);assert np.allclose(trades_fn(d,off),B.baseline_trades(d)),s
    print('engine copy == baseline OK',flush=True)
    B.run('a3_giveback',VARIANTS,trades_fn,notes='Agent 3 GIVEBACK: BE1R floor entry+0.1R after 1R; LOCKHALF floor 0.5*peak after 2R; PART2R 1/3 off at +2R (two rows).')
