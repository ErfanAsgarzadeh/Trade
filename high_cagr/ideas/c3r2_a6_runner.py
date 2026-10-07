"""C3 round 2, agent 6 - HIGHER-TIMEFRAME RUNNER LEG on top of C3+D (c3bench_d baseline).

Mechanism: the 4.5 ATR(4h) chandelier is sized for 4h noise; on a multi-week trend the first normal 4h correction
(often a daily pullback) takes the whole position out, and C3 then waits for a fresh PULL+D signal. Once a trade has
PROVEN itself (best 4h close >= entry + 3R, R = initial 2 ATR stop distance), the trend is established; letting part
of the position trail on the DAILY timeframe lets it sit through daily-scale pullbacks and ride the multi-week leg,
while the rest keeps the normal 4h chandelier (keeps C3's profit-taking profile on the trades that fade).

Own engine copy (identical to mtf_search.engine mode 6 for entry, initial stop, sizing, costs .0006/.0002, funding
d['fb'], base 1e4, total initial risk 0.5%). The position is split at entry into a MAIN leg (fraction 1-f) and a
RUNNER leg (fraction f), both sharing the same initial stop and 4h chandelier until activation (so total initial risk
is unchanged at 0.5%). After the +3R activation (decided on a bar close, effective from the next bar) the runner
leaves the 4h chandelier and uses a daily trail, ratcheting only in the trade's favour, floored at the entry price
(breakeven). Daily bars = 6 consecutive 4h bars (UTC day, as c3bench_d uses c[5::6]); a daily level is only updated
when a day has completed (bar index % 6 == 5) - strictly causal. One position per coin: no new entry until ALL legs
are closed. Each leg is emitted as its own bench row (own qty, exit, cost) so mark-to-market works.

PRE-DECLARED variants (fixed round parameters, no post-hoc changes):
  R50_DON20  f=0.5, activation +3R, runner trail = 20-day Donchian (lowest daily low of the last 20 completed days;
             highest daily high for shorts) - the classic turtle-style daily exit.
  R50_ATR3   f=0.5, activation +3R, runner trail = best 4h close since entry - 3 x daily ATR14 (Wilder, completed
             days), updated at day closes - a daily chandelier.
  R100_DON20 f=1.0 (the whole position switches to the 20-day Donchian at +3R) - maximum trend exposure, tests whether
             splitting matters.
Inputs: C3+D entries via c3bench_d.confirm_signals(d), weekend mask d['wk'] on the decision bar.
"""
from pathlib import Path
import sys
import numpy as np
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench_d as BD
from high_cagr.ideas import ltf_search as L

VARIANTS={'R50_DON20':dict(f=.5,trig=3.,kind=0,N=20,k=3.),
          'R50_ATR3':dict(f=.5,trig=3.,kind=1,N=20,k=3.),
          'R100_DON20':dict(f=1.,trig=3.,kind=0,N=20,k=3.)}

def daily_levels(d,N):
    """Per 4h bar j: levels from daily bars completed by the end of bar j (days 0..(j+1)//6-1)."""
    h,l,c,n=d['h'],d['l'],d['c'],d['n'];nd=n//6
    dh=h[:nd*6].reshape(nd,6).max(1);dl=l[:nd*6].reshape(nd,6).min(1);dc=c[:nd*6].reshape(nd,6)[:,-1]
    pc=np.concatenate([[dc[0]],dc[:-1]]) if nd else dc
    tr=np.maximum(dh-dl,np.maximum(np.abs(dh-pc),np.abs(dl-pc)));datr=L.wilder(tr,14) if nd else tr
    lo=np.full(nd,np.nan);hi=np.full(nd,np.nan)
    for i in range(N-1,nd):lo[i]=dl[i-N+1:i+1].min();hi[i]=dh[i-N+1:i+1].max()
    k=(np.arange(n)+1)//6-1;ok=k>=0;kk=np.clip(k,0,max(nd-1,0))
    f=lambda a:np.where(ok,a[kk],np.nan) if nd else np.full(n,np.nan)
    return f(lo),f(hi),f(np.asarray(datr,float))

@njit(cache=True)
def engine_runner(o,h,l,c,atr,le,se,al,as_,fee,slip,fcum,warm,f,trig,kind,k,dlo,dhi,datr):
    n=len(c);out=np.zeros((2*n,9));m=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        stop=entry-side*2.*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry)
        qs=np.array([qty*(1.-f),qty*f]);stops=np.array([stop,stop]);xr=np.zeros(2);xb=np.full(2,-1)
        best=c[t];act=False;sw=False;j=e
        while j<n:
            for g in range(2):
                if xb[g]>=0 or qs[g]<=0:continue
                if side==1 and l[j]<=stops[g]:xr[g]=min(o[j],stops[g]);xb[g]=j
                elif side==-1 and h[j]>=stops[g]:xr[g]=max(o[j],stops[g]);xb[g]=j
            done=True
            for g in range(2):
                if qs[g]>0 and xb[g]<0:done=False
            if done:break
            best=max(best,c[j]) if side==1 else min(best,c[j])
            ns=best-side*4.5*atr[j]
            if xb[0]<0 and side*(ns-stops[0])>0:stops[0]=ns
            if xb[1]<0:
                if not act:
                    if side*(ns-stops[1])>0:stops[1]=ns
                    if side*(best-entry)>=trig*dist:act=True
                if act and j%6==5:
                    if kind==0:lv=dlo[j] if side==1 else dhi[j]
                    else:lv=best-side*k*datr[j]
                    if lv==lv:
                        if side*(lv-entry)<0:lv=entry
                        if not sw:stops[1]=lv;sw=True          # first daily level replaces the 4h chandelier
                        elif side*(lv-stops[1])>0:stops[1]=lv  # then ratchet only in favour
            j+=1
        last=e
        for g in range(2):
            if qs[g]<=0:continue
            if xb[g]<0:xr[g]=c[n-1];xb[g]=n-1
            x=xb[g];q=qs[g];xp=xr[g]*(1-side*slip);fund=-side*raw*q*(fcum[x]-fcum[e])
            net=side*(xp-entry)*q-(entry+xp)*q*fee+fund
            out[m,0]=e;out[m,1]=x;out[m,2]=side;out[m,3]=net/1e4;out[m,4]=side*(xr[g]-raw)/dist;out[m,5]=q
            out[m,6]=entry;out[m,7]=xp;out[m,8]=(entry+xp)*q*fee-fund;m+=1
            if x>last:last=x
        t=last if last>t else t+1
    return out[:m]

def trades_fn(d,v):
    le,se=BD.confirm_signals(d);dlo,dhi,datr=daily_levels(d,v['N'])
    return engine_runner(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],.0006,.0002,d['fb'],300,
                         v['f'],v['trig'],v['kind'],v['k'],dlo,dhi,datr)

if __name__=='__main__':
    # sanity: f=0 must reproduce the C3+D baseline exactly
    d=BD.B.coin('AVAXUSDT');a=trades_fn(d,dict(f=0.,trig=3.,kind=0,N=20,k=3.));b=BD.d_trades(d)
    print('f=0 reproduces C3+D:',a.shape==b.shape and np.allclose(a,b),flush=True)
    BD.run('a6r2_runner',VARIANTS,trades_fn,notes=__doc__)
