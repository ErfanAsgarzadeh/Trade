"""Cross-universe check: every config from orb_intraday (3), ltf_search (840) and mtf_search (2,880) plus the bot
(2A+5A, unchanged) on 10 OTHER coins: AVAX DOT ATOM FIL DOGE LTC AXS LINK XTZ ALGO (stage-2 liquidity list chosen
in Sep-2021 terms, before any result). Written and committed BEFORE running on these coins. No parameter is refit.

Same engines, costs, sizing, filters and mark-to-market daily returns as the 5-coin runs; 10 symbols, one position
per symbol (strategies), bot keeps 4 slots and 0.75% risk. BTC filter uses BTC from the 5-coin data.
Reported (no pass/fail, comparison only):
  1. bot on the 10 coins vs bot on the 5 coins (full / train / validation Calmar and CAGR)
  2. share of configs profitable on the 10 coins, by family type and timeframe; how many beat the bot on the
     10 coins (full-period Calmar)
  3. transfer: Spearman rank correlation of 5-coin TRAIN Calmar (the selection metric used before) vs 10-coin
     full Calmar; median 10-coin Calmar of the 5-coin top-20 vs all configs
"""
from pathlib import Path
import sys,json,itertools,glob,zipfile
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import orb_intraday as oi, ltf_search as L, mtf_search as M
NEW=['AVAXUSDT','DOTUSDT','ATOMUSDT','FILUSDT','DOGEUSDT','LTCUSDT','AXSUSDT','LINKUSDT','XTZUSDT','ALGOUSDT']
PREP=ROOT/'high_cagr/prepared_stage2';CACHE=ROOT/'high_cagr/cache_stage2';OUT=oi.OUT
SPLIT=(pd.Timestamp('2025-01-01')-pd.Timestamp('2021-10-05')).days

def frame(s,prep=PREP):
    z=np.load(prep/s/'4h_standard.npz');return pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))

def minute_volume(s,n):
    p=PREP/s/'vol1m.npy'
    if p.exists():return np.load(p)
    parts=[]
    for f in sorted(glob.glob(str(CACHE/f'monthly/klines/{s}/1m/*.zip')))+sorted(glob.glob(str(CACHE/f'daily/klines/{s}/1m/*.zip'))):
        with zipfile.ZipFile(f) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=[0,5],names=['t','v'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        parts.append(d)
    d=pd.concat(parts).drop_duplicates('t');i=((d.t-rs.START)//60000).astype(np.int64).to_numpy();m=(i>=0)&(i<n)
    v=np.zeros(n,np.float32);v[i[m]]=d.v.to_numpy(np.float32)[m];np.save(p,v);return v

def daily_from_curve(curve,days):
    c=curve[np.isfinite(curve).all(axis=1)];s=pd.Series(c[:,1],index=pd.to_datetime(c[:,0]-3600000,unit='ms')).resample('D').last().ffill()
    s=s.reindex(pd.date_range('2021-10-05',periods=days,freq='D')).ffill();return (s/s.shift(1).fillna(10000.)-1).to_numpy()

def stats(r):return {k:L.calmar(r[a:b]) for k,(a,b) in (('full',(0,len(r))),('train',(0,SPLIT)),('oos',(SPLIT,len(r))))}

def bot_daily(symbols,frames,prices,funding,days):
    """2A+5A exactly as the 5-coin bench (Donchian10+Kumo 4h, ATR2 stop, Donchian10 trail, pyramid, 4 slots, 0.75%)."""
    case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.0075,max_open_positions=4)
    fk={(s,'4h','standard'):frames[s] for s in symbols};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    for j,s in enumerate(symbols):
        f=frames[s];ix=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
        ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix];low=~(ar>=1.)&(ss[j,:,0]!=0);ss[j,low,0]=0;ss[j,low,3]=-np.inf
    a,t,curve=simulate(prices,funding,np.ascontiguousarray(ss),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.0075,4,step,True,slip=2e-4,floor_on=True,floor_trigger=1.,floor_lock=.1)
    return daily_from_curve(curve,days),int((t[:,18]==0).sum())

