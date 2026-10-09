"""pa2_entrymech - Ghoghnous ENTRY MECHANICS and FEES. Pre-declared before any validation or IN15 result of these variants was seen.

HYPOTHESIS. C1's signal (4h key reversal, >= 1.1 ATR) may be fine but its ORDER may not be: the buy/sell-stop at the signal
extreme pays taker fee + slippage and fills on every poke above the extreme, including one-minute wicks that immediately
fail. Two opposite ideas are tested: (a) PATIENCE / maker: a limit order on a retrace into the signal bar gets a better
price (tighter effective stop at equal risk) and pays the LBank maker fee (0.02% instead of 0.06%); (b) CONFIRMATION: only
enter once the following 4h bar CLOSES beyond the signal extreme, i.e. trade the reversals the market has accepted, and
skip the wick-only breaks. Mechanism (b) trades fewer, better reversals; mechanism (a) risks adverse selection (the
limit fills mainly when the reversal is failing).

MECHANISM / ENGINE. engine3 (this file) is a numba copy of pabench.engine2 restricted to C1 exits (stop, or time stop at the
close of the 30th bar after the entry bar, no target). ASSERTED before declaring (scratchpad check.py): mode='stop' gives
trade arrays IDENTICAL (np.array_equal) to pabench2.base_fn, and mode='mkt' identical to engine2 kind 2, on all 35 coins
(2595 trades). Costs as the bench: taker 0.06%/side + 2 bps slip per fill + funding, 0.5% risk of a fixed 1e4 base, cap 1x,
MINSTOP 0.4%, stop = C1's stop (0.1 ATR beyond the signal bar) in every variant. Limit fills (conservative): only when a
minute low (high for shorts) trades THROUGH the limit by max(1 tick, 1 bp), where tick = smallest price increment printed
inside the signal bar (causal); fill at the limit, maker fee 0.02%, no slippage; exit always taker + slip. An order
already marketable when placed (bar t+1 open beyond the limit) fills at that open as a taker. A limit order has no
cancel rule: a minute reaching the stop passed the limit first, so it is filled and stopped in that minute.

TRAIN-ONLY PRE-PASS (OTHER20, TRAIN Calmar / CAGR / DD / train trades / mean R; nothing from 2025+ or IN15 was looked at):
  stop (C1)           0.28 / 10.0% / 35.9% / 841 / 0.131
  mkt (next open)     0.20 /  8.5% / 42.7% / 1088 / 0.111
  conf_x  w1          0.95 / 11.6% / 12.2% / 416 / 0.224   (bar t+1 closes beyond the signal extreme, market at t+2 open)
  conf_x  w2 / w3     0.73 / 0.74  (DD 16.0 / 19.7%)       (any of bars t+1..t+2 / t+1..t+3)
  conf_c  w1 / w2     0.90 / 0.58  (close beyond the signal-bar close)
  conf_x then maker limit back at the extreme: valid 1 bar 0.50 (204 trades), 3 bars 0.33
  lim25 v1/v3/v6      0.11 / 0.12 / 0.03     lim50 v1/v3/v6 0.26 / 0.19 / 0.06    (retrace limit at 25/50% of the range)
  oco25_v1 0.12, oco50_v1 0.25 (limit retrace OR the C1 stop, first fill wins)
  fee check: lim50_v3 with maker 0.19 vs the same fills charged taker fee 0.14 (maker saves ~5.7% of base over train);
  conf_x w1 at 5 bps slip 0.86. Train years conf_x w1: 2022 +12.3, 2023 +7.6, 2024 +17.3 (% at 0.5%).
  Reading: limit retraces suffer adverse selection that the maker fee does not repay; confirmation removes most of the
  2023-type drawdown in train. About 20 train cells were looked at, so expect some winner's-curse shrink.

VARIANTS (fixed parameters):
  mkt          market at the open of bar t+1 (taker), C1 stop
  conf_x       bar t+1 closes beyond the signal extreme (and beyond the stop) -> market at the open of bar t+2
  conf_c       bar t+1 closes beyond the signal-bar close -> market at bar t+2 open
  conf_x_w3    as conf_x but the confirming close may come on bar t+1, t+2 or t+3 (first one)
  conf_x_lim1  conf_x, but enter with a maker limit back at the signal extreme valid 1 bar (retest entry)
  lim50_v1     maker limit at the signal-bar midpoint, valid 1 bar
  lim25_v3     maker limit at 25% retrace from the extreme, valid 3 bars
  oco50_v1     maker limit at the midpoint OR C1's stop order at the extreme (first to fill), valid 1 bar
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from numba import njit
from high_cagr.ideas import pabench2 as Q, pabench as PB

MAKER=.0002          # LBank maker fee per side (taker = PB.FEE = 0.06%)
THR_BP=1e-4          # a limit fills only if the price trades THROUGH it by max(1 tick, 1 bp)

@njit(cache=True)
def bar_tick(P,bm,nb):
    """Causal price increment per bar: smallest positive gap between distinct OHLC prices printed inside bar t."""
    out=np.full(nb,np.nan)
    for t in range(nb):
        a=P[t*bm:(t+1)*bm].ravel()
        if len(a)<2:continue
        x=np.sort(a);best=1e300
        for i in range(1,len(x)):
            g=x[i]-x[i-1]
            if g>x[i]*1e-9 and g<best:best=g
        if best<1e300:out[t]=best
    return out

@njit(cache=True)
def engine3(P,fcum,bm,side,kind,lev,lev2,stp,val,thr,mult,hold,fee,maker,slip,risk,cap,minstop,warm):
    """Copy of pabench.engine2 restricted to C1 exits (stop or time stop at the close of the hold-th bar, no target),
    with extra entry kinds. kind 1 = buy/sell-stop at lev (engine2 rules, taker); 2 = market at bar t+1 open (taker);
    3 = limit at lev2 valid val bars: fills only when the minute low (high for shorts) trades THROUGH lev2 by thr,
        at lev2, maker fee and no slippage; if the order is already marketable at placement (bar t+1 open beyond lev2)
        it fills at that open as a taker. No cancel rule: a minute that reaches the stop has passed the limit first,
        so it is filled and stopped in that same minute (conservative).
    4 = OCO: limit at lev2 (as 3) AND stop at lev (as 1, incl. its cancel-on-stop rule), whichever fills first."""
    nb=len(side);nm=P.shape[0];out=np.zeros((nb,10));k=0;free=0;root=0
    for t in range(warm,nb-1):
        s=side[t]
        if s==0 or mult[t]<=0:continue
        m0=(t+1)*bm
        if m0<free or m0>=nm:continue
        em=-1;raw=0.;mk=False;kd=kind[t]
        if kd==2:em=m0;raw=P[m0,0]
        elif kd==1:
            lv=lev[t];mend=min((t+1+val[t])*bm,nm)
            for m in range(m0,mend):
                if (s==1 and P[m,2]<=stp[t]) or (s==-1 and P[m,1]>=stp[t]):
                    if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):break
                if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        else:
            l2=lev2[t];lv=lev[t];mend=min((t+1+val[t])*bm,nm);stopok=True
            if s*(P[m0,0]-l2)<=0:em=m0;raw=P[m0,0]
            else:
                for m in range(m0,mend):
                    if (s==1 and P[m,2]<=l2-thr[t]) or (s==-1 and P[m,1]>=l2+thr[t]):raw=l2;em=m;mk=True;break
                    if kd==4 and stopok:
                        if (s==1 and P[m,2]<=stp[t]) or (s==-1 and P[m,1]>=stp[t]):
                            if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):stopok=False
                        if stopok:
                            if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                            if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        if em<0:continue
        if mk:
            entry=raw;stop=stp[t];dist=s*(entry-stop)
            if not dist/entry>=minstop:continue
            qty=min(risk*mult[t]*1e4/(dist+entry*(maker+fee+slip)),cap*1e4/entry)
        else:
            entry=raw*(1+s*slip);stop=stp[t];dist=s*(entry-stop)
            if not dist/entry>=minstop:continue
            qty=min(risk*mult[t]*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        x=-1;xraw=0.;ebar=em//bm;rem=qty
        for m in range(em,nm):
            hi=P[m,1];lo=P[m,2];op=P[m,0] if m>em else raw
            if s==1:
                if lo<=stop:xraw=min(op,stop);x=m;break
            else:
                if hi>=stop:xraw=max(op,stop);x=m;break
            if (m+1)%bm==0:
                b=m//bm;cl=P[m,3]
                if hold>0 and b-ebar>=hold:xraw=cl;x=m;break
        if x<0:x=nm-1;xraw=P[nm-1,3]
        xp=xraw*(1-s*slip);fund=-s*raw*rem*(fcum[x+1]-fcum[em])
        if mk:cost=(entry*maker+xp*fee)*rem
        else:cost=(entry+xp)*rem*fee
        net=s*(xp-entry)*rem-cost+fund
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=rem;out[k,6]=entry;out[k,7]=xp;out[k,8]=cost-fund;out[k,9]=root;k+=1
        root+=1;free=x+1
    return out[:k]

def build(d,mode,frac=0.,valid=1,conf=None,cwin=1,centry='mkt'):
    """Signal arrays for one entry mechanic, all derived from the C1 signal on bar t (bar data <= t, or <= t+1 for conf)."""
    side=Q.c1_side(d);n=len(side);g=d['sig'];h,l,c=d['h'][:n],d['l'][:n],d['c'][:n]
    lev=g['lev'][:n].astype(np.float64).copy();stp=g['stp'][:n].astype(np.float64).copy()
    kind=np.ones(n,np.int8);val=np.full(n,int(valid),np.int64);lev2=np.full(n,np.nan)
    if mode=='stop':val=g['val'][:n].astype(np.int64).copy()
    elif mode=='mkt':kind[:]=2
    elif mode in ('lim','oco'):
        kind[:]=3 if mode=='lim' else 4
        lev2=np.where(side==1,h-frac*(h-l),l+frac*(h-l))
    elif mode=='conf':          # a bar t+j (j=1..cwin) CLOSES beyond the signal extreme (conf='x') or beyond the signal close (conf='c')
        ref=np.where(side==1,h,l) if conf=='x' else c       # -> market at the following open (centry='mkt') or a limit back at
        s2=np.zeros(n,np.int8);st2=np.full(n,np.nan);l2=np.full(n,np.nan)   # the signal extreme valid `valid` bars (centry='lim')
        for t in np.nonzero(side)[0]:
            for j in range(1,cwin+1):
                u=t+j
                if u>=n or side[t]*(c[u]-stp[t])<=0:break
                if side[t]*(c[u]-ref[t])>0:
                    if s2[u]==0:s2[u]=side[t];st2[u]=stp[t];l2[u]=ref[t] if conf=='x' else (h[t] if side[t]==1 else l[t])
                    break
        side,stp,lev2=s2,st2,l2;kind[:]=2 if centry=='mkt' else 3
    return side,kind,lev,lev2,stp,val

def run3(d,mode,frac=0.,valid=1,conf=None,cwin=1,centry='mkt',maker=MAKER,slip=None):
    side,kind,lev,lev2,stp,val=build(d,mode,frac,valid,conf,cwin,centry);n=len(side);P=np.asarray(d['P'])
    thr=np.maximum(np.nan_to_num(bar_tick(P,240,n),nan=0.),THR_BP*np.nan_to_num(np.abs(lev2)))
    return engine3(P,d['fc'],240,side,kind,lev,lev2,stp,val,thr,np.ones(n),30,PB.FEE,float(maker),PB.SLIP if slip is None else slip,
                   PB.RISK,PB.CAP,PB.MINSTOP,250)

def fn(d,variant):return run3(d,**variant)

VARIANTS={'mkt':dict(mode='mkt'),'conf_x':dict(mode='conf',conf='x'),'conf_c':dict(mode='conf',conf='c'),
          'conf_x_w3':dict(mode='conf',conf='x',cwin=3),'conf_x_lim1':dict(mode='conf',conf='x',centry='lim',valid=1),
          'lim50_v1':dict(mode='lim',frac=.5,valid=1),'lim25_v3':dict(mode='lim',frac=.25,valid=3),'oco50_v1':dict(mode='oco',frac=.5,valid=1)}

if __name__=='__main__':
    Q.run_idea('entrymech',VARIANTS,fn,notes=__doc__)
