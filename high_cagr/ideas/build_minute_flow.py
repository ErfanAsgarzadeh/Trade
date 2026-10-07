"""Minute volume / taker-buy volume / trade count aligned with prepared/<sym>/prices.npy (from run_suite.START)."""
from pathlib import Path
import sys,zipfile,glob
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
OUT=ROOT/'high_cagr/prepared_flow1m';OUT.mkdir(exist_ok=True)
for s in ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT']:
    n=len(np.load(ROOT/'high_cagr/prepared'/s/'prices.npy',mmap_mode='r'));cache=ROOT/('btc_backtest/cache' if s=='BTCUSDT' else 'portfolio/cache');parts=[]
    for p in sorted(glob.glob(str(cache/f'{s}-1m-*.zip'))):
        with zipfile.ZipFile(p) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=[0,5,8,9],names=['t','vol','cnt','tbv'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        parts.append(d)
    d=pd.concat(parts).drop_duplicates('t');i=((d.t-rs.START)//60000).astype(np.int64).to_numpy();m=(i>=0)&(i<n)
    a=np.zeros((n,3),np.float32);a[i[m]]=d[['vol','tbv','cnt']].to_numpy(np.float32)[m]
    assert m.sum()==n,(s,m.sum(),n);np.save(OUT/f'{s}.npy',a);print(s,n,flush=True)
