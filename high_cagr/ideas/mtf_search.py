"""Large strategy search on 2h / 3h / 4h for the 5 coins. Written and committed BEFORE any result.

Engine, costs, sizing and exits are those of ltf_search.py (taker 0.06%/side + 2 bps + funding, risk 0.5%/trade,
notional <= 0.4 x equity, one position per symbol, entry at next bar open, conservative stop-before-target).
ENTRIES (19): DON10 DON20 DON55 | EMA9_21 EMA20_50 EMA50_200 | ST10_3 ST10_2 | MACD200 | KELT | SQZ | RSI2T RSI2 BBREV |
  PULL | MOM20 / MOM50 (close above/below close N bars ago AND above/below EMA50, fresh flip) | DMI (DI+ crosses DI-
  with ADX >= 20; exit on reverse cross) | KUMO (close crosses out of this timeframe's Ichimoku Kumo 9/26/52/26;
  exit back inside) | RSI50 (RSI14 crosses 50; exit reverse cross)
EXITS (6): SIG, TRAIL (2 ATR stop + 3 ATR chandelier), TRAILW (2 ATR stop + 4.5 ATR chandelier), TP2, TP1, TIME(12 bars)
FILTERS (8): none | DAILY: last completed daily close beyond daily EMA50 on the trade side | ADX>=20 | ADX<20 |
  ATRREG: ATR >= median ATR of the prior 60 bars (same timeframe) | NOWKND | VOL: signal-bar volume >= 1.5 x mean
  of the prior 20 bars | BTC: BTC close beyond its EMA200 (same timeframe) on the trade side
TIMEFRAMES 2h, 3h, 4h  ->  19 x 6 x 8 x 3 = 2,736 configs.
SELECTION on TRAIN (< 2025) only, configs with >= 100 train trades.
  Q1 "better than the bot alone": top 10 by train Calmar; BETTER if train Calmar >= bot train Calmar AND validation
     Calmar >= bot validation Calmar (bot = 2A+5A daily curve).
  Q2 "useful next to the bot": blend = 50% bot + 50% config (daily returns). Top 10 by TRAIN blend Calmar;
     USEFUL if blend Calmar >= bot Calmar in train AND in validation AND blend full max DD <= bot full max DD.
  Reported: Spearman train/validation, share positive in both periods by family, maker-cost sensitivity.
"""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import orb_intraday as oi
from high_cagr.ideas import ltf_search as L
S=oi.S;OUT=oi.OUT
EXITS={'SIG':1,'TRAIL':2,'TRAILW':6,'TP2':3,'TP1':4,'TIME':5}
FILTS=['none','DAILY','ADX>=20','ADX<20','ATRREG','NOWKND','VOL','BTC']
from numba import njit

@njit(cache=True)
def engine(o,h,l,c,atr,le,se,lx,sx,al,as_,mode,fee,slip,fcum,warm):
    """ltf_search.engine plus mode 6 = wide chandelier (4.5 ATR)."""
    n=len(c);out=np.zeros((n,6));k=0;t=warm
    while t<n-2:
        side=1 if (le[t] and al[t]) else (-1 if (se[t] and as_[t]) else 0)
        if side==0 or not atr[t]>0:t+=1;continue
        e=t+1;raw=o[e];entry=raw*(1+side*slip);a=atr[t]
        sm=2.5 if mode==1 else (1.5 if mode in (3,4) else 2.)
        stop=entry-side*sm*a;dist=side*(entry-stop)
        if dist/entry<.004:t+=1;continue
        tp=entry+side*(2. if mode==3 else 1.)*dist if mode in (3,4) else 0.
        qty=min(.005*1e4/(dist+entry*(2*fee+2*slip)),.4*1e4/entry);best=c[t];xraw=0.;x=e;j=e;tw=4.5 if mode==6 else 3.
        while j<n:
            if side==1:
                if l[j]<=stop:xraw=min(o[j],stop);x=j;break
                if mode in (3,4) and h[j]>=tp:xraw=max(o[j],tp);x=j;break
            else:
                if h[j]>=stop:xraw=max(o[j],stop);x=j;break
                if mode in (3,4) and l[j]<=tp:xraw=min(o[j],tp);x=j;break
            if mode==1 and ((side==1 and lx[j]) or (side==-1 and sx[j])) and j+1<n:xraw=o[j+1];x=j+1;break
            if mode==5 and j-e>=11:xraw=c[j];x=j;break
            if mode==2 or mode==6:
                best=max(best,c[j]) if side==1 else min(best,c[j]);ns=best-side*tw*atr[j]
                if side*(ns-stop)>0:stop=ns
            j+=1
        if xraw==0.:xraw=c[n-1];x=n-1
        xp=xraw*(1-side*slip);fund=-side*raw*qty*(fcum[x]-fcum[e])
        net=side*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=e;out[k,1]=x;out[k,2]=side;out[k,3]=net/1e4;out[k,4]=side*(xraw-raw)/dist;out[k,5]=0.;k+=1
        t=x if x>t else t+1
    return out[:k]

