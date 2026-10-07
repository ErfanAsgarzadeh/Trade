"""Broad search for a 30m / 1h strategy on the 5 coins. Written and committed BEFORE any result.

FAMILIES (signal on a closed bar, entry at the next bar's open):
  DON20/DON55   Donchian N breakout (close beyond prior N-bar extreme); family exit: opposite N/2 channel
  EMA9_21/EMA20_50/EMA50_200  EMA cross; family exit: reverse cross
  ST10_3/ST10_2 Supertrend(10, k) flip; family exit: flip back
  MACD200       MACD(12,26,9) cross with close beyond EMA200; family exit: reverse MACD cross
  KELT          close beyond Keltner(EMA20 +/- 2 ATR); family exit: close back through EMA20
  SQZ           Bollinger(20,2) width in lowest 20% of prior 120 bars, then close outside band; exit: close through mid
  RSI2T         Connors RSI(2) < 10 (> 90) with close beyond EMA200; family exit: close through EMA5
  RSI2          RSI(2) < 10 (> 90), no trend filter; family exit: close through EMA5
  BBREV         close outside Bollinger(20,2), fade it; family exit: close through mid
  PULL          EMA50 vs EMA200 trend, RSI(14) re-crosses 40 (60 for shorts); exit: RSI14 > 70 (< 30) or close through EMA50
EXITS: SIG family exit + 2.5 ATR stop | TRAIL 2 ATR stop + 3 ATR chandelier on closes | TP2 R=1.5 ATR, target 2R |
       TP1 target 1R | TIME close after 12 bars, 2 ATR stop. Same-bar stop+target -> stop (conservative).
FILTERS: none | HTF: last closed 4h close beyond 4h EMA50 on the trade side | ADX(14) >= 20 | ADX < 20 |
       ATR4h: 4h ATR >= median of prior 60 4h ATRs (the bot's 2A) | NOWKND: no entries Sat/Sun UTC
TIMEFRAMES 30m, 1h. One position per symbol, 5 symbols, risk 0.5% of equity per trade (stop distance + cost
  allowance), notional <= 0.4 x equity, skip stops < 0.4% of price. Taker costs 0.06%/side + 2 bps slippage + funding.
  Maker sensitivity (0.02%/side, no slippage) is reported only, never used for selection.
SELECTION on TRAIN (< 2025-01-01) only: configs with >= 150 train trades, ranked by train Calmar (daily, compounded).
VALIDATION 2025-01-01..2026-10-04 judges the TOP 10. A strategy is FOUND only if: validation return > 0, validation
  Calmar >= 0.5, and bot+strategy improves the bot (full Calmar >= bot + 0.05, full DD <= bot DD, validation Calmar
  >= bot's). Daily returns are mark-to-market (fix after the first run, which booked P&L on exit day). Also reported: Spearman rank correlation of train vs validation Calmar across all configs (persistence).
"""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import orb_intraday as oi
from high_cagr.trigger_study import adx as adx4
S=oi.S;OUT=oi.OUT;RISK=.005;CAP=.4;MIN_STOP=.004
FAMS=['DON20','DON55','EMA9_21','EMA20_50','EMA50_200','ST10_3','ST10_2','MACD200','KELT','SQZ','RSI2T','RSI2','BBREV','PULL']
EXITS={'SIG':1,'TRAIL':2,'TP2':3,'TP1':4,'TIME':5};FILTS=['none','HTF','ADX>=20','ADX<20','ATR4h','NOWKND']

def wilder(x,n):return pd.Series(x).ewm(alpha=1/n,adjust=False).mean().to_numpy()
def ema(x,n):return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()
def rsi(c,n):
    d=np.diff(c,prepend=c[0]);g=wilder(np.maximum(d,0),n);l=wilder(np.maximum(-d,0),n);return 100-100/(1+g/np.where(l==0,1e-12,l))
def supertrend(h,l,c,atr,k):
    mid=(h+l)/2;up=mid+k*atr;dn=mid-k*atr;n=len(c);d=np.ones(n);fu=up.copy();fd=dn.copy()
    for i in range(1,n):
        fu[i]=up[i] if (up[i]<fu[i-1] or c[i-1]>fu[i-1]) else fu[i-1];fd[i]=dn[i] if (dn[i]>fd[i-1] or c[i-1]<fd[i-1]) else fd[i-1]
        d[i]=1 if c[i]>fu[i-1] else (-1 if c[i]<fd[i-1] else d[i-1])
    return d