def main():
    P={s:np.load(PREP/s/'prices.npy') for s in NEW};FU={s:np.load(PREP/s/'funding.npy') for s in NEW};F4={s:frame(s) for s in NEW}
    n1=len(P[NEW[0]]);days=n1//1440;V={s:minute_volume(s,n1) for s in NEW}
    btcP=np.load(ROOT/'high_cagr/prepared/BTCUSDT/prices.npy')
    fcum={}
    for s in NEW:
        f=FU[s].copy();m=np.arange(len(f));px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fcum[s]=np.concatenate([[0.],np.cumsum(f)])
    # 1. bot
    bot10,roots=bot_daily(NEW,F4,np.stack([P[s] for s in NEW]),np.stack([FU[s] for s in NEW]),days);bot5=oi.bot_daily(days)
    B10,B5=stats(bot10),stats(bot5);res=dict(notes=__doc__,bot10=B10,bot5=B5,bot10_roots=roots)
    print('bot on 5 coins :',{k:[round(x,2) for x in v] for k,v in B5.items()});print('bot on 10 coins:',{k:[round(x,2) for x in v] for k,v in B10.items()},'roots',roots,flush=True)
    rows=[]
    # ORB
    out=None
    for name,v in oi.VARIANTS.items():
        o,_=oi.run(np.stack([P[s] for s in NEW]),np.stack([FU[s] for s in NEW]),v['h'],v['mid'],2e-4,days);st=stats(o[:,0])
        rows.append(dict(src='orb',tf='1m',fam='ORB_'+name,exit='EOD',filter='none',full=st['full'][0],full_cagr=st['full'][1],train=st['train'][0],oos=st['oos'][0]))
    # ltf + mtf
    plan=[('ltf','30m',30,L.FAMS,{k:v for k,v in M.EXITS.items() if k!='TRAILW'},L.FILTS),('ltf','1h',60,L.FAMS,{k:v for k,v in M.EXITS.items() if k!='TRAILW'},L.FILTS),
          ('mtf','2h',120,None,M.EXITS,M.FILTS),('mtf','3h',180,None,M.EXITS,M.FILTS),('mtf','4h',240,None,M.EXITS,M.FILTS)]
    for src,tf,bm,fams,exits,filts in plan:
        per={};bo,bh,bl,bc=L.bars(btcP,bm);btc_up=bc>L.ema(bc,200)
        for s in NEW:
            o,h,l,c=L.bars(P[s],bm);sig,atr,adx=L.signals(o,h,l,c);n=len(c)
            if src=='mtf':sig=M.extra_signals(o,h,l,c,atr,adx,sig)
            close_ms=rs.START+(np.arange(n)+1)*bm*60000;f=F4[s];r=np.searchsorted(f.timestamp.to_numpy(np.int64)+14400000,close_ms,side='right')-1
            wk=pd.to_datetime(close_ms,unit='ms').weekday<5;ones=np.ones(n,bool)
            if src=='ltf':
                e50=L.ema(f.close.to_numpy(),50);up=f.close.to_numpy()[r]>e50[r];a4=f.atr.to_numpy();a4r=(a4/pd.Series(a4).rolling(60).median().shift(1).to_numpy())[r]
                filt={'none':(ones,ones),'HTF':(up,~up),'ADX>=20':(adx>=20,)*2,'ADX<20':(adx<20,)*2,'ATR4h':(a4r>=1,)*2,'NOWKND':(wk,wk)}
            else:
                g=f.assign(day=(f.timestamp//86400000).astype(np.int64)).groupby('day').agg(c=('close','last'),k=('close','size'));g=g[g.k==6]
                e50=L.ema(g.c.to_numpy(),50);pos=np.clip(np.searchsorted((g.index.to_numpy()+1)*86400000,close_ms,side='right')-1,0,None);dup=g.c.to_numpy()[pos]>e50[pos]
                ar=atr/pd.Series(atr).rolling(60).median().shift(1).to_numpy();v=V[s][:n*bm].reshape(n,bm).sum(1);vr=v/pd.Series(v).rolling(20).mean().shift(1).to_numpy()
                bu=btc_up[:n]
                filt={'none':(ones,ones),'DAILY':(dup,~dup),'ADX>=20':(adx>=20,)*2,'ADX<20':(adx<20,)*2,'ATRREG':(ar>=1,)*2,'NOWKND':(wk,wk),'VOL':(vr>=1.5,)*2,'BTC':(bu,~bu)}
            per[s]=(o,h,l,c,atr,sig,filt,fcum[s][np.minimum(np.arange(n)*bm,len(fcum[s])-1)])
        famlist=fams if fams else L.FAMS+['MOM20','MOM50','DMI','KUMO','RSI50','DON10']
        for fam,ex,fl in itertools.product(famlist,exits,filts):
            ds=np.zeros(days)
            for s in NEW:
                o,h,l,c,atr,sig,filt,fb=per[s];T=M.engine(o,h,l,c,atr,*sig[fam],*filt[fl],exits[ex],.0006,.0002,fb,300);ds+=M.m2m(T,c,bm,days)
            st=stats(ds);rows.append(dict(src=src,tf=tf,fam=fam,exit=ex,filter=fl,full=st['full'][0],full_cagr=st['full'][1],full_dd=st['full'][2],train=st['train'][0],oos=st['oos'][0],corr=float(np.corrcoef(bot10,ds)[0,1]) if ds.std()>0 else 0.))
        print('done',tf,len(rows),flush=True)
    R=pd.DataFrame(rows)
    five=pd.concat([pd.read_csv(OUT/'ltf_search.csv').assign(src='ltf'),pd.read_csv(OUT/'mtf_search.csv').assign(src='mtf')])[['src','tf','fam','exit','filter','train_calmar','oos_calmar']]
    R=R.merge(five.rename(columns={'train_calmar':'five_train','oos_calmar':'five_oos'}),on=['src','tf','fam','exit','filter'],how='left')
    R.to_csv(OUT/'xuni.csv',index=False)
    typ=lambda f:'ORB' if f.startswith('ORB') else ('mean reversion' if f in('RSI2T','RSI2','BBREV') else ('pullback' if f=='PULL' else 'trend'))
    R['type']=R.fam.map(typ)
    print(f"\nconfigs {len(R)} | profitable on 10 coins (full) {(R.full_cagr>0).mean()*100:.0f}% | beat the bot on 10 coins (full Calmar {B10['full'][0]:.2f}): {(R.full>B10['full'][0]).sum()}")
    print(R.groupby(['type','tf']).apply(lambda g:pd.Series(dict(n=len(g),profitable=(g.full_cagr>0).mean()*100,median_calmar=g.full.median(),beat_bot=(g.full>B10['full'][0]).sum())),include_groups=False).round(2).to_string())
    m=R.dropna(subset=['five_train']);rho=float(m.five_train.rank().corr(m.full.rank()));top=m.sort_values('five_train',ascending=False).head(20)
    print(f"\ntransfer: Spearman(5-coin train Calmar, 10-coin full Calmar) = {rho:.2f}; 5-coin top-20 median 10-coin Calmar {top.full.median():.2f} vs all {m.full.median():.2f}")
    print('\n5-coin top-20 (by train Calmar) on the 10 coins:');print(top[['tf','fam','exit','filter','five_train','five_oos','full','full_cagr','full_dd','corr']].round(2).to_string(index=False))
    print('\nbest 15 on the 10 coins (full Calmar; hindsight, info only):');print(R.sort_values('full',ascending=False).head(15)[['tf','fam','exit','filter','full','full_cagr','full_dd','train','oos','five_train','corr']].round(2).to_string(index=False))
    res.update(spearman=rho,top20_median=float(top.full.median()),all_median=float(m.full.median()),beat_bot=int((R.full>B10['full'][0]).sum()),configs=len(R))
    (OUT/'xuni.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
