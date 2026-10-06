"""Strict minute coverage, frozen funding and exact 199-closed-bar indicators."""
from pathlib import Path
import sys,json,hashlib,zipfile
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'btc_backtest'));sys.path.insert(0,str(ROOT.parent/'lbank_project'))
import backtest as bt, strategy_archetypes as shared, lbank_bot as bot
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','ADAUSDT']
SETTINGS={'standard':(9,26,52,26),'crypto':(20,60,120,30)}
def main():
 rows=json.loads((ROOT/'output/data_manifest.json').read_text());checks=[]
 for symbol in SYMBOLS:
  selected=[x for x in rows if x['symbol']==symbol]
  if len(selected)!=126 or any(x['status']!='verified' for x in selected):print('NOT READY',symbol,len(selected),flush=True);continue
  dst=ROOT/'prepared'/symbol;dst.mkdir(parents=True,exist_ok=True)
  if (dst/'manifest.json').exists():checks.append(json.loads((dst/'manifest.json').read_text()));continue
  cache=ROOT.parent/'btc_backtest/cache' if symbol=='BTCUSDT' else ROOT/'cache';frames=[]
  repairs=json.loads((ROOT/'output/repair_manifest.json').read_text()) if (ROOT/'output/repair_manifest.json').exists() else []
  extra=[x for x in repairs if x['symbol']==symbol]
  if any(x['status']!='verified' for x in extra):raise ValueError('Unverified repair')
  sources=selected+extra
  for r in sorted([x for x in sources if '-1m-' in x['name']],key=lambda x:x['name']):
   p=cache/r['name'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
   with zipfile.ZipFile(p) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=range(6),names=['timestamp','open','high','low','close','volume'],low_memory=False)
   d=d[pd.to_numeric(d.timestamp,errors='coerce').notna()].astype(float)
   if d.timestamp.max()>1e14:d.timestamp/=1000
   frames.append(d)
  d=pd.concat(frames,ignore_index=True).sort_values('timestamp');d=d[d.timestamp<bt.END].reset_index(drop=True)
  expected=np.arange(int(d.timestamp.iloc[0]),bt.END,60000,dtype=np.int64)
  if not np.array_equal(d.timestamp.astype(np.int64),expected):raise ValueError('Missing/duplicate minute '+symbol)
  if not np.isfinite(d.to_numpy()).all() or (d[['open','high','low','close']]<=0).any().any():raise ValueError('Invalid prices '+symbol)
  if ((d.high<d[['open','close','low']].max(axis=1))|(d.low>d[['open','close','high']].min(axis=1))).any():raise ValueError('Invalid OHLC '+symbol)
  raw=bt.aggregate(d,'4h');c=json.loads((ROOT.parent/'optimization/baseline/config.json').read_text());parity={}
  for setting,params in SETTINGS.items():
   c['ichimoku_params'].update(zip(['tenkan','kijun','senkou_b','displacement'],params));frame=shared.add_features(bt.prepare_indicators(raw,c))
   for end in np.linspace(199,len(raw)-2,10,dtype=int):
    batch=raw.iloc[end-198:end+2][['timestamp','open','high','low','close','volume']].values.tolist()
    actual=bot.indicators(batch,c,'4h',(raw.iloc[end+1].timestamp+3000)/1000).iloc[-1]
    cols=['kijun','kumo_top','kumo_bottom','atr'];np.testing.assert_allclose(frame.iloc[end][cols].astype(float),actual[cols].astype(float),rtol=1e-11,atol=1e-8)
   parity[setting]=10;np.savez_compressed(dst/(setting+'.npz'),data=frame.to_numpy(),columns=json.dumps(list(frame.columns)))
  test=d[d.timestamp>=bt.START];prices=test[['open','high','low','close']].to_numpy();np.save(dst/'prices.npy',prices);fund=np.full(len(prices),np.nan);events=[]
  for r in [x for x in selected if '-fundingRate-' in x['name']]:
   p=cache/r['name'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
   with zipfile.ZipFile(p) as z:events.append(pd.read_csv(z.open(z.namelist()[0])))
  f=pd.concat(events,ignore_index=True);ts=f.calc_time.astype(np.int64)//60000*60000;assert not ts.duplicated().any()
  ix=((ts-bt.START)//60000).to_numpy();mask=(ix>=0)&(ix<len(fund));fund[ix[mask]]=f.last_funding_rate.to_numpy()[mask];np.save(dst/'funding.npy',fund)
  if symbol=='BTCUSDT':
   old=np.load(ROOT.parent/'optimization/features.npz');assert np.array_equal(prices,old['prices']) and np.array_equal(fund,old['funding'],equal_nan=True)
  result=dict(symbol=symbol,recovery_archives=len(extra),minutes=len(prices),warmup_minutes=len(d)-len(test),observed_funding_events=int(mask.sum()),parity_windows=parity,prices_sha256=hashlib.sha256(prices.tobytes()).hexdigest(),unknown_funding_from='2026-10-01T00:00:00Z')
  (dst/'manifest.json').write_text(json.dumps(result,indent=2));checks.append(result);print('PREPARED',result,flush=True)
 (ROOT/'output/coverage.json').write_text(json.dumps(checks,indent=2))
 if len(checks)!=6:raise SystemExit(2)
if __name__=='__main__':main()