def cross_up(a,b):return (a>b)&(np.roll(a,1)<=np.roll(b,1))
def cross_dn(a,b):return (a<b)&(np.roll(a,1)>=np.roll(b,1))

def bars(p,m):
    n=len(p)//m*m;x=p[:n].reshape(-1,m,4);return x[:,0,0],x[:,:,1].max(1),x[:,:,2].min(1),x[:,-1,3]

def signals(o,h,l,c):
    """Returns dict fam -> (long_entry, short_entry, long_exit, short_exit), plus atr/adx arrays."""
    tr=np.maximum(h-l,np.maximum(np.abs(h-np.roll(c,1)),np.abs(l-np.roll(c,1))));atr=wilder(tr,14)
    up=h-np.roll(h,1);dw=np.roll(l,1)-l;pdm=np.where((up>dw)&(up>0),up,0.);ndm=np.where((dw>up)&(dw>0),dw,0.)
    pdi=100*wilder(pdm,14)/atr;ndi=100*wilder(ndm,14)/atr;adx=wilder(100*np.abs(pdi-ndi)/np.maximum(pdi+ndi,1e-12),14)
    E={n:ema(c,n) for n in (5,9,20,21,26,12,50,200)};sig={}
    for N in (20,55):
        hh=pd.Series(h).rolling(N).max().shift(1).to_numpy();ll=pd.Series(l).rolling(N).min().shift(1).to_numpy()
        h2=pd.Series(h).rolling(N//2).max().shift(1).to_numpy();l2=pd.Series(l).rolling(N//2).min().shift(1).to_numpy()
        sig[f'DON{N}']=(c>hh,c<ll,c<l2,c>h2)
    for a,b in ((9,21),(20,50),(50,200)):sig[f'EMA{a}_{b}']=(cross_up(E[a],E[b]),cross_dn(E[a],E[b]),E[a]<E[b],E[a]>E[b])
    for k in (3,2):
        d=supertrend(h,l,c,atr,k);sig[f'ST10_{k}']=((d==1)&(np.roll(d,1)==-1),(d==-1)&(np.roll(d,1)==1),d==-1,d==1)
    macd=E[12]-E[26];ms=ema(macd,9);sig['MACD200']=(cross_up(macd,ms)&(c>E[200]),cross_dn(macd,ms)&(c<E[200]),cross_dn(macd,ms),cross_up(macd,ms))
    sig['KELT']=(c>E[20]+2*atr,c<E[20]-2*atr,c<E[20],c>E[20])
    mid=pd.Series(c).rolling(20).mean().to_numpy();sd=pd.Series(c).rolling(20).std().to_numpy();bw=4*sd/mid
    low=pd.Series(bw).rolling(120).quantile(.2).shift(1).to_numpy();sq=np.roll(bw,1)<=low
    sig['SQZ']=(sq&(c>mid+2*sd),sq&(c<mid-2*sd),c<mid,c>mid)
    r2=rsi(c,2);r14=rsi(c,14)
    sig['RSI2T']=((r2<10)&(c>E[200]),(r2>90)&(c<E[200]),c>E[5],c<E[5])
    sig['RSI2']=(r2<10,r2>90,c>E[5],c<E[5])
    sig['BBREV']=(c<mid-2*sd,c>mid+2*sd,c>=mid,c<=mid)
    sig['PULL']=((E[50]>E[200])&cross_up(r14,np.full_like(r14,40)),(E[50]<E[200])&cross_dn(r14,np.full_like(r14,60)),(r14>70)|(c<E[50]),(r14<30)|(c>E[50]))
    for k in sig:sig[k]=tuple(np.nan_to_num(x.astype(float))>0 for x in sig[k])
    return sig,atr,adx

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,lx,sx,al,as_,mode,fee,slip,fcum,bm,warm):
    n=len(c);out=np.zeros((n,6));k=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        sm=2.5 if mode==1 else (1.5 if mode in (3,4) else 2.)
        stop=entry-side*sm*a;dist=side*(entry-stop)
        if dist/entry<MIN_STOP_:t+=1;continue
        tp=entry+side*(2. if mode==3 else 1.)*dist if mode in (3,4) else 0.
        qty=min(RISK_*1e4/(dist+entry*(2*fee+2*slip)),CAP_*1e4/entry);best=c[t];xraw=0.;x=e
        j=e
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
                if mode in (3,4) and h[j]>=tp:xraw=max(o[j],tp);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
                if mode in (3,4) and l[j]<=tp:xraw=min(o[j],tp);x=j;break
            if mode==1 and ((side==1 and lx[j]) or (side==-1 and sx[j])) and j+1<n:xraw=o[j+1];x=j+1;break
            if mode==5 and j-e>=11:xraw=c[j];x=j;break
            if mode==2:
                best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*3*atr[j]
                if side*(ns-stop)>0:stop=ns
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=(dist*qty)/1e4;k+=1
        t=x if x>t else t+1
    return out[:k]
