"""Resumable SHA256 verified official USD-M archives, atomic progress per result."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,json,time,urllib.request,urllib.error,os
import pandas as pd
ROOT=Path(__file__).resolve().parent
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','ADAUSDT']
BASE='https://data.binance.vision/data/futures/um/'
MANIFEST=ROOT/'output/data_manifest.json'
def atomic(path,data):
 p=path.with_suffix(path.suffix+'.tmp');p.write_text(json.dumps(data,indent=2));p.replace(path)
def jobs():
 for s in SYMBOLS:
  for d in pd.period_range('2021-08','2026-09',freq='M'):
   n=f'{s}-1m-{d}.zip';yield s,n,BASE+f'monthly/klines/{s}/1m/{n}'
  for day in range(1,5):
   n=f'{s}-1m-2026-10-{day:02d}.zip';yield s,n,BASE+f'daily/klines/{s}/1m/{n}'
  for d in pd.period_range('2021-10','2026-09',freq='M'):
   n=f'{s}-fundingRate-{d}.zip';yield s,n,BASE+f'monthly/fundingRate/{s}/{n}'
def fetch(job,known):
 s,n,u=job;cache=ROOT.parent/'btc_backtest/cache' if s=='BTCUSDT' else ROOT/'cache'
 p=cache/n;c=cache/(n+'.CHECKSUM');expected=known.get(n,{}).get('sha256')
 error=''
 for attempt in range(3):
  try:
   if not expected:
    if not c.exists():
     with urllib.request.urlopen(u+'.CHECKSUM',timeout=25) as r:payload=r.read()
     c.write_bytes(payload)
    expected=c.read_text().split()[0]
   if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
    with urllib.request.urlopen(u,timeout=60) as r:payload=r.read()
    if hashlib.sha256(payload).hexdigest()!=expected:raise ValueError('Checksum mismatch')
    temp=p.with_suffix('.part');temp.write_bytes(payload);temp.replace(p)
   return dict(symbol=s,name=n,url=u,status='verified',sha256=expected,bytes=p.stat().st_size)
  except Exception as e:
   error=str(e)
   if isinstance(e,urllib.error.HTTPError) and e.code in [403,451]:break
   if attempt<2:time.sleep(attempt+1)
 return dict(symbol=s,name=n,url=u,status='error',error=error)
def main():
 known={x['name']:x for x in json.loads((ROOT.parent/'btc_backtest/output/data_manifest.json').read_text())}
 if MANIFEST.exists():known.update({x['name']:x for x in json.loads(MANIFEST.read_text())})
 results={};work=list(jobs());atomic(ROOT/'output/download_state.json',dict(pid=os.getpid(),status='running',started_utc=pd.Timestamp.now(tz='UTC').isoformat(),total=len(work)))
 with ThreadPoolExecutor(max_workers=16) as pool:
  tasks={pool.submit(fetch,job,known):job for job in work}
  for f in as_completed(tasks):
   row=f.result();results[row['name']]=row
   atomic(MANIFEST,sorted(results.values(),key=lambda x:x['name']))
   if len(results)%20==0 or row['status']!='verified':print(len(results),len(work),row['name'],row['status'],row.get('error',''),flush=True)
 bad=[x for x in results.values() if x['status']!='verified']
 atomic(ROOT/'output/download_state.json',dict(status='failed' if bad else 'complete',completed_utc=pd.Timestamp.now(tz='UTC').isoformat(),total=len(work),verified=len(work)-len(bad),failures=bad))
 print('DONE',len(results),'failures',len(bad),flush=True)
 if bad:raise SystemExit(1)
if __name__=='__main__':main()
