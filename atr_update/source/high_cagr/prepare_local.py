"""Verified 1m feeds, exact frozen Wilder windows, and causal 4h/1h features."""
from pathlib import Path
import sys,json,zipfile,hashlib
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT.parents[1]/'btc_backtest'),str(ROOT/'lbank_project')]
import backtest as bt, lbank_bot as bot, strategy_archetypes as shared
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT']
PRESETS={'standard':(9,26,52,26)}
def main():
 manifest=json.loads((ROOT/'portfolio/output/data_manifest.json').read_text());repairs=json.loads((ROOT/'portfolio/output/repair_manifest.json').read_text());results=[]
 for symbol in SYMBOLS:
  dst=ROOT/'high_cagr/prepared'/symbol;dst.mkdir(parents=True,exist_ok=True)
  if (dst/'manifest.json').exists():
   try:
    for tf in ['4h']:
     for preset in PRESETS:
      with zipfile.ZipFile(dst/f'{tf}_{preset}.npz') as z:assert z.testzip() is None
    results.append(json.loads((dst/'manifest.json').read_text()));continue
   except (zipfile.BadZipFile, AssertionError):print('REBUILD INVALID CHECKPOINT',symbol,flush=True)
  selected=[r for r in manifest if r['symbol']==symbol];extra=[r for r in repairs if r['symbol']==symbol]
  assert len(selected)==126 and all(r['status']=='verified' for r in selected+extra)
  cache=ROOT.parents[1]/'btc_backtest/cache' if symbol=='BTCUSDT' else ROOT/'portfolio/cache';frames=[]
  for r in sorted([x for x in selected+extra if '-1m-' in x['name']],key=lambda r:r['name']):
   p=cache/r['name'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
   with zipfile.ZipFile(p) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=range(6),names=['timestamp','open','high','low','close','volume'],low_memory=False)
   d=d[pd.to_numeric(d.timestamp,errors='coerce').notna()].astype(float)
   if d.timestamp.max()>1e14:d.timestamp/=1000
   frames.append(d)
  d=pd.concat(frames,ignore_index=True).sort_values('timestamp');d=d[d.timestamp<bt.END].reset_index(drop=True);del frames
  assert np.array_equal(d.timestamp.astype(np.int64),np.arange(int(d.timestamp.iloc[0]),bt.END,60000,dtype=np.int64))
  assert np.isfinite(d.to_numpy()).all() and (d[['open','high','low','close']]>0).all().all()
  assert not ((d.high<d[['open','close','low']].max(axis=1))|(d.low>d[['open','close','high']].min(axis=1))).any()
  for tf in ['4h']:
   raw=bt.aggregate(d,tf)
   for preset,params in PRESETS.items():
    c=json.loads((ROOT/'lbank_project/config.json').read_text());c['ichimoku_params'].update(zip(['tenkan','kijun','senkou_b','displacement'],params))
    f=shared.add_features(bt.prepare_indicators(raw,c))
    for n in [15,40]:
     f[f'donchian_high_{n}']=f.high.rolling(n).max().shift(1);f[f'donchian_low_{n}']=f.low.rolling(n).min().shift(1)
    for end in np.linspace(199,len(raw)-2,6,dtype=int):
     actual=bot.indicators(raw.iloc[end-198:end+2][['timestamp','open','high','low','close','volume']].values.tolist(),c,tf,(raw.iloc[end+1].timestamp+3000)/1000).iloc[-1]
     cols=['kijun','atr','kumo_top','kumo_bottom'];np.testing.assert_allclose(f.iloc[end][cols].astype(float),actual[cols].astype(float),rtol=1e-11,atol=1e-8)
    temp=dst/f'{tf}_{preset}.tmp.npz';np.savez_compressed(temp,data=f.to_numpy(),columns=json.dumps(list(f.columns)));
    with zipfile.ZipFile(temp) as z:assert z.testzip() is None
    temp.replace(dst/f'{tf}_{preset}.npz')
  prices=d[d.timestamp>=bt.START][['open','high','low','close']].to_numpy();del d
  np.save(dst/'prices.npy',prices);fund=np.full(len(prices),np.nan);events=[]
  for r in [x for x in selected if '-fundingRate-' in x['name']]:
   p=cache/r['name'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
   with zipfile.ZipFile(p) as z:events.append(pd.read_csv(z.open(z.namelist()[0])))
  f=pd.concat(events,ignore_index=True);ts=f.calc_time.astype(np.int64)//60000*60000;assert not ts.duplicated().any();ix=((ts-bt.START)//60000).to_numpy();mask=(ix>=0)&(ix<len(fund));fund[ix[mask]]=f.last_funding_rate.to_numpy()[mask];np.save(dst/'funding.npy',fund)
  old=next(r for r in json.loads((ROOT/'portfolio/output/coverage.json').read_text()) if r['symbol']==symbol)
  sha=hashlib.sha256(prices.tobytes()).hexdigest();assert sha==old['prices_sha256']
  result=dict(symbol=symbol,minutes=len(prices),prices_sha256=sha,parity_windows=6,observed_funding_events=int(mask.sum()),gap_repairs=len(extra));(dst/'manifest.json').write_text(json.dumps(result,indent=2));results.append(result);print('PREPARED',result,flush=True)
 (ROOT/'high_cagr/output/coverage.json').write_text(json.dumps(results,indent=2))
if __name__=='__main__':main()
