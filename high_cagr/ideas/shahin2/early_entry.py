"""Entry timing for Shahin (PREDECLARED.md addendum, written before this file was run): close entry (as shipped) vs stop entry.

Shahin's long signal is: close[b] > max(Donchian10 high of the 10 bars before b, Kumo top at b) (shorts mirrored); the bot
enters at that close. Both thresholds are known when bar b OPENS, so a resting stop order at that level is implementable.
  CLOSE : enter at the close of b (as shipped)          stop = entry - 2 x ATR[b]
  STOP  : enter intrabar the first minute the level trades (fill at max(open, level) + slippage), stop = entry - 2 x ATR[b-1]
          (ATR of the last CLOSED bar); filters use the last closed bar (b-1)
Same filters (ATR-regime >= 1, late-entry gate 60 bars / 0.1521 on the last closed close, stop >= 1.2 %), same exits on
minute data: stop, Donchian10 opposite-channel trail on 4h closes, profit floor 1R -> +0.1R; one position per coin, no pyramid,
no slots, costs 0.06 %/side + 2 bps + funding. Compared in R per trade and as a daily R curve summed over coins
(five Shahin coins and, separately, the 30 coins it never traded). Pass = STOP beats CLOSE in total R AND R-curve Calmar
in TRAIN and in VALID on the five coins, and in total R on the 30 coins.
  RETEST3/6 (added before running them): the close signal of b, then a resting limit at the breakout level for 3 / 6 bars;
  unfilled = no trade. Reported only (not part of the pass rule).
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import xuni as X, pa_bot as PBOT
from high_cagr.ideas.shahin2 import lab as LB
from high_cagr.ideas.winrate import ledger as LG
BM=240;FEE=.0006;SLIP=.0002;LATE=.1521

@njit(cache=True)
def engine(P,fc,lv_l,lv_s,atr,c4,trail_l,trail_s,ok_l,ok_s,mode,fee,slip):
    nb=len(c4);nm=P.shape[0];out=np.zeros((nb,5));k=0;b=61
    while b<nb-1:
        s=0;em=-1;e=0.;stop=0.
        if mode==0:                                    # close entry at the close of b
            if ok_l[b] and c4[b]>lv_l[b]:s=1
            elif ok_s[b] and c4[b]<lv_s[b]:s=-1
            if s!=0:
                em=(b+1)*BM;e=P[em,0]*(1+s*slip) if em<nm else 0.;stop=e-s*2*atr[b]
        elif mode>=2:                                  # retest: close signal at b, then a limit at the breakout level for (mode-1) bars
            if ok_l[b] and c4[b]>lv_l[b]:s=1
            elif ok_s[b] and c4[b]<lv_s[b]:s=-1
            if s!=0:
                lv=lv_l[b] if s==1 else lv_s[b]
                for m in range((b+1)*BM,min((b+mode)*BM,nm)):
                    if (s==1 and P[m,2]<=lv) or (s==-1 and P[m,1]>=lv):
                        em=m;e=(min(P[m,0],lv) if s==1 else max(P[m,0],lv))*(1+s*slip);break
                if em<0:
                    b+=1;continue
                stop=e-s*2*atr[b]
        else:                                          # stop entry during bar b at the level known at its open
            for m in range(b*BM,min((b+1)*BM,nm)):
                if ok_l[b-1] and P[m,1]>=lv_l[b]:
                    s=1;em=m;e=max(P[m,0],lv_l[b])*(1+slip);break
                if ok_s[b-1] and P[m,2]<=lv_s[b]:
                    s=-1;em=m;e=min(P[m,0],lv_s[b])*(1-slip);break
            if s!=0:stop=e-s*2*atr[b-1]
        if s==0 or em<0 or em>=nm or s*(e-stop)/e<.012:
            b+=1;continue
        dist=s*(e-stop);mfe=0.;x=-1;xr=0.;m=em
        while m<nm:
            if (s==1 and P[m,2]<=stop) or (s==-1 and P[m,1]>=stop):
                xr=min(P[m,0],stop) if s==1 else max(P[m,0],stop);x=m;break
            fav=(P[m,1]-e)/dist if s==1 else (e-P[m,2])/dist
            if fav>mfe:mfe=fav
            if mfe>=1.:
                fl=e+s*.1*dist
                if s*(fl-stop)>0:stop=fl
            if (m+1)%BM==0:
                bb=m//BM;line=trail_l[bb] if s==1 else trail_s[bb]
                if s*(c4[bb]-line)<0:
                    xr=c4[bb];x=m;break
                if s*(line-stop)>0:stop=line
            m+=1
        if x<0:
            x=nm-1;xr=P[nm-1,3]
        xp=xr*(1-s*slip);net=s*(xp-e)/e-fee*(1+xp/e)-s*(fc[x+1]-fc[em])
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/(dist/e);out[k,4]=dist/e;k+=1
        b=x//BM+1
    return out[:k]

def coin_arrays(s):
    f=X.frame(s);P,fc=PBOT.load_coin(s);n=len(P)//BM;step=BM*60000
    bnd=rs.START+np.arange(n)*step;ix=np.searchsorted(f.timestamp.to_numpy(np.int64),bnd)   # row of the bar that STARTS at bnd
    ix=np.minimum(ix,len(f)-1);g=lambda c:f[c].to_numpy()[ix]
    lv_l=np.maximum(g('donchian_high_10'),g('kumo_top'));lv_s=np.minimum(g('donchian_low_10'),g('kumo_bottom'))
    c=g('close');atr=g('atr');ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix]
    cl=f.close.to_numpy();r60=np.log(cl/np.roll(cl,60));r60[:60]=np.nan;r60=r60[ix]
    with np.errstate(invalid='ignore'):base=(ar>=1.)&np.isfinite(lv_l)&np.isfinite(lv_s)
    ok_l=base&~(r60>LATE);ok_s=base&~(-r60>LATE)
    return P,fc,lv_l,lv_s,atr,c,g('opposite_low_10'),g('opposite_high_10'),ok_l,ok_s

def stats(T,days):
    if not len(T):return {}
    R=T[:,3];d=np.minimum(T[:,1]//1440,days-1).astype(int);curve=np.bincount(d,R,days);eq=np.cumsum(curve)
    def seg(a,b):
        x=eq[a:b]-(eq[a-1] if a>0 else 0.);dd=float((np.maximum.accumulate(np.r_[0,x])-np.r_[0,x]).max());tot=float(x[-1]);yrs=(b-a)/365.25
        return dict(R=tot,R_per_year=tot/yrs,maxDD_R=dd,calmar=tot/yrs/dd if dd>0 else np.inf)
    sp=LG.SPLIT_MIN//1440;tr=T[:,0]<LG.SPLIT_MIN;g=R[R>0].sum();b=-R[R<0].sum()
    return dict(n=len(R),win=float((R>0).mean()*100),meanR=float(R.mean()),pf=float(g/b),stop_pct=float(np.median(T[:,4])*100),
                full=seg(0,days),train=seg(0,sp),valid=seg(sp,days),n_train=int(tr.sum()))

def main():
    res={}
    for uni,coins in (('MAIN5',LB.MAIN5),('OTHER30',LB.OTHER30)):
        for mode,name in ((0,'CLOSE'),(1,'STOP'),(4,'RETEST3'),(7,'RETEST6')):
            T=[];days=0
            for s in coins:
                A=coin_arrays(s);days=len(A[0])//1440;T.append(engine(*A,mode,FEE,SLIP))
            st=stats(np.concatenate(T),days);res[f'{uni}|{name}']=st
            print(f"{uni:7s} {name:5s} n {st['n']} WR {st['win']:.1f}% meanR {st['meanR']:.3f} PF {st['pf']:.2f} stop {st['stop_pct']:.2f}% | R/yr tr {st['train']['R_per_year']:.1f} va {st['valid']['R_per_year']:.1f} | Calmar(R) tr {st['train']['calmar']:.2f} va {st['valid']['calmar']:.2f} | DD(R) {st['full']['maxDD_R']:.1f}",flush=True)
    a,b=res['MAIN5|CLOSE'],res['MAIN5|STOP']
    res['passed']=bool(b['train']['R']>a['train']['R'] and b['valid']['R']>a['valid']['R'] and b['train']['calmar']>a['train']['calmar'] and b['valid']['calmar']>a['valid']['calmar']
                       and res['OTHER30|STOP']['full']['R']>res['OTHER30|CLOSE']['full']['R'])
    print('STOP entry passes:',res['passed']);LB.OUT.mkdir(parents=True,exist_ok=True);(LB.OUT/'early_entry.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
