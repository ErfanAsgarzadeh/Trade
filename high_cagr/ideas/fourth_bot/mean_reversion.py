"""Mean-reversion candidate for a fourth bot (PREDECLARED.md section 1). Same data, groups, costs and storage as Chabok."""
from pathlib import Path
import sys,json,itertools,time
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pa_bot as PBOT
from high_cagr.ideas.chabok import research as RS
from high_cagr.ideas.winrate import prepare_ttt as PT, ledger as LG
OUT=ROOT/'high_cagr/output/ideas/fourth_bot';TFS={'15m':15,'1h':60,'4h':240,'1d':1440}
SIG=list(itertools.product(('BB20/2.0','BB20/2.5','RSI2-10','RSI2-5'),('none','trend','range')))
EXIT=list(itertools.product((1.5,2.5,4.),(12,24,48),('sma20','sma5')))

def adx14(h,l,c):
    up=np.diff(h,prepend=h[0]);dn=-np.diff(l,prepend=l[0]);pdm=np.where((up>dn)&(up>0),up,0.);ndm=np.where((dn>up)&(dn>0),dn,0.)
    pc=np.roll(c,1);pc[0]=c[0];tr=np.maximum(h-l,np.maximum(abs(h-pc),abs(l-pc)));atr=RS.wilder(tr,14)
    with np.errstate(divide='ignore',invalid='ignore'):
        pdi=100*RS.wilder(pdm,14)/atr;ndi=100*RS.wilder(ndm,14)/atr;dx=100*abs(pdi-ndi)/(pdi+ndi)
    return RS.wilder(np.nan_to_num(dx),14)

def features(o,h,l,c,warm):
    atr,_,_,up,dn,_=RS.indicators(o,h,l,c,warm);s=pd.Series(c)
    d=np.diff(c,prepend=c[0]);g=pd.Series(np.clip(d,0,None)).ewm(alpha=.5,adjust=False).mean().to_numpy();ls=pd.Series(np.clip(-d,0,None)).ewm(alpha=.5,adjust=False).mean().to_numpy()
    with np.errstate(divide='ignore',invalid='ignore'):rsi2=np.where(ls>0,100-100/(1+g/ls),100.)
    return dict(atr=atr,up=up,dn=dn,sma20=s.rolling(20).mean().to_numpy(),std20=s.rolling(20).std().to_numpy(),sma5=s.rolling(5).mean().to_numpy(),
                rsi2=rsi2,adx=adx14(h,l,c),warm=warm)

def signals(c,f,entry,filt):
    n=len(c);base=(np.arange(n)>=f['warm'])&(f['atr']/c>=.0015)
    with np.errstate(invalid='ignore'):
        if entry.startswith('BB'):
            k=float(entry.split('/')[1]);lg=c<f['sma20']-k*f['std20'];sh=c>f['sma20']+k*f['std20']
        else:
            q=float(entry.split('-')[1]);lg=f['rsi2']<q;sh=f['rsi2']>100-q
        if filt=='trend':lg&=f['up'];sh&=f['dn']
        elif filt=='range':r=f['adx']<20;lg&=r;sh&=r
    side=np.zeros(n,np.int8);side[base&lg]=1;side[base&sh&~lg]=-1;return side

@njit(cache=True)
def engine(o,h,l,c,atr,side,target,fb,start,stop_atr,max_bars,fee,slip):
    n=len(c);out=np.zeros((n//2+1,4));k=0;t=start
    while t<n-2:
        s=side[t]
        if s==0:
            t+=1;continue
        e=o[t+1]*(1+s*slip);dist=max(stop_atr*atr[t],.006*e);stop=e-s*dist;x=-1;xr=0.;i=t+1
        while i<n:
            if s==1 and l[i]<=stop:
                xr=min(o[i],stop);x=i;break
            if s==-1 and h[i]>=stop:
                xr=max(o[i],stop);x=i;break
            if (s==1 and c[i]>=target[i]) or (s==-1 and c[i]<=target[i]) or i-t>=max_bars:
                xr=c[i];x=i;break
            i+=1
        if x<0:
            x=n-1;xr=c[n-1]
        xp=xr*(1-s*slip);net=s*(xp-e)/e-fee*(1+xp/e)-s*(fb[x+1]-fb[t+1])
        out[k,0]=t+1;out[k,1]=x;out[k,2]=net/(dist/e);out[k,3]=(2*fee+2*slip)/(dist/e);k+=1;t=x+1
    return out[:k]

def run_tf(tf,A,B):
    m=TFS[tf];ncfg=len(SIG)*len(EXIT);days=np.zeros((2,2,ncfg,RS.DAYS),np.float32);cnt=np.zeros((2,2,ncfg,2),np.int64)
    gp=np.zeros((2,2,ncfg,2));gl=np.zeros((2,2,ncfg,2));wins=np.zeros((2,ncfg,2),np.int64);gi={s:0 for s in A}|{s:1 for s in B}
    for s in A+B:
        P,fc=PBOT.load_coin(s);o,h,l,c=RS.bars(P,m);f=features(o,h,l,c,250 if m<1440 else 60);fb=fc[np.minimum(np.arange(len(c)+1)*m,len(fc)-1)]
        start=int(np.ceil((PT.listed_min(s)+PT.WARMUP_DAYS*1440)/m));g=gi[s]
        for si,(en,fl) in enumerate(SIG):
            side=signals(c,f,en,fl)
            for ei,(sa,mb,ex) in enumerate(EXIT):
                T=engine(o,h,l,c,f['atr'],side,f[ex].copy(),fb,start,sa,mb,RS.FEE,RS.SLIP)
                if not len(T):continue
                ci=si*len(EXIT)+ei;day=np.minimum((T[:,1]*m)//1440,RS.DAYS-1).astype(np.int64);per=(T[:,0]*m>=LG.SPLIT_MIN).astype(np.int64)
                for cost,R in ((0,T[:,2]),(1,T[:,2]-T[:,3])):
                    days[g,cost,ci]+=np.bincount(day,R,RS.DAYS).astype(np.float32)
                    for p in (0,1):
                        r=R[per==p];cnt[g,cost,ci,p]+=len(r);gp[g,cost,ci,p]+=r[r>0].sum();gl[g,cost,ci,p]+=-r[r<0].sum()
                        if cost==0:wins[g,ci,p]+=int((r>0).sum())
        print(tf,s,'done',flush=True)
    np.savez_compressed(OUT/f'mr_grid_{tf}.npz',days=days,cnt=cnt,gp=gp,gl=gl,wins=wins)

def main():
    OUT.mkdir(parents=True,exist_ok=True);A,B=RS.groups()
    for tf in (sys.argv[1:] or list(TFS)):
        t0=time.time();run_tf(tf,A,B);print('TF',tf,'seconds',round(time.time()-t0),flush=True)
if __name__=='__main__':main()
