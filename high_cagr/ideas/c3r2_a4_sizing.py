"""C3 round 2, agent 4 - SIZING by trend conviction on top of C3+D (c3bench_d baseline).

MECHANISM. C3's profit is concentrated in a few big-trend trades (top 10% = 173% of net R). The C3 diagnosis (train
cohort) shows entries early in a trend earn far more per trade (cross age <=30 bars: +1.05R, 30-90: +0.39R,
>400: -0.03R), and that moderate EMA50/200 separation (1-2 ATR: +0.59R) beats stretched separation (4-8 ATR: +0.16R).
Young, still-accelerating trends are the ones that turn into the >=30% moves. Putting more risk on those entries and
less on old or stretched ones should capture more of the big moves in R terms. Average risk is meant to stay around
0.5% per trade; tiers are symmetric (1.5 / 1.0 / 0.5) and the realised mean multiplier is reported.

All features are measured at the decision bar k = the D confirmation bar (entry at k+1); data <= k only.
Entries = c3bench_d.confirm_signals(d), weekday mask d['wk'], mode 6 exit (2 ATR stop, 4.5 ATR chandelier), costs
.0006/.0002, funding d['fb'], base 1e4, base risk 0.5% x multiplier, notional cap 0.4 x base unchanged.

PRE-DECLARED VARIANTS (fixed round parameters, single round):
  S1_age    cross age = bars since EMA50 last crossed EMA200 (into the trade side):
            age <= 90 -> 1.5x ; 90 < age <= 400 -> 1.0x ; age > 400 -> 0.5x
  S2_score  3 binary conviction items: (a) cross age <= 180, (b) EMA50 slope in trade direction, e50[k] vs e50[k-20],
            (c) 15 <= ADX14 <= 35.  3 items -> 1.5x ; 2 -> 1.0x ; 0-1 -> 0.5x
  S3_gap    EMA50-EMA200 separation in ATR (trade side), g = side*(e50-e200)/atr:
            g <= 2 -> 1.5x ; 2 < g <= 4 -> 1.0x ; g > 4 -> 0.5x
Realised risk multiplier = qty / qty of the same trade at 1.0x (cap included), averaged over MAIN10 trades.
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench_d as BD
B=BD.B

@njit(cache=True)
def engine_s(o,h,l,c,atr,le,se,al,as_,ml,ms,fee,slip,fcum,warm):
    """mtf_search.engine mode 6 with per-signal risk multiplier (ml for longs, ms for shorts at the signal bar)."""
    n=len(c);out=np.zeros((n,10));k=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        m=ml[t] if side==1 else ms[t]
        q1=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry)
        qty=min(m*.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry)
        best=c[t];xraw=0.;x=e;j=e
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
            best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*4.5*atr[j]
            if side*(ns-stop)>0:stop=ns
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;out[k,9]=qty/q1;k+=1
        t=x if x>t else t+1
    return out[:k]

def cross_age(d):
    s=np.sign(d['e50']-d['e200']);n=len(s);age=np.zeros(n);a=0
    for i in range(n):
        a=a+1 if i>0 and s[i]==s[i-1] else 0;age[i]=a
    return age

def tier(x,lo,hi,rev=False):
    """x<=lo ->1.5, lo<x<=hi ->1.0, >hi ->0.5"""
    return np.where(x<=lo,1.5,np.where(x<=hi,1.,.5))

def mults(d,v):
    n=d['n'];e50,e200,atr=d['e50'],d['e200'],d['atr']
    if v=='S1_age':m=tier(cross_age(d),90,400);return m,m
    if v=='S3_gap':
        g=(e50-e200)/np.where(atr>0,atr,np.nan);gl=np.nan_to_num(g,nan=99.);gs=np.nan_to_num(-g,nan=99.)
        return tier(gl,2,4),tier(gs,2,4)
    if v=='S2_score':
        young=cross_age(d)<=180;prev=np.concatenate([np.full(20,np.nan),e50[:-20]]);adx=d['adx'];ab=(adx>=15)&(adx<=35)
        sl=(young.astype(int)+(e50>prev)+ab);ss=(young.astype(int)+(e50<prev)+ab)
        f=lambda s:np.where(s>=3,1.5,np.where(s==2,1.,.5));return f(sl),f(ss)
    raise ValueError(v)

def trades_ext(d,variant):
    le,se=BD.confirm_signals(d);ml,ms=mults(d,variant['v'])
    return engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],ml.astype(float),ms.astype(float),.0006,.0002,d['fb'],300)

def trades_fn(d,variant):return trades_ext(d,variant)[:,:9]

VARIANTS={k:dict(v=k) for k in ('S1_age','S2_score','S3_gap')}

if __name__=='__main__':
    b=B.baseline();print('C3+D baseline',{k:{p:[round(x,2) for x in v] for p,v in b[k].items()} for k in ('main','other','port')},'| capture',round(BD.BASE_CAPTURE(),1),flush=True)
    # sanity: 1.0x everywhere must reproduce the baseline trades
    d0=B.coin('AVAXUSDT');le,se=BD.confirm_signals(d0);one=np.ones(d0['n'])
    print('sanity identical to baseline:',np.allclose(engine_s(d0['o'],d0['h'],d0['l'],d0['c'],d0['atr'],le,se,d0['wk'],d0['wk'],one,one,.0006,.0002,d0['fb'],300)[:,:9],BD.d_trades(d0)),flush=True)
    BD.run('r2_a4_sizing',VARIANTS,trades_fn,notes=__doc__)
    for k,v in VARIANTS.items():
        for uni,coins in (('MAIN10',B.MAIN10),('OTHER20',B.OTHER20)):
            T=np.concatenate([trades_ext(B.coin(s),v) for s in coins]);m=T[:,9]
            print(f'{k} {uni}: realised mean risk multiplier {m.mean():.3f} | share 1.5x {np.mean(m>1.2)*100:.0f}% 1.0x {np.mean((m>.8)&(m<=1.2))*100:.0f}% 0.5x {np.mean(m<=.8)*100:.0f}%',flush=True)
