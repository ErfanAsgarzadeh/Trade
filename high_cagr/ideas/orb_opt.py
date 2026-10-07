"""ORB A optimisation: entry-trigger grid + every filter family we tried on the bot, adapted to intraday. 5 symbols.

PROTOCOL (written before any result of this file):
  Stage 1 (triggers, TRAIN only = days before 2025-01-01): OR hours H in {2,4,6}; confirmation bar 15m or 60m close;
    last entry hour (UTC) in {12,16,20}; buffer = close must clear the OR edge by 0 or 0.1 x OR width.
    Exit stays ORB-A: stop = other side of the OR, else close at the end of the UTC day. Costs as orb_intraday
    (0.06% fee/side, 2 bps slippage, funding). Rank by TRAIN Calmar of the daily return series.
  Stage 2 (filters, TRAIN only) on the best trigger: each filter alone at its listed thresholds; then greedy forward
    selection: add the filter that most improves TRAIN Calmar, stop when the gain < 5% or after 4 filters.
    A filter only skips that day's first breakout (no second trade that day).
  Judge (VALIDATION 2025-01-01..2026-10-04, never used for selection): report ORB alone and bot+ORB.
  Null control: 300 random daily-trade subsets with the same keep rate as the final filter set; report the
    percentile of the real filter set's VALIDATION Calmar among them.
  Pass = validation ORB net > 0 AND bot+ORB validation Calmar >= bot validation Calmar AND full-period bot+ORB
    Calmar >= bot + 0.05 AND bot+ORB full max DD <= bot max DD AND null percentile >= 90.
"""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import orb_intraday as oi
from high_cagr.trigger_study import adx
S=oi.S;OUT=oi.OUT;SPLIT_DAY=(pd.Timestamp('2025-01-01')-pd.Timestamp('2021-10-05')).days
FEE,RISK,CAP,MIN_DIST=oi.FEE,oi.RISK,oi.CAP,oi.MIN_DIST

@njit(cache=True)
def candidates(prices,funding,h,bar,cut,buf,slip,days):
    """First breakout per symbol/day. Returns rows: s,d,side,k_entry,bar_start,orh,orl,frac(net/E0),price_R."""
    ns=prices.shape[0];rows=np.zeros((days*ns,9));n=0
    for d in range(days):
        base=d*1440
        for s in range(ns):
            orh=-1e18;orl=1e18
            for m in range(base,base+h*60):
                if prices[s,m,1]>orh:orh=prices[s,m,1]
                if prices[s,m,2]<orl:orl=prices[s,m,2]
            w=orh-orl;side=0;k=base+h*60
            while k+bar<=base+cut*60 and side==0:
                c=prices[s,k+bar-1,3]
                if c>orh+buf*w:side=1
                elif c<orl-buf*w:side=-1
                k+=bar
            if side==0 or k>=base+1440:continue
            entry=prices[s,k,0]*(1+side*slip);stop=orl if side==1 else orh;dist=side*(entry-stop)
            if dist<=0 or dist/entry<MIN_DIST:continue
            e0=10000.;qty=min(RISK*e0/(dist+entry*(2*FEE+2*slip)),CAP*e0/entry);exit_p=0.;exit_m=base+1439
            for m in range(k,base+1440):
                o,hi,lo=prices[s,m,0],prices[s,m,1],prices[s,m,2]
                if side==1 and lo<=stop:exit_p=min(o,stop);exit_m=m;break
                if side==-1 and hi>=stop:exit_p=max(o,stop);exit_m=m;break
            if exit_p==0.:exit_p=prices[s,base+1439,3]
            raw=exit_p;exit_p=exit_p*(1-side*slip);fund=0.
            for m in range(k+1,exit_m+1):
                f=funding[s,m]
                if f==f:fund-=side*prices[s,m,0]*qty*f
                elif m>=(1790812800000-1633392000000)//60000 and m%480==0:fund-=prices[s,m,0]*qty*.0001
            net=side*(exit_p-entry)*qty-(entry+exit_p)*qty*FEE+fund
            rows[n]=np.array([s,d,side,k,k-bar,orh,orl,net/e0,side*(raw-prices[s,k,0])/(dist)]);n+=1
    return rows[:n]

def daily(rows,days,keep=None):
    r=np.zeros(days);sel=rows if keep is None else rows[keep];np.add.at(r,sel[:,1].astype(int),sel[:,7]);return r

def calmar(r):
    eq=np.cumprod(1+r);yrs=len(r)/365.25
    if eq[-1]<=0:return -9.,-100.,100.
    cagr=eq[-1]**(1/yrs)-1;dd=(1-eq/np.maximum.accumulate(eq)).max();return (cagr/dd if dd>0 else 0.),cagr*100,dd*100

