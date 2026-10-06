from pathlib import Path
import json,zipfile
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
rows=json.loads((ROOT/'output/data_manifest.json').read_text());results=[]
for symbol in ['SOLUSDT','XRPUSDT','ADAUSDT']:
 chosen=[x for x in rows if x['symbol']==symbol and '-1m-' in x['name']]
 if len(chosen)<66:continue
 pieces=[]
 for r in sorted(chosen,key=lambda x:x['name']):
  with zipfile.ZipFile(ROOT/'cache'/r['name']) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=[0],names=['timestamp'],low_memory=False)
  a=pd.to_numeric(d.timestamp,errors='coerce').dropna().to_numpy(dtype=np.int64)
  if a.max()>1e14:a=a//1000
  pieces.append(a)
 a=np.sort(np.concatenate(pieces));expected=np.arange(a[0],1791158400000,60000,dtype=np.int64);a=a[a<1791158400000]
 missing=np.setdiff1d(expected,a);dup=a[1:][a[1:]==a[:-1]]
 result=dict(symbol=symbol,missing_count=len(missing),duplicate_count=len(dup),missing_ms=missing.tolist(),duplicate_ms=dup.tolist(),dates=sorted(set(pd.to_datetime(missing,unit='ms',utc=True).strftime('%Y-%m-%d'))))
 results.append(result);print(symbol,'MISSING',len(missing),'DUP',len(dup),'DATES',result['dates'],'FIRST',pd.to_datetime(missing[:10],unit='ms',utc=True).tolist(),flush=True)
(ROOT/'output/coverage_issues.json').write_text(json.dumps(results,indent=2))