def extra_signals(o,h,l,c,atr,adx,sig):
    E50=L.ema(c,50)
    for N in (20,50):
        up=(c>np.roll(c,N))&(c>E50);dn=(c<np.roll(c,N))&(c<E50)
        sig[f'MOM{N}']=(up&~np.roll(up,1),dn&~np.roll(dn,1),~up,~dn)
    tr=atr;upm=h-np.roll(h,1);dwm=np.roll(l,1)-l;pdm=np.where((upm>dwm)&(upm>0),upm,0.);ndm=np.where((dwm>upm)&(dwm>0),dwm,0.)
    pdi=L.wilder(pdm,14)/tr;ndi=L.wilder(ndm,14)/tr
    sig['DMI']=(L.cross_up(pdi,ndi)&(adx>=20),L.cross_dn(pdi,ndi)&(adx>=20),L.cross_dn(pdi,ndi),L.cross_up(pdi,ndi))
    mid=lambda w:(pd.Series(h).rolling(w).max()+pd.Series(l).rolling(w).min()).to_numpy()/2
    ten,kij,sb=mid(9),mid(26),mid(52);sa=(ten+kij)/2;top=np.maximum(np.roll(sa,26),np.roll(sb,26));bot=np.minimum(np.roll(sa,26),np.roll(sb,26))
    above=c>top;below=c<bot
    sig['KUMO']=(above&~np.roll(above,1),below&~np.roll(below,1),~above,~below)
    r14=L.rsi(c,14);f50=np.full_like(r14,50)
    sig['RSI50']=(L.cross_up(r14,f50),L.cross_dn(r14,f50),L.cross_dn(r14,f50),L.cross_up(r14,f50))
    hh=pd.Series(h).rolling(10).max().shift(1).to_numpy();ll=pd.Series(l).rolling(10).min().shift(1).to_numpy()
    h5=pd.Series(h).rolling(5).max().shift(1).to_numpy();l5=pd.Series(l).rolling(5).min().shift(1).to_numpy()
    sig['DON10']=(c>hh,c<ll,c<l5,c>h5)
    for k in ('MOM20','MOM50','DMI','KUMO','RSI50','DON10'):sig[k]=tuple(np.nan_to_num(x.astype(float))>0 for x in sig[k])
    return sig

def blend_stats(r,split):
    return {k:L.calmar(r[a:b]) for k,(a,b) in (('full',(0,len(r))),('train',(0,split)),('oos',(split,len(r))))}

