"""Intraday momentum / opening-range breakout (ORB) as a second sleeve next to the 4h bot, 5 symbols, 1m data.

PRE-DECLARED before any result (2026-10-07):
  Day = UTC day. Opening range (OR) = high/low of the first H hours. From the end of the OR until 16:00 UTC, on each
  closed 15m bar: close > OR high -> long, close < OR low -> short; entry at the next minute's open (+slippage).
  One trade per symbol per day (first breakout only). Stop: other side of the OR (A, B) or OR midpoint (C).
  Skip if stop distance < 0.5% of entry (fees would dominate). Exit at the stop (or worse on a gap) or at the
  last minute of the UTC day.
    A  H=4 (00-04 UTC), stop = opposite side      B  H=1 (00-01 UTC), stop = opposite side
    C  H=4, stop = OR midpoint
  Sizing: risk 0.5% of start-of-day equity per trade incl. cost allowance, notional capped at 0.4 x equity per
  position (at 5x this uses <= 40% margin for all 5 symbols = the bot's free margin).
  Costs: 0.06% fee per side, 2 bps adverse slippage per fill (5 bps sensitivity), Binance funding prints that fall
  inside the holding period (unknown Oct-2026 prints: adverse 0.01%).
  Combined sleeve = daily return of the 2A+5A bot (its full-period curve) + daily ORB return on the same equity.
  GATES: G1 ORB alone net > 0 in train (<2025) and in oos; G2 combined Calmar >= bot Calmar + 0.05 (full) and >= bot
  in train and in oos; G3 combined max DD (daily) <= bot max DD (daily); G4 ORB full net > 0 at 5 bps.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
S=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT'];OUT=ROOT/'high_cagr/output/ideas'
VARIANTS={'A':dict(h=4,mid=False),'B':dict(h=1,mid=False),'C':dict(h=4,mid=True)}
FEE=.0006;RISK=.005;CAP=.4;MIN_DIST=.005

@njit(cache=True)
def run(prices,funding,h,mid,slip,days):
    ns=prices.shape[0];eq=10000.;out=np.zeros((days,3));trades=np.zeros((days*ns,9));nt=0
    for d in range(days):
        base=d*1440;e0=eq;pnl_day=0.
        for s in range(ns):
            orh=-1e18;orl=1e18
            for m in range(base,base+h*60):
                if prices[s,m,1]>orh:orh=prices[s,m,1]
                if prices[s,m,2]<orl:orl=prices[s,m,2]
            side=0;k=base+h*60
            while k+15<base+16*60+1 and side==0:
                c=prices[s,k+14,3]
                if c>orh:side=1
                elif c<orl:side=-1
                k+=15
            if side==0 or k>=base+1440:continue
            entry=prices[s,k,0]*(1+side*slip)
            stop=(orh+orl)/2 if mid else (orl if side==1 else orh)
            dist=side*(entry-stop)
            if dist<=0 or dist/entry<MIN_DIST:continue
            qty=min(RISK*e0/(dist+entry*(2*FEE+2*slip)),CAP*e0/entry)
            exit_p=0.;exit_m=base+1439
            for m in range(k,base+1440):
                o,hi,lo=prices[s,m,0],prices[s,m,1],prices[s,m,2]
                if side==1 and lo<=stop:exit_p=min(o,stop);exit_m=m;break
                if side==-1 and hi>=stop:exit_p=max(o,stop);exit_m=m;break
            if exit_p==0.:exit_p=prices[s,base+1439,3]
            exit_p=exit_p*(1-side*slip)
            fund=0.
            for m in range(k+1,exit_m+1):
                f=funding[s,m]
                if f==f:fund-=side*prices[s,m,0]*qty*f
                elif m>=(1790812800000-1633392000000)//60000 and m%480==0:fund-=prices[s,m,0]*qty*.0001
            gross=side*(exit_p-entry)*qty;fee=(entry+exit_p)*qty*FEE;net=gross-fee+fund;pnl_day+=net
            trades[nt]=np.array([s,d,side,entry,exit_p,qty,net,dist*qty,1. if exit_m<base+1439 else 0.]);nt+=1
        eq+=pnl_day;out[d,0]=pnl_day/e0;out[d,1]=eq;out[d,2]=pnl_day
    return out,trades[:nt]

def metrics(ret,dates,lo=None,hi=None):
    m=np.ones(len(ret),bool)
    if lo is not None:m&=dates>=lo
    if hi is not None:m&=dates<hi
    r=ret[m];eq=np.cumprod(1+r);yrs=len(r)/365.25;cagr=(eq[-1]**(1/yrs)-1)*100;dd=float((1-eq/np.maximum.accumulate(eq)).max()*100)
    return dict(cagr=float(cagr),dd=dd,calmar=float(cagr/dd) if dd>0 else None,ret=float((eq[-1]-1)*100))

def bot_daily(days):
    c=np.array(json.loads((OUT/'htf_confirm.json').read_text())['baseline_2A5A']['curve'])
    s=pd.Series(c[:,1],index=pd.to_datetime(c[:,0],unit='ms')).resample('D').last().ffill()
    s=s.reindex(pd.date_range('2021-10-05',periods=days,freq='D')).ffill();prev=s.shift(1).fillna(10000.)
    return (s/prev-1).to_numpy()

if __name__=='__main__':
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in S]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in S])
    days=prices.shape[1]//1440;dates=pd.date_range('2021-10-05',periods=days,freq='D');split=pd.Timestamp('2025-01-01')
    rb=bot_daily(days);B={k:metrics(rb,dates,*w) for k,w in (('full',(None,None)),('train',(None,split)),('oos',(split,None)))}
    print('bot (daily) ',{k:{m:round(v[m],2) for m in ('cagr','dd','calmar')} for k,v in B.items()},flush=True);res=dict(notes=__doc__,bot=B,variants={})
    for name,v in VARIANTS.items():
        row={}
        for bps in (2,5):
            out,tr=run(prices,funding,v['h'],v['mid'],bps/1e4,days);ro=out[:,0]
            O={k:metrics(ro,dates,*w) for k,w in (('full',(None,None)),('train',(None,split)),('oos',(split,None)))}
            C={k:metrics(rb+ro,dates,*w) for k,w in (('full',(None,None)),('train',(None,split)),('oos',(split,None)))}
            tdate=dates[tr[:,1].astype(int)];net=tr[:,6]
            row[f'{bps}bps']=dict(orb=O,combined=C,trades=int(len(tr)),win=float((net>0).mean()*100),pf=float(net[net>0].sum()/-net[net<0].sum()),
                net_train=float(net[tdate<split].sum()),net_oos=float(net[tdate>=split].sum()),net=float(net.sum()),fees_share=None,
                corr=float(np.corrcoef(rb,ro)[0,1]),stopped_pct=float(tr[:,8].mean()*100),
                by_symbol={S[i]:float(net[tr[:,0]==i].sum()) for i in range(5)},by_side={'long':float(net[tr[:,2]==1].sum()),'short':float(net[tr[:,2]==-1].sum())},
                curve=[[str(d.date()),float(x)] for d,x in zip(dates[::7],np.cumprod(1+ro)[::7]*10000)],
                curve_comb=[[str(d.date()),float(x)] for d,x in zip(dates[::7],np.cumprod(1+rb+ro)[::7]*10000)])
        r2,r5=row['2bps'],row['5bps']
        ck={'G1_orb_train_oos_positive':r2['net_train']>0 and r2['net_oos']>0,
            'G2_combined_calmar':r2['combined']['full']['calmar']>=B['full']['calmar']+.05 and r2['combined']['train']['calmar']>=B['train']['calmar'] and r2['combined']['oos']['calmar']>=B['oos']['calmar'],
            'G3_combined_dd':r2['combined']['full']['dd']<=B['full']['dd'],'G4_5bps_positive':r5['net']>0}
        row['verdict']=dict(checks=ck,passed=all(ck.values()));res['variants'][name]=dict(variant=v,**row)
        o,c=r2['orb'],r2['combined']
        print(f"{name}: ORB trades {r2['trades']} win {r2['win']:.1f}% PF {r2['pf']:.2f} net ${r2['net']:.0f} (train {r2['net_train']:.0f} / oos {r2['net_oos']:.0f}) CAGR {o['full']['cagr']:.1f} DD {o['full']['dd']:.1f} | @5bps net ${r5['net']:.0f} | corr {r2['corr']:.2f} | COMBINED CAGR {c['full']['cagr']:.1f} DD {c['full']['dd']:.1f} Calmar {c['full']['calmar']:.2f} (train {c['train']['calmar']:.2f} oos {c['oos']['calmar']:.2f}) | PASS={row['verdict']['passed']} {[k for k,x in ck.items() if not x]}",flush=True)
    (OUT/'orb_intraday.json').write_text(json.dumps(res,indent=1,default=float))
