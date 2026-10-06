"""Download checksum-verified Binance USD-M BTCUSDT archives."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import time
import requests
import pandas as pd
import zipfile

ROOT=Path(__file__).parent
CACHE=ROOT/'cache'
CACHE.mkdir(exist_ok=True)
BASE='https://data.binance.vision/data/futures/um'
manifest_path=ROOT/'output'/'data_manifest.json'
EXPECTED={r['name']:r for r in json.loads(manifest_path.read_text())} if manifest_path.exists() else {}


def fetch(kind,period,date):
    if kind=='klines':
        name=f'BTCUSDT-1m-{date}.zip'
        url=f'{BASE}/{period}/klines/BTCUSDT/1m/{name}'
    else:
        name=f'BTCUSDT-fundingRate-{date}.zip'
        url=f'{BASE}/monthly/fundingRate/BTCUSDT/{name}'
    target=CACHE/name
    for attempt in range(3):
        try:
            digest=EXPECTED.get(name,{}).get('sha256')
            if digest is None:
                checksum=requests.get(url+'.CHECKSUM',timeout=35)
                if checksum.status_code==404:
                    return {'name':name,'url':url,'status':'missing'}
                checksum.raise_for_status()
                digest=checksum.text.split()[0]
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                response=requests.get(url,timeout=90)
                response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest()!=digest:
                    raise ValueError('Checksum mismatch '+name)
                temporary=target.with_suffix('.tmp')
                temporary.write_bytes(response.content)
                temporary.replace(target)
            with zipfile.ZipFile(target) as z:
                if z.testzip():raise ValueError('Corrupt archive '+name)
            return {'name':name,'url':url,'sha256':digest,'size':target.stat().st_size,'status':'verified'}
        except Exception as exc:
            if attempt==2:return {'name':name,'url':url,'status':'error','error':str(exc)}
            time.sleep(attempt+1)


def main():
    months=pd.date_range('2021-08-01','2026-09-01',freq='MS')
    jobs=[('klines','monthly',d.strftime('%Y-%m')) for d in months]
    jobs += [('klines','daily',f'2026-10-{day:02d}') for day in range(1,5)]
    jobs += [('fundingRate','monthly',d.strftime('%Y-%m')) for d in months if d>=pd.Timestamp('2021-10-01')]
    results=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(fetch,*job) for job in jobs]
        for future in as_completed(futures):
            result=future.result();results.append(result)
            if len(results)%10==0 or result['status']!='verified':
                print(f"{len(results)}/{len(jobs)} {result['name']} {result['status']}",flush=True)
    (ROOT/'output'/'data_manifest.json').write_text(json.dumps(sorted(results,key=lambda r:r['name']),indent=2))
    print('Completed:',{status:sum(r['status']==status for r in results) for status in ['verified','missing','error']},flush=True)

if __name__=='__main__':main()
