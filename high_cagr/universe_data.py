"""Expanded training universe: up to 100 extra Binance USD-M perpetuals (USDT) that have 4h klines from 2021-08 to 2026-09,
ranked by quote volume in 2024-06, excluding the 35 traded coins. Downloads (resumable, SHA-256 checked where provided):
4h klines (monthly + Oct 1-4 2026 daily), funding rate (monthly), metrics (daily, from 2021-12-01). Used for model training only."""
from pathlib import Path
import sys,re,io,json,time,zipfile,hashlib,urllib.request,concurrent.futures
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import criteria_lib as C
BASE='https://data.binance.vision/';CACHE=ROOT/'high_cagr/cache_universe';S3='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
MONTHS=[f'{y}-{m:02d}' for y in range(2021,2027) for m in range(1,13) if '2021-08'<=f'{y}-{m:02d}'<='2026-09']
DAYS=[d.strftime('%Y-%m-%d') for d in pd.date_range('2021-12-01','2026-10-04')]
def get(url,ok404=True):
    for k in range(5):
        try:return urllib.request.urlopen(url,timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code==404 and ok404:return None
            time.sleep(2*(k+1))
        except Exception:time.sleep(2*(k+1))
    return None
def symbols():
    out=[];marker=''
    while True:
        x=get(f'{S3}?prefix=data/futures/um/monthly/klines/&delimiter=/&marker={marker}').decode()
        out+=re.findall(r'klines/([A-Z0-9]+)/</Prefix>',x)
        m=re.search(r'<NextMarker>(.*?)</NextMarker>',x)
        if not m:break
        marker=m.group(1)
    return [s for s in out if s.endswith('USDT')]
def qv(s):
    a=get(f'{BASE}data/futures/um/monthly/klines/{s}/4h/{s}-4h-2021-08.zip');b=get(f'{BASE}data/futures/um/monthly/klines/{s}/4h/{s}-4h-2026-09.zip');c=get(f'{BASE}data/futures/um/monthly/klines/{s}/4h/{s}-4h-2024-06.zip')
    if not (a and b and c):return s,None
    with zipfile.ZipFile(io.BytesIO(c)) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None)
    d=d[pd.to_numeric(d[0],errors='coerce').notna()];return s,float(pd.to_numeric(d[7]).sum())
def fetch(rel):
    f=CACHE/rel
    if f.exists() or f.with_suffix('.none').exists():return 0
    b=get(BASE+rel);f.parent.mkdir(parents=True,exist_ok=True)
    if b is None:f.with_suffix('.none').write_text('');return 1
    f.write_bytes(b);return 0
def main():
    CACHE.mkdir(parents=True,exist_ok=True);sel=CACHE/'selected.json'
    if not sel.exists():
        syms=[s for s in symbols() if s not in C.COINS];print('USDT perps listed',len(syms),flush=True)
        with concurrent.futures.ThreadPoolExecutor(24) as ex:vols=[r for r in ex.map(qv,syms) if r[1]]
        vols.sort(key=lambda t:-t[1]);chosen=[s for s,_ in vols[:100]];sel.write_text(json.dumps(dict(chosen=chosen,eligible=len(vols))));print('eligible',len(vols),'chosen',len(chosen),flush=True)
    chosen=json.loads(sel.read_text())['chosen'];rels=[]
    for s in chosen:
        rels+=[f'data/futures/um/monthly/klines/{s}/4h/{s}-4h-{m}.zip' for m in MONTHS]+[f'data/futures/um/daily/klines/{s}/4h/{s}-4h-2026-10-0{d}.zip' for d in range(1,5)]
        rels+=[f'data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip' for m in MONTHS if m>='2021-10']
        rels+=[f'data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip' for d in DAYS]
    for s in C.COINS:rels+=[f'data/futures/um/monthly/klines/{s}/4h/{s}-4h-{m}.zip' for m in MONTHS]+[f'data/futures/um/daily/klines/{s}/4h/{s}-4h-2026-10-0{d}.zip' for d in range(1,5)]
    print('files',len(rels),flush=True);miss=0
    with concurrent.futures.ThreadPoolExecutor(24) as ex:
        for k,r in enumerate(ex.map(fetch,rels)):
            miss+=r
            if k%10000==0:print('done',k,'/',len(rels),'missing',miss,flush=True)
    print('finished missing',miss,flush=True)
if __name__=='__main__':main()
