"""Missed-trend audit of the bot default (2A+5A), 5 symbols, full period. HINDSIGHT labelling, diagnosis only.

Trends: zigzag on daily closes, a swing ends when price reverses >= 25% from its extreme; keep swings >= 30% that last
>= 7 days. For every 4h bar inside a trend we record what the bot was doing:
  WITH      a position in the trend direction was open
  AGAINST   a position against the trend was open
  FLAT      no position on that symbol; reason = first match of
              blocked_2A   a raw breakout signal in the trend direction existed but the ATR filter removed it
              slots_full   a 2A-valid signal existed but 4 positions were already open
              no_signal    no fresh 10-bar Donchian breakout outside the Kumo in the trend direction on that bar
Captured share = sum of trend-direction log returns of bars spent WITH / total trend log move.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
from high_cagr import run_suite as rs
H4=240*60000

def zigzag(close,th=.25):
    piv=[0];d=0;ext=0
    for i in range(1,len(close)):
        c=close[i]
        if d>=0 and c>=close[ext]:ext=i
        if d<=0 and c<=close[ext]:ext=i
        if d==0:
            if close[ext]/close[piv[-1]]-1>=th:d=1
            elif 1-close[ext]/close[piv[-1]]>=th:d=-1
            continue
        if d==1 and c<=close[ext]*(1-th):piv.append(ext);d=-1;ext=i
        elif d==-1 and c>=close[ext]*(1+th):piv.append(ext);d=1;ext=i
    piv.append(ext);return piv

def main():
    ctx=bench.load();c=hc.build(ctx,None);raw=bench.base_sig();(a,t,cv),b,e=bench._sim(c,'full',2);p=bench.positions(t)
    nb=ctx['sig'].shape[1];bts=rs.START+np.arange(nb)*H4          # bar boundary times (decision times)
    # open-position state per symbol and bar (position open at boundary bt if entry<=bt<exit)
    state=np.zeros((5,nb),int);opens=np.zeros(nb,int)
    for _,r in p.iterrows():
        j=bench.SYMBOLS.index(r.symbol);m=(bts>=r.entry_ts-3000)&(bts<r.exit_ts);state[j,m]=r.side;opens+=m
    trends=[];bars=[]
    for j,s in enumerate(bench.SYMBOLS):
        f=ctx['frames'][s];ix=ctx['ix'][s];close4=f.close.to_numpy()[ix]
        d=f.assign(day=(f.timestamp//86400000).astype(np.int64)).groupby('day').close.last();d=d[d.index*86400000>=rs.START]
        piv=zigzag(d.to_numpy())
        for k in range(len(piv)-1):
            i0,i1=piv[k],piv[k+1];mv=d.iat[i1]/d.iat[i0]-1;days=i1-i0
            if abs(mv)<.30 or days<7:continue
            side=1 if mv>0 else -1;t0=d.index[i0]*86400000+86400000;t1=d.index[i1]*86400000+86400000
            sel=np.where((bts>t0)&(bts<=t1))[0]
            if len(sel)<2:continue
            lr=np.diff(np.log(close4[sel]))*side          # trend-direction log return of each bar step
            st=state[j,sel[:-1]];rs_=raw[j,sel[:-1],0];vs=c['sig'][j,sel[:-1],0]
            reason=np.where(st==side,'WITH',np.where(st==-side,'AGAINST',
                     np.where(rs_==side,np.where(vs==side,np.where(opens[sel[:-1]]>=4,'FLAT:slots_full','FLAT:entered_next'),'FLAT:blocked_2A'),'FLAT:no_signal')))
            tot=np.log(d.iat[i1]/d.iat[i0])*side
            row=dict(symbol=s,side='UP' if side>0 else 'DOWN',start=str(pd.Timestamp(t0,unit='ms').date()),end=str(pd.Timestamp(t1,unit='ms').date()),days=int(days),move_pct=round(mv*100,1))
            for key in ('WITH','AGAINST','FLAT:blocked_2A','FLAT:slots_full','FLAT:no_signal','FLAT:entered_next'):
                row['share_'+key]=float(lr[reason==key].sum()/tot*100)
                row['bars_'+key]=int((reason==key).sum())
            pos=p[(p.symbol==s)&(p.entry_ts<t1)&(p.exit_ts>t0)]
            row['trades_with']=int((pos.side==side).sum());row['trades_against']=int((pos.side==-side).sum())
            row['pnl_with']=float(pos[pos.side==side].net.sum());row['pnl_against']=float(pos[pos.side==-side].net.sum())
            trends.append(row)
    T=pd.DataFrame(trends);T.to_csv(bench.OUT/'trend_audit.csv',index=False)
    cols=['share_WITH','share_AGAINST','share_FLAT:no_signal','share_FLAT:blocked_2A','share_FLAT:slots_full','share_FLAT:entered_next']
    w=T.assign(lm=np.log1p(T.move_pct.abs()/100*np.where(T.side=='UP',1,-1)).abs())
    print(f"{len(T)} trends >=30% on 5 symbols ({(T.side=='UP').sum()} up, {(T.side=='DOWN').sum()} down)")
    print('move-weighted share of trend log-move, %:');print((w[cols].mul(w.lm,axis=0).sum()/w.lm.sum()).round(1).to_string())
    print('\nby direction:');print(w.groupby('side').apply(lambda g:(g[cols].mul(g.lm,axis=0).sum()/g.lm.sum()).round(1),include_groups=False).to_string())
    print('\nPnL inside trends: with $%.0f, against $%.0f'%(T.pnl_with.sum(),T.pnl_against.sum()))
    print('\nbiggest trends:');print(T.sort_values('move_pct',key=abs,ascending=False).head(15)[['symbol','side','start','end','days','move_pct','share_WITH','share_AGAINST','share_FLAT:no_signal','share_FLAT:blocked_2A','trades_with','trades_against','pnl_with','pnl_against']].round(0).to_string(index=False))
    return T
if __name__=='__main__':main()
