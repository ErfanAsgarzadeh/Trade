"""Reproduce Quant Ichimoku research using local verified Binance USD-M archive files.
Run from repository ROOT: python -m quant_ichimoku.run --source repo --symbols BTCUSDT ...
"""
import argparse
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd
from .backtester import Settings, backtest

ROOT=Path(__file__).resolve().parent.parent
BASE_COLS=['timestamp','open','high','low','close','volume']


def from_archive(symbol, start='2021-08', end='2026-10'):
    cache=ROOT/('btc_backtest/cache' if symbol=='BTCUSDT' else 'portfolio/cache')
    names=[f'{symbol}-1m-{month}.zip' for month in pd.period_range(start,'2026-09',freq='M')]
    names += [f'{symbol}-1m-2026-10-{day:02d}.zip' for day in range(1,5)]
    # SOL/XRP monthly archives omitted 5 dates in 2022. Include the verified
    # daily repairs already tracked by portfolio/prepare_data.py.
    repairs=ROOT/'portfolio/output/repair_manifest.json'
    if repairs.exists():
        names += [r['name'] for r in json.loads(repairs.read_text())
                  if r.get('symbol')==symbol and r.get('status')=='verified']
    missing=[n for n in names if not (cache/n).exists()]
    if missing:raise FileNotFoundError(f'{symbol}: {len(missing)} missing archives e.g. {missing[:3]} (run python restore_data.py)')
    chunks=[]
    for name in names:
        with zipfile.ZipFile(cache/name) as z:
            if z.testzip() is not None:raise ValueError(f'Corrupt zip: {name}')
            src=z.namelist()[0]
            raw=pd.read_csv(z.open(src),header=None,usecols=list(range(6)),names=BASE_COLS,low_memory=False)
        raw=raw[pd.to_numeric(raw.timestamp,errors='coerce').notna()].copy()
        for col in BASE_COLS:raw[col]=pd.to_numeric(raw[col],errors='raise')
        if raw.timestamp.max()>1e14:raw['timestamp']=raw.timestamp//1000
        chunks.append(raw)
    minute=pd.concat(chunks,ignore_index=True)
    minute=minute.sort_values('timestamp')
    minute=minute[minute.timestamp< pd.Timestamp('2026-10-05',tz='UTC').timestamp()*1000]
    if minute.timestamp.duplicated().any():raise ValueError(f'{symbol}: duplicate minute')
    minute.index=pd.to_datetime(minute.timestamp,unit='ms',utc=True)
    if not minute.index.to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all():
        raise ValueError(f'{symbol}: gaps in minute data, REFUSE unverified fills')
    size=minute.close.resample('15min',label='left',closed='left').count()
    m15=minute[BASE_COLS[1:]].resample('15min',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    if not (size==15).all():raise ValueError(f'{symbol}: partial 15m candle')
    return m15


def from_csv(path):
    d=pd.read_csv(path)
    if 'timestamp' not in d:raise ValueError('Need timestamp column')
    val=d.pop('timestamp')
    if pd.api.types.is_numeric_dtype(val):
        unit='ms' if val.max()>1e11 else 's'
        d.index=pd.to_datetime(val,unit=unit,utc=True)
    else:d.index=pd.to_datetime(val,utc=True)
    return d


def main():
    pa=argparse.ArgumentParser()
    pa.add_argument('--source',choices=('repo','csv'),default='repo')
    pa.add_argument('--csv',help='M15 CSV input with UTC timestamp,open,high,low,close,volume')
    pa.add_argument('--symbols',nargs='+',default=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT'])
    pa.add_argument('--risk',type=float,default=0.015)
    pa.add_argument('--capital',type=float,default=1000.)
    pa.add_argument('--out',type=Path,default=ROOT/'quant_ichimoku/output')
    a=pa.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    settings=Settings(initial_capital=a.capital,risk_per_trade=a.risk)
    if a.source=='csv' and (not a.csv or len(a.symbols)!=1):
        pa.error('--source csv requires --csv and exactly one --symbols value')
    results={}
    for symbol in a.symbols:
        print('Loading',symbol,flush=True)
        d=from_csv(a.csv) if a.source=='csv' else from_archive(symbol)
        summary,ledger,curve=backtest(d,settings)
        summary.update(symbol=symbol,source='user supplied M15 CSV' if a.source=='csv' else 'Binance USD-M official 1m archives aggregated to M15',
         funding='NOT MODELED: figures exclude futures funding',account='Independent $1,000 per symbol, NOT shared-margin portfolio')
        results[symbol]=summary
        ledger.to_csv(a.out/f'{symbol}_trades.csv',index=False)
        curve.to_csv(a.out/f'{symbol}_equity.csv')
        print(symbol, 'trades',summary['closed_trades'],'return',round(summary['net_return_pct'],2),'DD',round(summary['max_drawdown_pct'],2),flush=True)
    (a.out/'report.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Saved',a.out/'report.json')

if __name__=='__main__':main()