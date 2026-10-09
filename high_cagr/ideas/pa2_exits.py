"""pa2_exits - exit engineering for Ghoghnous C1 (entry, stop, sizing, coins unchanged; only the EXIT changes).

HYPOTHESIS. C1's money is in slow trades held to the 30-bar time stop (anatomy: 381 time exits = +531R, 460 stops = -458R,
time-exit MFE peaks late, median bar 21.8). A better exit can either (a) keep the paying tail longer (volatility-scaled
or profit-conditional time stop), or (b) cut losers/give-back earlier without trimming the tail (opposite key reversal),
and so raise Calmar stand-alone. Trailing/partial exits are tested because the owner asked, with a negative prior
(anatomy: BE/trail/partials cut the tail).

MECHANISM. Low-volatility coins move fewer ATRs per bar, so a fixed 30-bar clock exits them early; a trade still >= N R
in profit at bar 30 is a trend that has not ended; an opposite C1 key reversal is the same evidence C1 uses for entry,
read against the open trade.

OWN ENGINE. engine_x = copy of pabench.engine2 with extra exit rules; with defaults it reproduces Q.base_fn exactly
(np.array_equal on all OTHER20 coins, asserted at start).

TRAIN-ONLY PRE-PASS (entries < 2025-01-01, OTHER20, train Calmar of the daily series; base 0.28 CAGR 10.0% DD 35.9%):
  841 train trades, 387 time exits: 210 at >= 1R, 106 at >= 2R, 63 below 0R at the time stop.
  volhold 0.34 | ext0.5_60 0.30 | ext1_60 0.31 | ext2_60 0.32 | struct1R 0.14 | struct2R 0.19 | oppKR 0.28 (DD 30.6%)
  chandelier 2R/3ATR 0.15 | same + hold 60 0.11 | partial 50% at 3R 0.26 | ext1_180 + chandelier 1R 0.07
  combos: volh+ext1_60 0.25 | volh+ext2_60 0.33 | volh+opp 0.32 | ext2_60+opp 0.37 | volh+ext2_60+opp 0.41 | ext1_90 0.32
  No single exit reaches the Q1 bar (train >= 0.43). 18 train cells were looked at, so V8 (best train combo) carries
  selection bias; the others use the parameters stated in the task.

VARIANTS (fixed before any validation / IN15 / gate result was seen):
  V1 volhold   time stop = clip(round(30 * median500(ATR/close) / (ATR/close at signal)), 15, 60) bars
  V2 ext1_60   at bar 30 keep holding while the 4h close >= entry + 1R, exit at the first close below or at bar 60
  V3 ext2_60   same with 2R
  V4 struct1R  after best close >= 1R, stop ratchets to the latest confirmed 2/2 swing low (high); 30-bar stop kept
  V5 oppKR     exit at the close of any bar that prints an opposite-side C1 signal; 30-bar stop kept
  V6 chand2R   chandelier best close - 3 ATR once the best close >= 2R; 30-bar stop kept
  V7 part3R    close 50% at 3R, runner to the stop / 30-bar exit
  V8 combo     V1 + V3 + V5 (volhold, extend while >= 2R to bar 60, opposite-KR exit)
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np,pandas as pd
from numba import njit
from high_cagr.ideas import pabench2 as Q, pabench as PB

@njit(cache=True)
def engine_x(P,fcum,bm,side,kind,lev,stp,val,atr,mult,holdarr,pfrac,pr,tra,tatr,ext_r,ext_max,st_r,pivlo,pivhi,opp,
             fee,slip,risk,cap,minstop,warm):
    """Copy of pabench.engine2 (C1 settings: no target, no BE, no early exit) with extra EXIT rules.
    holdarr[t]  time stop (bars after the entry bar) for a signal on bar t; engine2 = 30 everywhere.
    ext_r>0     at/after the time stop, keep holding while the 4h close is >= entry + ext_r R, until bar ext_max.
    st_r>0      structure trail: once the best 4h close is >= st_r R, stop ratchets to the most recent CONFIRMED
                swing low (long; pivlo[b] = low of the latest 2/2 pivot confirmed by the close of bar b) / swing high (short).
    opp[b]      +1/-1 = a C1 signal of that side on closed bar b; a position of the opposite side exits at that close.
    tra>0       engine2 chandelier: after best close >= tra R, stop = best close - tatr ATR (4h closes).
    pfrac>0     engine2 partial: close pfrac of the size at pr R, the rest continues."""
    nb=len(side);nm=P.shape[0];out=np.zeros((2*nb,10));k=0;free=0;root=0
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
        qty=min(risk*mult[t]*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        hold=holdarr[t]
        ptp=entry+s*pr*dist;pq=qty*pfrac if pfrac>0 else 0.;pdone=pfrac<=0
        best=-1e300 if s==1 else 1e300;armed=False;sarmed=False
        x=-1;xraw=0.;ebar=em//bm;rem=qty
        for m in range(em,nm):
            hi=P[m,1];lo=P[m,2];op=P[m,0] if m>em else raw
            if s==1:
                if lo<=stop:xraw=min(op,stop);x=m;break
            else:
                if hi>=stop:xraw=max(op,stop);x=m;break
            if not pdone and ((s==1 and hi>=ptp) or (s==-1 and lo<=ptp)):
                pxr=max(op,ptp) if s==1 else min(op,ptp);xp=pxr*(1-s*slip);fund=-s*raw*pq*(fcum[m+1]-fcum[em])
                net=s*(xp-entry)*pq-(entry+xp)*pq*fee+fund
                out[k,0]=em;out[k,1]=m;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(pxr-raw)/dist;out[k,5]=pq;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*pq*fee-fund;out[k,9]=root;k+=1
                rem=qty-pq;pdone=True
            if (m+1)%bm==0:
                b=m//bm;cl=P[m,3]
                if hold>0 and b-ebar>=hold:
                    if not (ext_r>0 and b-ebar<ext_max and s*(cl-entry)>=ext_r*dist):xraw=cl;x=m;break
                if b<len(opp) and opp[b]==-s:xraw=cl;x=m;break
                best=max(best,cl) if s==1 else min(best,cl)
                if tra>0:
                    if s*(best-entry)>=tra*dist:armed=True
                    if armed:
                        ns=best-s*tatr*atr[b]
                        if s*(ns-stop)>0:stop=ns
                if st_r>0 and b<len(pivlo):
                    if s*(best-entry)>=st_r*dist:sarmed=True
                    if sarmed:
                        ns=pivlo[b] if s==1 else pivhi[b]
                        if ns==ns and s*(ns-stop)>0:stop=ns
        if x<0:x=nm-1;xraw=P[nm-1,3]
        xp=xraw*(1-s*slip);fund=-s*raw*rem*(fcum[x+1]-fcum[em])
        net=s*(xp-entry)*rem-(entry+xp)*rem*fee+fund
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=rem;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*rem*fee-fund;out[k,9]=root;k+=1
        root+=1;free=x+1
    return out[:k]

def pivots(h,l):
    """pivlo[b]/pivhi[b] = low/high of the latest 2-left/2-right pivot bar j with j+2 <= b (bar data <= b only)."""
    n=len(l);pl=np.full(n,np.nan);ph=np.full(n,np.nan);cl=np.nan;ch=np.nan
    for b in range(n):
        j=b-2
        if j>=2:
            if l[j]<l[j-1] and l[j]<l[j-2] and l[j]<l[j+1] and l[j]<l[j+2]:cl=l[j]
            if h[j]>h[j-1] and h[j]>h[j-2] and h[j]>h[j+1] and h[j]>h[j+2]:ch=h[j]
        pl[b]=cl;ph[b]=ch
    return pl,ph

def volhold(d,n,base=30,lo=15,hi=60,win=500):
    """hold = clip(round(base * median(ATR%% over the last win bars) / ATR%% now), lo, hi); bar data <= t."""
    ap=pd.Series(d['atr'][:n]/d['c'][:n]);ref=ap.rolling(win,min_periods=100).median()
    h=np.round(base*ref/ap).to_numpy();h=np.where(np.isfinite(h),h,base);return np.clip(h,lo,hi).astype(np.int64)

def runx(d,hold=30,volh=False,ext_r=0.,ext_max=0,st_r=0.,opp=False,tra=0.,tatr=3.,pfrac=0.,pr=1.):
    side=Q.c1_side(d);n=len(side);g=d['sig']
    ha=volhold(d,n) if volh else np.full(n,int(hold),np.int64)
    pl,ph=pivots(d['h'][:n],d['l'][:n]) if st_r>0 else (np.zeros(0),np.zeros(0))
    op=side.astype(np.int8) if opp else np.zeros(0,np.int8)
    return engine_x(d['P'],d['fc'],240,side,g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],np.ones(n),ha,
                    float(pfrac),float(pr),float(tra),float(tatr),float(ext_r),int(ext_max),float(st_r),pl,ph,op,
                    PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP,250)

def fn(d,variant):return runx(d,**variant)

def assert_baseline(coins=('LINKUSDT','CRVUSDT','AXSUSDT')):
    for s in coins:
        d=PB.coin(s);a=np.asarray(Q.base_fn(d));b=runx(d)
        assert a.shape==b.shape and np.array_equal(a,b),f'engine_x does not reproduce C1 on {s}'

VARIANTS={'V1_volhold':dict(volh=True),'V2_ext1_60':dict(ext_r=1.,ext_max=60),'V3_ext2_60':dict(ext_r=2.,ext_max=60),
          'V4_struct1R':dict(st_r=1.),'V5_oppKR':dict(opp=True),'V6_chand2R':dict(tra=2.,tatr=3.),'V7_part3R':dict(pfrac=.5,pr=3.),
          'V8_combo':dict(volh=True,ext_r=2.,ext_max=60,opp=True)}

if __name__=='__main__':
    assert_baseline(tuple(PB.OTHER20));print('engine_x reproduces C1 exactly on OTHER20',flush=True)
    Q.run_idea('exits',VARIANTS,fn,notes=__doc__)
