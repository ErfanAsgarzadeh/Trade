"""TRAIN-only (<2025) look at order-flow features of the signal bar on the 2A+5A ledger. Validation not inspected."""
from pathlib import Path
import sys
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
from high_cagr import run_suite as rs
def flow(s,f):
    o=pd.read_csv(ROOT/f'high_cagr/prepared_orderflow/{s}_4h.csv').set_index('timestamp').reindex(f.timestamp.astype(np.int64))
    assert np.allclose(o.vol.to_numpy(),f.volume.to_numpy(),rtol=1e-6),s
    x=pd.DataFrame(index=f.index);x['tbr']=(o.tbv/o.vol).to_numpy();x['tbr_rel']=x.tbr-x.tbr.rolling(20).mean().shift(1)
    d=(2*o.tbv-o.vol).to_numpy();x['delta3']=pd.Series(d).rolling(3).sum().to_numpy()/pd.Series(o.vol.to_numpy()).rolling(3).sum().to_numpy()
    x['cnt_rel']=(o.cnt/o.cnt.rolling(20).mean().shift(1)).to_numpy();sz=(o.vol/o.cnt);x['size_rel']=(sz/sz.rolling(20).mean().shift(1)).to_numpy()
    return x
if __name__=='__main__':
    ctx=bench.load();c=hc.build(ctx,None);(a,t,curve),b,e=bench._sim(c,'full',2);p=bench.positions(t);p=p[p.entry_ts<rs.SPLIT].copy();p['R']=p.net/p.risk_usd;rows=[]
    for s in bench.SYMBOLS:
        f=ctx['frames'][s];x=flow(s,f);ix=ctx['ix'][s]
        for _,r in p[p.symbol==s].iterrows():
            row=ix[(r.entry_ts-3000-rs.START)//(240*60000)];d=r.side;v=x.iloc[row]
            rows.append(dict(R=r.R,net=r.net,side=d,tbr=v.tbr if d>0 else 1-v.tbr,tbr_rel=d*v.tbr_rel,delta3=d*v.delta3,cnt_rel=v.cnt_rel,size_rel=v.size_rel))
    X=pd.DataFrame(rows);print('train positions',len(X),'meanR %.3f'%X.R.mean())
    for col in ['tbr','tbr_rel','delta3','cnt_rel','size_rel']:
        z=X.dropna(subset=[col]);g=z.groupby(pd.qcut(z[col],5),observed=True).agg(n=('R','size'),meanR=('R','mean'),win=('R',lambda v:(v>0).mean()*100),net=('net','sum'))
        print('\n##',col);print(g.round(3).to_string())
