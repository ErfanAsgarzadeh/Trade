"""4h taker-buy aggregates from the verified Binance 1m kline archives (column taker_buy_volume, never used before)."""
from pathlib import Path
import sys,zipfile,glob
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'high_cagr/prepared_orderflow';OUT.mkdir(exist_ok=True)
H4=14400000
for s in ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT']:
    cache=ROOT/('btc_backtest/cache' if s=='BTCUSDT' else 'portfolio/cache');parts=[]
    for p in sorted(glob.glob(str(cache/f'{s}-1m-*.zip'))):
        with zipfile.ZipFile(p) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=[0,5,8,9],names=['t','vol','cnt','tbv'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        parts.append(d)
    d=pd.concat(parts).drop_duplicates('t').sort_values('t');d['k']=(d.t//H4).astype(np.int64)
    g=d.groupby('k').agg(vol=('vol','sum'),tbv=('tbv','sum'),cnt=('cnt','sum'),n=('t','size'))
    g.index=g.index*H4;g.index.name='timestamp';g.to_csv(OUT/f'{s}_4h.csv');print(s,len(g),pd.to_datetime(g.index[[0,-1]],unit='ms').tolist(),'incomplete bars',int((g.n<240).sum()),flush=True)
