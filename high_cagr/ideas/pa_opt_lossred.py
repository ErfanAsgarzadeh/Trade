"""pa_opt_lossred: cutting losers early in the PA sleeve (4h KEYREV).

TRAIN-ONLY DIAGNOSTIC (baseline trades of OTHER20, entries < 2024-12-31, run before the variants were declared; 1104 trades):
 667 losers (sum -629.0 R), 437 winners (sum +679.3 R). Loser MFE pctl 10/25/50/75/90 = 0.06/0.19/0.42/0.88/1.35 R; winner MFE
 1.01/1.58/1.89/1.97/1.99. Loser bars-to-exit 1/2/6/13/28 vs winner 3/7/19/30/30. 55% of losers never reached 0.5R, 21% reached 1R.
 Best 4h close after 3 bars <0R: 114 of 427 losers (-109.0 R) but also 29 of 380 winners (+39.7 R); <0.25R: 234 losers (-219.9 R)
 vs 105 winners (+128.3 R); <0.5R: 329 losers (-304 R) vs 199 winners (+262 R). Trades lasting >=10 bars sum +193.9 R, >=20 bars +161.8 R
 (slow trades are the profitable ones, so shortening the time stop is expected to HURT; only one shorter hold is tested).
HYPOTHESIS. Losers show no follow-through early (low MFE); cutting them before the full -1R stop reduces average loss more than it
 costs in winners that start slowly. Winners and losers overlap strongly after 3 bars, so only the clearly negative tail is cut.
MECHANISM. Same signals/entries/stops/2R target; only the exit rule changes (own engine copy engine3 = pabench.engine2 without
 partial/trail + invalidation exit + gap skip; assert_reproduces() checks identical trades vs PB.run for default and for
 early/be/hold/valid parameters). Invalidation level = signal-bar midpoint (h+l)/2 of bar t (causal): exit at a 4h close beyond it.
VARIANTS (fixed before any variant result):
 A hold20      time stop 20 bars
 B early3_r0   exit at close of bar 3 after entry if best close so far < 0R (early_bars=3, early_r=0)
 C early6_r25  exit at close of bar 6 if best close so far < 0.25R
 D be1         stop to breakeven+costs after MFE 1R
 E be05        stop to breakeven+costs after MFE 0.5R
 F inval_mid   exit on 4h close beyond signal bar midpoint
 G valid1      entry stop order valid 1 bar only
 H gap25       skip if entry gaps through the trigger by > 25% of (trigger - stop) distance
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from numba import njit
from high_cagr.ideas import pabench as PB

@njit(cache=True)
def engine3(P,fcum,bm,side,kind,lev,stp,val,atr,mult,invl,target_r,hold,be_r,eb_n,eb_r,inv_on,gapfrac,fee,slip,risk,cap,minstop,warm):
    """Copy of pabench.engine2 (no partial/trail) + invalidation exit (4h close beyond invl[t]) + gap skip + 4 diag columns."""
    nb=len(side);nm=P.shape[0];out=np.zeros((2*nb,14));k=0;free=0;root=0
    for t in range(warm,nb-1):
        s=side[t]
        if s==0 or mult[t]<=0:continue
        m0=(t+1)*bm
        if m0<free or m0>=nm:continue
        em=-1;raw=0.
        if kind[t]==2:em=m0;raw=P[m0,0]
        else:
            lv=lev[t];mend=min((t+1+val[t])*bm,nm)
            for m in range(m0,mend):
                if (s==1 and P[m,2]<=stp[t]) or (s==-1 and P[m,1]>=stp[t]):
                    if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):break
                if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        if em<0:continue
        entry=raw*(1+s*slip);stop=stp[t];dist=s*(entry-stop)
        if not dist/entry>=minstop:continue
        if gapfrac>0 and kind[t]!=2:
            if s*(raw-lev[t])>gapfrac*s*(lev[t]-stp[t]):continue
        qty=min(risk*mult[t]*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        tp=entry+s*target_r*dist if target_r>0 else 0.
        be=entry*(1+s*(2*fee+2*slip));best=-1e300 if s==1 else 1e300;mfe=0.
        x=-1;xraw=0.;ebar=em//bm;rem=qty;bc3=-9.;
        for m in range(em,nm):
            hi=P[m,1];lo=P[m,2];op=P[m,0] if m>em else raw
            if s==1:
                if lo<=stop:xraw=min(op,stop);x=m;break
            else:
                if hi>=stop:xraw=max(op,stop);x=m;break
            if target_r>0:
                if (s==1 and hi>=tp) or (s==-1 and lo<=tp):xraw=max(op,tp) if s==1 else min(op,tp);x=m;break
            fav=(hi-entry)/dist if s==1 else (entry-lo)/dist
            if fav>mfe:mfe=fav
            if be_r>0 and mfe>=be_r and s*(be-stop)>0:stop=be
            if (m+1)%bm==0:
                b=m//bm;cl=P[m,3]
                if hold>0 and b-ebar>=hold:xraw=cl;x=m;break
                best=max(best,cl) if s==1 else min(best,cl)
                if b-ebar==3:bc3=s*(best-entry)/dist
                if eb_n>0 and b-ebar==eb_n and s*(best-entry)<eb_r*dist:xraw=cl;x=m;break
                if inv_on>0 and s*(cl-invl[t])<0:xraw=cl;x=m;break
        if x<0:x=nm-1;xraw=P[nm-1,3]
        xp=xraw*(1-s*slip);fund=-s*raw*rem*(fcum[x+1]-fcum[em])
        net=s*(xp-entry)*rem-(entry+xp)*rem*fee+fund
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=rem;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*rem*fee-fund;out[k,9]=root
        out[k,10]=mfe;out[k,11]=(x//bm)-ebar;out[k,12]=bc3;out[k,13]=dist/entry
        k+=1;root+=1;free=x+1
    return out[:k]

def midlevel(d):
    """signal-bar midpoint (bar t only -> causal)."""
    return (d['h']+d['l'])/2.

def run3(d,target_r=2.,hold=30,be_r=0.,early_bars=0,early_r=0.,inval=False,valid=None,gapfrac=0.):
    g=d['sig'];sd=g['side'];n=len(sd);mu=np.ones(n)
    vl=g['val'][:n] if valid is None else np.full(n,int(valid),np.int64)
    return engine3(d['P'],d['fc'],240,sd,g['kind'][:n],g['lev'][:n],g['stp'][:n],vl,d['atr'][:n],mu,midlevel(d)[:n],float(target_r),int(hold),float(be_r),
                   int(early_bars),float(early_r),1 if inval else 0,float(gapfrac),PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP,250)

def assert_reproduces():
    for s in ('LINKUSDT','CRVUSDT',PB.OTHER20[0],PB.OTHER20[5]):
        d=PB.coin(s);a=PB.run(d);b=run3(d)[:,:10]
        assert a.shape==b.shape and np.allclose(a,b),f'engine3 does not reproduce baseline on {s}'
        a=PB.run(d,early_bars=3,early_r=.5,be_r=1.,hold=20,valid=2);b=run3(d,early_bars=3,early_r=.5,be_r=1.,hold=20,valid=2)[:,:10]
        assert a.shape==b.shape and np.allclose(a,b),f'engine3 does not reproduce params on {s}'

VARIANTS={'A_hold20':dict(hold=20),'B_early3_r0':dict(early_bars=3,early_r=0.),'C_early6_r25':dict(early_bars=6,early_r=.25),
 'D_be1':dict(be_r=1.),'E_be05':dict(be_r=.5),'F_inval_mid':dict(inval=True),'G_valid1':dict(valid=1),'H_gap25':dict(gapfrac=.25)}
def fn(d,v):return run3(d,**v)
def main():
    assert_reproduces();PB.run_idea('lossred',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
