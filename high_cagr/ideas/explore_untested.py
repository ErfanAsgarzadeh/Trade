"""Exploration of never-tested entry features on the 2A+5A ledger. TRAIN entries (<2025) only; validation is not looked at."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
from high_cagr import run_suite as rs
ctx=bench.load();c=hc.build(ctx,None);(a,t,curve),b,e=bench._sim(c,'full',2);p=bench.positions(t)
p=p[p.entry_ts<rs.SPLIT].copy();p['R']=p.net/p.risk_usd
fund=ctx['funding'];rows=[]
for s in bench.SYMBOLS:
    f=ctx['frames'][s];j=bench.SYMBOLS.index(s);ix=ctx['ix'][s]
    hi60=f.high.rolling(60).max().shift(1);lo60=f.low.rolling(60).min().shift(1)
    hi120=f.high.rolling(120).max().shift(1);lo120=f.low.rolling(120).min().shift(1)
    q=p[p.symbol==s]
    for _,r in q.iterrows():
        bar=(r.entry_ts-3000-rs.START)//(240*60000);row=ix[bar];x=f.iloc[row];d=r.side;atr=x.atr
        # funding prints before entry
        m=(r.entry_ts-3000-rs.START)//60000;fr=fund[j,:m];fr=fr[np.isfinite(fr)][-9:]
        rows.append(dict(R=r.R,net=r.net,side=d,sym=s,
          room60=(d*((hi60.iat[row] if d>0 else lo60.iat[row])-x.close))/atr,
          room120=(d*((hi120.iat[row] if d>0 else lo120.iat[row])-x.close))/atr,
          thick=abs(x.senkou_a_curr-x.senkou_b_curr)/atr,
          dkumo=d*(x.close-(x.kumo_top if d>0 else x.kumo_bottom))/atr,
          runup=d*(x.close-f.close.iat[row-6])/atr,
          atrslope=x.atr/f.atr.iat[row-6],
          hour=int((x.timestamp//3600000)%24),wd=pd.Timestamp(x.timestamp,unit='ms').weekday(),
          fund=d*(np.mean(fr) if len(fr)==9 else np.nan)*1e4))
X=pd.DataFrame(rows);print('train positions',len(X),'mean R %.3f'%X.R.mean())
for col in ['room60','room120','thick','dkumo','runup','atrslope','fund']:
    z=X.dropna(subset=[col]);qq=pd.qcut(z[col],5,duplicates='drop')
    g=z.groupby(qq,observed=True).agg(n=('R','size'),meanR=('R','mean'),win=('R',lambda v:(v>0).mean()*100),net=('net','sum'))
    print('\n##',col);print(g.round(3).to_string())
for col in ['hour','wd']:
    g=X.groupby(col).agg(n=('R','size'),meanR=('R','mean'),net=('net','sum'));print('\n##',col);print(g.round(3).to_string())
print('\n## room60<0 means close already above the 60-bar high (new high)')