def split_stats(r):
    out={}
    for k,(a,b) in (('train',(0,SPLIT_DAY)),('oos',(SPLIT_DAY,len(r))),('full',(0,len(r)))):
        c,g,dd=calmar(r[a:b]);out[k]=dict(calmar=float(c),cagr=float(g),dd=float(dd),ret=float((np.prod(1+r[a:b])-1)*100))
    return out

def features(rows,prices,flow,frames,funding):
    """Per-candidate features, all known at the entry minute (bar_start..k-1 is the closed confirmation bar)."""
    F={};n=len(rows);s_=rows[:,0].astype(int);d_=rows[:,1].astype(int);side=rows[:,2];k=rows[:,3].astype(int);b0=rows[:,4].astype(int)
    ts=rs.START+k*60000
    for name in ('atr_rel','adx','kumo4h','tk4h','btc_out','dema','prevday','orw','pen','clv','vbar','vor','taker','cnt','fund','weekend','early'):F[name]=np.full(n,np.nan)
    btc=frames['BTCUSDT'];bts=btc.timestamp.to_numpy(np.int64)+14400000
    for j,s in enumerate(S):
        f=frames[s];idx=np.where(s_==j)[0]
        if not len(idx):continue
        r=np.searchsorted(f.timestamp.to_numpy(np.int64)+14400000,ts[idx],side='right')-1
        atr=f.atr.to_numpy();F['atr_rel'][idx]=(atr/pd.Series(atr).rolling(60).median().shift(1).to_numpy())[r]
        F['adx'][idx]=adx(f).to_numpy()[r];sd=side[idx];c4=f.close.to_numpy()[r]
        F['kumo4h'][idx]=np.where(sd>0,c4>f.kumo_top.to_numpy()[r],c4<f.kumo_bottom.to_numpy()[r])
        F['tk4h'][idx]=np.where(sd>0,f.tenkan.to_numpy()[r]>f.kijun.to_numpy()[r],f.tenkan.to_numpy()[r]<f.kijun.to_numpy()[r])
        rb=np.searchsorted(bts,ts[idx],side='right')-1;bc=btc.close.to_numpy()[rb]
        F['btc_out'][idx]=(bc>btc.kumo_top.to_numpy()[rb])|(bc<btc.kumo_bottom.to_numpy()[rb])
        # completed UTC days (from 4h bars): day close, EMA20 slope, daily ATR14
        g=f.assign(day=(f.timestamp//86400000).astype(np.int64)).groupby('day').agg(h=('high','max'),l=('low','min'),c=('close','last'),n=('close','size'))
        g=g[g.n==6];ema=g.c.ewm(alpha=2/21,adjust=False).mean();tr=np.maximum(g.h-g.l,np.maximum((g.h-g.c.shift()).abs(),(g.l-g.c.shift()).abs()));datr=tr.rolling(14).mean()
        day_ms=(rs.START//86400000)+d_[idx];pos=np.searchsorted(g.index.to_numpy(),day_ms,side='left')-1   # last completed day < entry day
        ok=pos>=5;p=np.clip(pos,5,None)
        up=(g.c.to_numpy()[p]>ema.to_numpy()[p])&(ema.to_numpy()[p]>ema.to_numpy()[p-5]);dn=(g.c.to_numpy()[p]<ema.to_numpy()[p])&(ema.to_numpy()[p]<ema.to_numpy()[p-5])
        F['dema'][idx]=np.where(ok,np.where(sd>0,up,dn),np.nan)
        F['prevday'][idx]=np.where(pos>=1,np.sign(g.c.to_numpy()[p]-g.c.to_numpy()[p-1])==sd,np.nan)
        w=rows[idx,5]-rows[idx,6];F['orw'][idx]=w/datr.to_numpy()[p]
        pr=prices[j];fl=flow[j]
        for ii,t in enumerate(idx):
            a,e=b0[t],k[t];bar=pr[a:e];hi,lo,cl=bar[:,1].max(),bar[:,2].min(),bar[-1,3];edge=rows[t,5] if side[t]>0 else rows[t,6]
            F['pen'][t]=side[t]*(cl-edge)/w[ii];F['clv'][t]=((cl-lo)/(hi-lo) if side[t]>0 else (hi-cl)/(hi-lo)) if hi>lo else np.nan
            L=e-a;v=fl[a:e,0].sum();prior=fl[max(0,a-1440):a,0];F['vbar'][t]=v/(prior.sum()/1440*L) if prior.sum()>0 else np.nan
            tb=fl[a:e,1].sum();F['taker'][t]=(tb/v if side[t]>0 else 1-tb/v) if v>0 else np.nan
            c=fl[a:e,2].sum();pc=fl[max(0,a-1440):a,2].sum();F['cnt'][t]=c/(pc/1440*L) if pc>0 else np.nan
            fr=funding[j,:e];fr=fr[np.isfinite(fr)][-9:];F['fund'][t]=side[t]*fr.mean() if len(fr)==9 else np.nan
        F['weekend'][idx]=pd.to_datetime(ts[idx],unit='ms').weekday>=5
    return F

def or_volume(rows,flow,h):
    """OR volume / mean OR volume of the previous 20 days (same symbol)."""
    out=np.full(len(rows),np.nan)
    for j in range(5):
        days=flow[j].shape[0]//1440;v=flow[j][:days*1440,0].reshape(days,1440)[:,:h*60].sum(1);m=pd.Series(v).rolling(20).mean().shift(1).to_numpy()
        idx=np.where(rows[:,0]==j)[0];d=rows[idx,1].astype(int);out[idx]=v[d]/m[d]
    return out

FILTERS={  # name -> list of (label, keep-function(F))
 'atr_rel':[('atr_rel>=1',lambda F:F['atr_rel']>=1)],
 'adx':[('adx>=20',lambda F:F['adx']>=20),('adx>=25',lambda F:F['adx']>=25)],
 'kumo4h':[('4h close beyond Kumo on side',lambda F:F['kumo4h']==1)],
 'tk4h':[('4h Tenkan/Kijun on side',lambda F:F['tk4h']==1)],
 'btc_out':[('BTC 4h outside Kumo',lambda F:F['btc_out']==1)],
 'dema':[('daily EMA20 trend on side',lambda F:F['dema']==1)],
 'prevday':[('previous day moved on side',lambda F:F['prevday']==1),('previous day moved against',lambda F:F['prevday']==0)],
 'orw':[('OR width <= 0.5 daily ATR',lambda F:F['orw']<=.5),('OR width <= 0.75 daily ATR',lambda F:F['orw']<=.75),('OR width >= 0.5 daily ATR',lambda F:F['orw']>=.5)],
 'pen':[('penetration >= 0.1 OR',lambda F:F['pen']>=.1),('penetration >= 0.25 OR',lambda F:F['pen']>=.25)],
 'clv':[('bar closes in top 30% (side)',lambda F:F['clv']>=.7)],
 'vbar':[('bar volume >= 1.5x',lambda F:F['vbar']>=1.5),('bar volume >= 2x',lambda F:F['vbar']>=2)],
 'vor':[('OR volume >= 1x 20d',lambda F:F['vor']>=1),('OR volume >= 1.25x 20d',lambda F:F['vor']>=1.25)],
 'taker':[('taker share on side >= 0.55',lambda F:F['taker']>=.55),('taker share on side <= 0.52',lambda F:F['taker']<=.52)],
 'cnt':[('trade count >= 1.5x',lambda F:F['cnt']>=1.5)],
 'fund':[('F4: no short when funding<0',lambda F:~((F['side']<0)&(F['fund']>0))),('F4 sym: also no long when funding>1bp',lambda F:~(((F['side']<0)&(F['fund']>0))|((F['side']>0)&(F['fund']>1e-4))))],
 'weekend':[('skip weekend',lambda F:F['weekend']==0)],
 'early':[('breakout within 2h of OR end',lambda F:F['early']==1)],
}

def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in S]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in S])
    flow=np.stack([np.load(ROOT/'high_cagr/prepared_flow1m'/f'{s}.npy') for s in S]);days=prices.shape[1]//1440
    frames={s:pd.DataFrame(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['data'],columns=json.loads(str(np.load(ROOT/'high_cagr/prepared'/s/'4h_standard.npz')['columns']))) for s in S}
    bot=oi.bot_daily(days);res=dict(notes=__doc__,bot=split_stats(bot))
    # Stage 1
    grid=[];print('stage 1: triggers (ranked on TRAIN Calmar)',flush=True)
    for h,bar,cut,buf in itertools.product((2,4,6),(15,60),(12,16,20),(0.,.1)):
        if h*60+bar>cut*60:continue
        rows=candidates(prices,funding,h,bar,cut,buf,2e-4,days);st=split_stats(daily(rows,days))
        grid.append(dict(h=h,bar=bar,cut=cut,buf=buf,trades=int(len(rows)),train=st['train'],oos=st['oos'],priceR_train=float(rows[rows[:,1]<SPLIT_DAY,8].mean())))
    grid.sort(key=lambda g:g['train']['calmar'],reverse=True);res['stage1']=grid
    for g in grid[:6]:print(f"  H{g['h']} bar{g['bar']} cut{g['cut']} buf{g['buf']}: trades {g['trades']} train Calmar {g['train']['calmar']:.2f} ret {g['train']['ret']:.0f}% priceR {g['priceR_train']:+.3f} | oos ret {g['oos']['ret']:.0f}%",flush=True)
    best=grid[0];rows=candidates(prices,funding,best['h'],best['bar'],best['cut'],best['buf'],2e-4,days)
    F=features(rows,prices,flow,frames,funding);F['side']=rows[:,2];F['vor']=or_volume(rows,flow,best['h']);F['early']=(rows[:,4]-(rows[:,1]*1440+best['h']*60))<120
    tr=rows[:,1]<SPLIT_DAY;base=split_stats(daily(rows,days))
    # Stage 2 singles
    singles=[]
    for fam,opts in FILTERS.items():
        for lab,fn in opts:
            keep=np.asarray(fn(F),bool);st=split_stats(daily(rows,days,keep))
            singles.append(dict(family=fam,label=lab,kept=float(keep[tr].mean()*100),train=st['train'],oos=st['oos'],net_R_train=float(rows[keep&tr,8].mean())))
    singles.sort(key=lambda x:x['train']['calmar'],reverse=True);res['singles']=singles;res['base_trigger']=dict(best,**base)
    print(f"\nbase trigger: train Calmar {base['train']['calmar']:.2f} ret {base['train']['ret']:.0f}% | oos ret {base['oos']['ret']:.0f}%\nstage 2: single filters (ranked on TRAIN)",flush=True)
    for x in singles[:12]:print(f"  {x['label']:42s} kept {x['kept']:4.0f}% | train Calmar {x['train']['calmar']:6.2f} ret {x['train']['ret']:6.0f}% | oos Calmar {x['oos']['calmar']:6.2f} ret {x['oos']['ret']:6.0f}%",flush=True)
    # greedy
    chosen=[];keep=np.ones(len(rows),bool);cur=base['train']['calmar']
    allf=[(fam,lab,fn) for fam,opts in FILTERS.items() for lab,fn in opts]
    while len(chosen)<4:
        cand=[(split_stats(daily(rows,days,keep&np.asarray(fn(F),bool)))['train']['calmar'],fam,lab,fn) for fam,lab,fn in allf if fam not in [c[0] for c in chosen]]
        c,fam,lab,fn=max(cand,key=lambda x:x[0])
        if cur>0 and c<cur*1.05 or cur<=0 and c<=cur:break
        chosen.append((fam,lab));keep&=np.asarray(fn(F),bool);cur=c
    fin=split_stats(daily(rows,days,keep));ro=daily(rows,days,keep);comb=split_stats(bot+ro)
    rng=np.random.default_rng(7);rate=keep.mean();null=[split_stats(daily(rows,days,rng.random(len(rows))<rate))['oos']['calmar'] for _ in range(300)]
    pct=float((np.array(null)<fin['oos']['calmar']).mean()*100)
    B=res['bot'];ck={'oos_orb_positive':fin['oos']['ret']>0,'comb_oos_calmar':comb['oos']['calmar']>=B['oos']['calmar'],'comb_full_calmar':comb['full']['calmar']>=B['full']['calmar']+.05,
        'comb_dd':comb['full']['dd']<=B['full']['dd'],'null_pct_ge90':pct>=90}
    res['final']=dict(filters=chosen,kept=float(rate*100),orb=fin,combined=comb,null_oos_calmar_percentile=pct,null_oos_median=float(np.median(null)),checks=ck,passed=all(ck.values()),
                      curve=[[int(i),float(x)] for i,x in zip(range(0,days,7),np.cumprod(1+ro)[::7]*1e4)],curve_comb=[[int(i),float(x)] for i,x in zip(range(0,days,7),np.cumprod(1+bot+ro)[::7]*1e4)])
    print(f"\ngreedy filters (TRAIN): {chosen} kept {rate*100:.0f}%\nfinal ORB: train Calmar {fin['train']['calmar']:.2f} ret {fin['train']['ret']:.0f}% | VALIDATION Calmar {fin['oos']['calmar']:.2f} ret {fin['oos']['ret']:.0f}% DD {fin['oos']['dd']:.0f}% | null oos median {np.median(null):.2f}, real percentile {pct:.0f}",flush=True)
    print(f"bot alone: full Calmar {B['full']['calmar']:.2f} DD {B['full']['dd']:.1f} | oos Calmar {B['oos']['calmar']:.2f}\nbot+ORB : full Calmar {comb['full']['calmar']:.2f} CAGR {comb['full']['cagr']:.1f} DD {comb['full']['dd']:.1f} | oos Calmar {comb['oos']['calmar']:.2f} | PASS={all(ck.values())} {[k for k,x in ck.items() if not x]}",flush=True)
    (OUT/'orb_opt.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
