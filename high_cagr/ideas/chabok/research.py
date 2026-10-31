"""Chabok optimisation on 49 TTT coins and six timeframes (see PREDECLARED.md). Research only.

Bars are built from the Binance 1m grid (rs.START aligned, so 1d bars are UTC days). The engine fills at the next bar's open,
checks the stop first in every bar (gap through the stop -> the bar's open), arms the profit lock from the bar AFTER the one
that touched +1R, takes the half at +2R intrabar, ratchets the trail and applies the time stop at the bar close.
Per configuration it stores the realised R per UTC exit day for coin groups A and B (and with doubled costs), from which
every metric of the pre-declared gates is computed.
"""
from pathlib import Path
import sys,json,itertools,time
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pa_bot as PBOT
from high_cagr.ideas.winrate import universe_alloc as UA, prepare_ttt as PT, ledger as LG
OUT=ROOT/'high_cagr/output/ideas/chabok';FEE=.0006;SLIP=.0002;DAYS=1826
TFS={'15m':15,'30m':30,'1h':60,'2h':120,'4h':240,'1d':1440};HTF_MULT=4
SIG=list(itertools.product((20,40,80),(True,False),(True,False)))                       # N, rsi band, trend filter
EXIT=list(itertools.product((1.5,2.,3.,4.),(0.,2.5,4.,6.),(0,48,96),(False,True)))      # stop_atr, trail_atr, max_bars, lock

def groups():
    order=[s for s,_ in UA.ranking(len(UA.daily_usd_volume('BTCUSDT')))]   # latest liquidity, PAXG excluded
    return order[0::2],order[1::2]

def ema(x,n):return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()
def wilder(x,n):return pd.Series(x).ewm(alpha=1/n,adjust=False).mean().to_numpy()

def bars(P,m):
    n=len(P)//m;Q=P[:n*m].reshape(n,m,4)
    return Q[:,0,0].copy(),Q[:,:,1].max(1),Q[:,:,2].min(1),Q[:,-1,3].copy()

def indicators(o,h,l,c,warm=250):
    pc=np.roll(c,1);pc[0]=c[0];tr=np.maximum(h-l,np.maximum(abs(h-pc),abs(l-pc)));atr=wilder(tr,14)
    d=np.diff(c,prepend=c[0]);g=wilder(np.clip(d,0,None),14);ls=wilder(np.clip(-d,0,None),14)
    with np.errstate(divide='ignore',invalid='ignore'):rsi=np.where(ls>0,100-100/(1+g/ls),100.)
    e20=ema(c,20);k=HTF_MULT;nh=len(c)//k;hc=c[:nh*k].reshape(nh,k)[:,-1];he50=ema(hc,50);he200=ema(hc,200)
    j=(np.arange(len(c))+1)//k-1;ok=j>=50;jj=np.clip(j,0,nh-1)
    up=ok&(he50[jj]>he200[jj])&(hc[jj]>he50[jj]);dn=ok&(he50[jj]<he200[jj])&(hc[jj]<he50[jj])
    return atr,rsi,e20,up,dn,warm

def signals(o,h,l,c,ind,N,use_rsi,use_trend):
    atr,rsi,e20,up,dn,warm=ind;n=len(c)
    hh=pd.Series(h).rolling(N).max().shift(1).to_numpy();ll=pd.Series(l).rolling(N).min().shift(1).to_numpy()
    e_up=np.r_[False,e20[1:]>e20[:-1]];e_dn=np.r_[False,e20[1:]<e20[:-1]]
    base=(atr/c>=.0015)&(np.arange(n)>=warm)
    lg=base&(c>hh)&(c>e20)&e_up;sh=base&(c<ll)&(c<e20)&e_dn
    if use_rsi:lg&=(rsi>=55)&(rsi<=75);sh&=(rsi>=25)&(rsi<=45)
    if use_trend:lg&=up;sh&=dn
    side=np.zeros(n,np.int8);side[lg]=1;side[sh&~lg]=-1;return side