RISK_,CAP_,MIN_STOP_=RISK,CAP,MIN_STOP

def daily_series(trades,bm,days):
    r=np.zeros(days);d=(trades[:,1]*bm//1440).astype(int);np.add.at(r,np.clip(d,0,days-1),trades[:,3]);return r

def calmar(r):
    eq=np.cumprod(1+r)
    if eq[-1]<=0 or len(r)==0:return -9.,-100.,100.
    yrs=len(r)/365.25;g=eq[-1]**(1/yrs)-1;dd=(1-eq/np.maximum.accumulate(eq)).max();return (g/dd if dd>0 else 0.),g*100,dd*100

def main():
    prices={s:np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in S};days=len(prices[S[0]])//1440;split=(pd.Timestamp('2025-01-01')-pd.Timestamp('2021-10-05')).days
    fcum={}
    for s in S:
        f=np.load(ROOT/'high_cagr/prepared'/s/'funding.npy').copy();m=np.arange(len(f));proxy=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f)
        f[proxy]=1e-4;f[~np.isfinite(f)]=0;fcum[s]=np.concatenate([[0.],np.cumsum(f)])
    f4={s:pd.DataFrame(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['data'],columns=json.loads(str(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['columns']))) for s in S}
    bot=oi.bot_daily(days);B={k:calmar(bot[a:b]) for k,(a,b) in (('full',(0,days)),('train',(0,split)),('oos',(split,days)))}
    rows=[];store={}
    for tf,bm in (('30m',30),('1h',60)):
        per={}
        for s in S:
            o,h,l,c=bars(prices[s],bm);sig,atr,adx=signals(o,h,l,c);n=len(c);close_ms=rs.START+(np.arange(n)+1)*bm*60000
            f=f4[s];r=np.searchsorted(f.timestamp.to_numpy(np.int64)+14400000,close_ms,side='right')-1;e50=ema(f.close.to_numpy(),50)
            htf_up=f.close.to_numpy()[r]>e50[r];a4=f.atr.to_numpy();a4r=(a4/pd.Series(a4).rolling(60).median().shift(1).to_numpy())[r]
            wk=pd.to_datetime(close_ms,unit='ms').weekday<5;fb=fcum[s][np.minimum(np.arange(n)*bm,len(fcum[s])-1)]
            filt={'none':(np.ones(n,bool),)*2,'HTF':(htf_up,~htf_up),'ADX>=20':(adx>=20,)*2,'ADX<20':(adx<20,)*2,'ATR4h':(a4r>=1,)*2,'NOWKND':(wk,)*2}
            per[s]=(o,h,l,c,atr,sig,filt,fb)
        for fam,ex,fl in itertools.product(FAMS,EXITS,FILTS):
            res={}
            for costs,fee,slip in (('taker',.0006,.0002),('maker',.0002,0.)):
                tr=[];ds=np.zeros(days)
                from high_cagr.ideas import mtf_search as M   # same engine + mark-to-market daily returns (fix)
                for s in S:
                    o,h,l,c,atr,sig,filt,fb=per[s];le,se,lx,sx=sig[fam];al,as_=filt[fl]
                    T=M.engine(o,h,l,c,atr,le,se,lx,sx,al,as_,EXITS[ex],fee,slip,fb,300);ds+=M.m2m(T,c,bm,days);tr.append(T)
                T=np.concatenate(tr);trn=(T[:,1]*bm//1440)<split
                res[costs]=dict(n_train=int(trn.sum()),n_oos=int((~trn).sum()),train=calmar(ds[:split]),oos=calmar(ds[split:]),full=calmar(ds),
                    priceR_train=float(T[trn,4].mean()) if trn.any() else 0.,priceR_oos=float(T[~trn,4].mean()) if (~trn).any() else 0.,win=float((T[:,3]>0).mean()*100) if len(T) else 0.)
                if costs=='taker':store[(tf,fam,ex,fl)]=ds
            rows.append(dict(tf=tf,fam=fam,exit=ex,filter=fl,**{k:v for k,v in res['taker'].items()},maker=res['maker']))
        print('done',tf,len(rows),flush=True)
    R=pd.DataFrame(rows);R['train_calmar']=R.train.map(lambda x:x[0]);R['oos_calmar']=R.oos.map(lambda x:x[0]);R['train_ret_cagr']=R.train.map(lambda x:x[1]);R['oos_cagr']=R.oos.map(lambda x:x[1])
    R['maker_train_calmar']=R.maker.map(lambda x:x['train'][0]);R['maker_oos_cagr']=R.maker.map(lambda x:x['oos'][1])
    el=R[R.n_train>=150].copy();rho=float(el.train_calmar.rank().corr(el.oos_calmar.rank()))
    top=el.sort_values('train_calmar',ascending=False).head(10)
    print(f"\nconfigs {len(R)}, eligible {len(el)}; train-positive (taker) {(el.train_ret_cagr>0).sum()}, oos-positive {(el.oos_cagr>0).sum()}, both {((el.train_ret_cagr>0)&(el.oos_cagr>0)).sum()}")
    print(f"maker costs: train-positive {(el.maker_train_calmar>0).sum()}; Spearman train-vs-oos Calmar (taker) {rho:.2f}")
    print(f"pre-cost price edge: mean train priceR across configs {el.priceR_train.mean():+.3f}, best {el.priceR_train.max():+.3f}")
    print('\nTOP 10 by TRAIN Calmar (taker):')
    found=[]
    for _,x in top.iterrows():
        ds=store[(x.tf,x.fam,x.exit,x['filter'])];comb={k:calmar((bot+ds)[a:b]) for k,(a,b) in (('full',(0,days)),('train',(0,split)),('oos',(split,days)))}
        ok=x.oos_cagr>0 and x.oos_calmar>=.5 and comb['full'][0]>=B['full'][0]+.05 and comb['full'][2]<=B['full'][2] and comb['oos'][0]>=B['oos'][0]
        found.append(dict(cfg=f"{x.tf} {x.fam} {x.exit} {x['filter']}",train=x.train,oos=x.oos,n_train=x.n_train,n_oos=x.n_oos,priceR_train=x.priceR_train,priceR_oos=x.priceR_oos,combined=comb,found=bool(ok)))
        print(f"  {x.tf:3s} {x.fam:9s} {x.exit:5s} {x['filter']:7s} | trades {x.n_train}/{x.n_oos} | TRAIN Calmar {x.train_calmar:5.2f} CAGR {x.train_ret_cagr:6.1f}% | VALID Calmar {x.oos_calmar:5.2f} CAGR {x.oos_cagr:6.1f}% DD {x.oos[2]:4.0f}% | priceR {x.priceR_train:+.3f}/{x.priceR_oos:+.3f} | bot+it full Calmar {comb['full'][0]:.2f} (bot {B['full'][0]:.2f}) FOUND={ok}",flush=True)
    both=el[(el.train_ret_cagr>0)&(el.oos_cagr>0)].sort_values('train_calmar',ascending=False)
    print('\n(info) configs positive in BOTH periods, best 8 by train:')
    for _,x in both.head(8).iterrows():print(f"  {x.tf} {x.fam} {x.exit} {x['filter']}: train CAGR {x.train_ret_cagr:.1f}% Calmar {x.train_calmar:.2f} | valid CAGR {x.oos_cagr:.1f}% Calmar {x.oos_calmar:.2f} | trades {x.n_train}/{x.n_oos}")
    R.drop(columns=['maker']).to_csv(OUT/'ltf_search.csv',index=False)
    (OUT/'ltf_search.json').write_text(json.dumps(dict(notes=__doc__,bot={k:list(v) for k,v in B.items()},spearman=rho,top10=found,
        counts=dict(configs=len(R),eligible=len(el),train_pos=int((el.train_ret_cagr>0).sum()),oos_pos=int((el.oos_cagr>0).sum()),both=int(len(both)))),indent=1,default=float))
if __name__=='__main__':main()