def main():
    prices={s:np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in S};flow={s:np.load(ROOT/'high_cagr/prepared_flow1m'/f'{s}.npy',mmap_mode='r') for s in S}
    days=len(prices[S[0]])//1440;split=(pd.Timestamp('2025-01-01')-pd.Timestamp('2021-10-05')).days
    fcum={}
    for s in S:
        f=np.load(ROOT/'high_cagr/prepared'/s/'funding.npy').copy();m=np.arange(len(f));px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f)
        f[px]=1e-4;f[~np.isfinite(f)]=0;fcum[s]=np.concatenate([[0.],np.cumsum(f)])
    f4={s:pd.DataFrame(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['data'],columns=json.loads(str(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['columns']))) for s in S}
    bot=oi.bot_daily(days);B=blend_stats(bot,split);print('bot',{k:[round(x,2) for x in v] for k,v in B.items()},flush=True)
    FAMS=L.FAMS+['MOM20','MOM50','DMI','KUMO','RSI50','DON10'];rows=[];store={}
    for tf,bm in (('2h',120),('3h',180),('4h',240)):
        per={};btc=None
        for s in ['BTCUSDT']+[x for x in S if x!='BTCUSDT']:
            o,h,l,c=L.bars(prices[s],bm);sig,atr,adx=L.signals(o,h,l,c);sig=extra_signals(o,h,l,c,atr,adx,sig);n=len(c)
            close_ms=rs.START+(np.arange(n)+1)*bm*60000
            # daily trend from completed UTC days of the 4h frame
            f=f4[s];g=f.assign(day=(f.timestamp//86400000).astype(np.int64)).groupby('day').agg(c=('close','last'),k=('close','size'));g=g[g.k==6]
            e50=L.ema(g.c.to_numpy(),50);pos=np.searchsorted((g.index.to_numpy()+1)*86400000,close_ms,side='right')-1;pos=np.clip(pos,0,None)
            dup=g.c.to_numpy()[pos]>e50[pos]
            ar=atr/pd.Series(atr).rolling(60).median().shift(1).to_numpy()
            v=np.asarray(flow[s][:n*bm,0]).reshape(n,bm).sum(1);vr=v/pd.Series(v).rolling(20).mean().shift(1).to_numpy()
            if s=='BTCUSDT':btc=c>L.ema(c,200)
            wk=pd.to_datetime(close_ms,unit='ms').weekday<5
            filt={'none':(np.ones(n,bool),)*2,'DAILY':(dup,~dup),'ADX>=20':(adx>=20,)*2,'ADX<20':(adx<20,)*2,'ATRREG':(ar>=1,)*2,'NOWKND':(wk,)*2,'VOL':(vr>=1.5,)*2,'BTC':(btc,~btc)}
            per[s]=(o,h,l,c,atr,sig,filt,fcum[s][np.minimum(np.arange(n)*bm,len(fcum[s])-1)])
        for fam,ex,fl in itertools.product(FAMS,EXITS,FILTS):
            res={}
            for costs,fee,slip in (('taker',.0006,.0002),('maker',.0002,0.)):
                T=np.concatenate([engine(*per[s][:4],per[s][4],*per[s][5][fam],*per[s][6][fl],EXITS[ex],fee,slip,per[s][7],300) for s in S])
                ds=L.daily_series(T,bm,days);trn=(T[:,1]*bm//1440)<split
                res[costs]=dict(n_train=int(trn.sum()),n_oos=int((~trn).sum()),st=blend_stats(ds,split),priceR=float(T[trn,4].mean()) if trn.any() else 0.)
                if costs=='taker':store[(tf,fam,ex,fl)]=ds
            t=res['taker'];bl=blend_stats(.5*bot+.5*store[(tf,fam,ex,fl)],split)
            rows.append(dict(tf=tf,fam=fam,exit=ex,filter=fl,n_train=t['n_train'],n_oos=t['n_oos'],priceR_train=t['priceR'],
                train_calmar=t['st']['train'][0],train_cagr=t['st']['train'][1],oos_calmar=t['st']['oos'][0],oos_cagr=t['st']['oos'][1],oos_dd=t['st']['oos'][2],full_dd=t['st']['full'][2],
                corr=float(np.corrcoef(bot,store[(tf,fam,ex,fl)])[0,1]),blend_train=bl['train'][0],blend_oos=bl['oos'][0],blend_full=bl['full'][0],blend_dd=bl['full'][2],
                maker_oos_cagr=res['maker']['st']['oos'][1],maker_train_cagr=res['maker']['st']['train'][1]))
        print('done',tf,len(rows),flush=True)
    R=pd.DataFrame(rows);R.to_csv(OUT/'mtf_search.csv',index=False);el=R[R.n_train>=100]
    rho=float(el.train_calmar.rank().corr(el.oos_calmar.rank()))
    print(f"\nconfigs {len(R)} eligible {len(el)} | positive train {(el.train_cagr>0).sum()} oos {(el.oos_cagr>0).sum()} both {((el.train_cagr>0)&(el.oos_cagr>0)).sum()} | Spearman {rho:.2f}")
    print(f"maker costs: positive both {((el.maker_train_cagr>0)&(el.maker_oos_cagr>0)).sum()}")
    print(f"\nQ1 top 10 by TRAIN Calmar (bot: train {B['train'][0]:.2f}, validation {B['oos'][0]:.2f}):");q1=[]
    for _,x in el.sort_values('train_calmar',ascending=False).head(10).iterrows():
        ok=x.train_calmar>=B['train'][0] and x.oos_calmar>=B['oos'][0];q1.append(dict(x,better=bool(ok)))
        print(f"  {x.tf} {x.fam:9s} {x.exit:6s} {x['filter']:7s} trades {x.n_train}/{x.n_oos} | train Calmar {x.train_calmar:.2f} CAGR {x.train_cagr:.1f}% | valid Calmar {x.oos_calmar:.2f} CAGR {x.oos_cagr:.1f}% DD {x.oos_dd:.0f}% | corr {x.corr:.2f} | BETTER={ok}")
    print(f"\nQ2 top 10 by TRAIN blend Calmar (50/50 with bot; bot train {B['train'][0]:.2f} valid {B['oos'][0]:.2f} DD {B['full'][2]:.1f}):");q2=[]
    for _,x in el.sort_values('blend_train',ascending=False).head(10).iterrows():
        ok=x.blend_train>=B['train'][0] and x.blend_oos>=B['oos'][0] and x.blend_dd<=B['full'][2];q2.append(dict(x,useful=bool(ok)))
        print(f"  {x.tf} {x.fam:9s} {x.exit:6s} {x['filter']:7s} | alone train/valid Calmar {x.train_calmar:.2f}/{x.oos_calmar:.2f} | corr {x.corr:.2f} | BLEND train {x.blend_train:.2f} valid {x.blend_oos:.2f} full {x.blend_full:.2f} DD {x.blend_dd:.1f} | USEFUL={ok}")
    fam=el.assign(both=(el.train_cagr>0)&(el.oos_cagr>0)).groupby('fam').both.mean().sort_values(ascending=False)*100
    print('\nshare of configs positive in BOTH periods by entry family (%):');print(fam.round(0).to_string())
    (OUT/'mtf_search.json').write_text(json.dumps(dict(notes=__doc__,bot={k:list(v) for k,v in B.items()},spearman=rho,q1=q1,q2=q2,family_both=fam.to_dict()),indent=1,default=float))
if __name__=='__main__':main()