@njit(cache=True)
def engine(o,h,l,c,atr,side,fb,start,stop_atr,trail_atr,max_bars,lock,fee,slip):
    n=len(c);out=np.zeros((n//2+1,4));k=0;t=start
    while t<n-2:
        s=side[t]
        if s==0:
            t+=1;continue
        if abs(o[t+1]-c[t])>.5*atr[t]:
            t+=1;continue
        e=o[t+1]*(1+s*slip);dist=max(stop_atr*atr[t],.006*e);stop=e-s*dist;best=c[t];armed=False;half=False;rest=1.;acc=0.
        x=-1;xr=0.;i=t+1
        while i<n:
            if s==1 and l[i]<=stop:
                xr=min(o[i],stop);x=i;break
            if s==-1 and h[i]>=stop:
                xr=max(o[i],stop);x=i;break
            if lock and not half:
                tg=e+s*2*dist
                if (s==1 and h[i]>=tg) or (s==-1 and l[i]<=tg):
                    px=max(o[i],tg) if s==1 else min(o[i],tg);xp=px*(1-s*slip)
                    acc+=.5*(s*(xp-e)/e-fee*(1+xp/e)-s*(fb[i+1]-fb[t+1]));rest=.5;half=True
            if lock and armed:
                lk=e+s*.1*dist
                if s*(lk-stop)>0:stop=lk
            if lock and ((s==1 and h[i]>=e+dist) or (s==-1 and l[i]<=e-dist)):armed=True
            best=max(best,c[i]) if s==1 else min(best,c[i])
            if trail_atr>0:
                ns=best-s*trail_atr*atr[i]
                if s*(ns-stop)>0:stop=ns
            if max_bars>0 and i-t>=max_bars:
                xr=c[i];x=i;break
            i+=1
        if x<0:
            x=n-1;xr=c[n-1]
        xp=xr*(1-s*slip);net=acc+rest*(s*(xp-e)/e-fee*(1+xp/e)-s*(fb[x+1]-fb[t+1]))
        out[k,0]=t+1;out[k,1]=x;out[k,2]=net/(dist/e);out[k,3]=(2*fee+2*slip)/(dist/e);k+=1   # R, and R of one extra round trip
        t=x+1
    return out[:k]

def run_tf(tf,A,B,coins):
    m=TFS[tf];ncfg=len(SIG)*len(EXIT);days=np.zeros((2,2,ncfg,DAYS),np.float32);cnt=np.zeros((2,2,ncfg,2),np.int64)   # group, cost, cfg, [train,valid] trades
    gp=np.zeros((2,2,ncfg,2));gl=np.zeros((2,2,ncfg,2));wins=np.zeros((2,ncfg,2),np.int64);gi={s:0 for s in A}|{s:1 for s in B}
    for s in coins:
        P,fc=PBOT.load_coin(s);o,h,l,c=bars(P,m);ind=indicators(o,h,l,c,250 if m<1440 else 60);fb=fc[np.minimum(np.arange(len(c)+1)*m,len(fc)-1)]
        start=int(np.ceil((PT.listed_min(s)+PT.WARMUP_DAYS*1440)/m));g=gi[s]
        for si,(N,ur,ut) in enumerate(SIG):
            side=signals(o,h,l,c,ind,N,ur,ut)
            for ei,(sa,ta,mb,lk) in enumerate(EXIT):
                T=engine(o,h,l,c,ind[0],side,fb,start,sa,ta,mb,lk,FEE,SLIP)
                if not len(T):continue
                ci=si*len(EXIT)+ei;day=np.minimum((T[:,1]*m)//1440,DAYS-1).astype(np.int64);per=(T[:,0]*m>=LG.SPLIT_MIN).astype(np.int64)
                for cost,R in ((0,T[:,2]),(1,T[:,2]-T[:,3])):
                    days[g,cost,ci]+=np.bincount(day,R,DAYS).astype(np.float32)
                    for p in (0,1):
                        r=R[per==p];cnt[g,cost,ci,p]+=len(r);gp[g,cost,ci,p]+=r[r>0].sum();gl[g,cost,ci,p]+=-r[r<0].sum()
                        if cost==0:wins[g,ci,p]+=int((r>0).sum())
        print(tf,s,'done',flush=True)
    np.savez_compressed(OUT/f'grid_{tf}.npz',days=days,cnt=cnt,gp=gp,gl=gl,wins=wins)

def main():
    OUT.mkdir(parents=True,exist_ok=True);A,B=groups();coins=A+B
    (OUT/'groups.json').write_text(json.dumps(dict(A=A,B=B),indent=1))
    for tf in (sys.argv[1:] or list(TFS)):
        if (OUT/f'grid_{tf}.npz').exists():continue
        t0=time.time();run_tf(tf,A,B,coins);print('TF',tf,'seconds',round(time.time()-t0),flush=True)
if __name__=='__main__':main()
