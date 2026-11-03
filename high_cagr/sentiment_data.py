"""Download (resumable) historical sentiment / positioning data for the 35 coins:
Binance USD-M daily 'metrics' (5-min open interest, top-trader and global long/short ratios, taker buy/sell volume ratio),
Crypto Fear & Greed index (alternative.me, daily), total stablecoin supply (DefiLlama, daily)."""
from pathlib import Path
import sys,json,time,urllib.request,concurrent.futures
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pabench as PB
OUT=ROOT/'high_cagr/cache_sentiment';BASE='https://data.binance.vision/data/futures/um/daily/metrics/'
DAYS=pd.date_range('2021-12-01','2026-10-04')
def get(url):
    for k in range(5):
        try:return urllib.request.urlopen(url,timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            time.sleep(2*(k+1))
        except Exception:time.sleep(2*(k+1))
    return None
def fetch(a):
    s,d=a;f=OUT/'metrics'/s/f'{s}-metrics-{d}.zip'
    if f.exists() or (f.with_suffix('.none')).exists():return 0
    b=get(f'{BASE}{s}/{s}-metrics-{d}.zip');f.parent.mkdir(parents=True,exist_ok=True)
    if b is None:f.with_suffix('.none').write_text('');return 1
    f.write_bytes(b);return 0
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'fng.json').write_bytes(get('https://api.alternative.me/fng/?limit=0&format=json'))
    (OUT/'stablecoins.json').write_bytes(get('https://stablecoins.llama.fi/stablecoincharts/all'))
    jobs=[(s,d.strftime('%Y-%m-%d')) for s in sorted(set(PB.ALL35)) for d in DAYS];miss=0
    with concurrent.futures.ThreadPoolExecutor(24) as ex:
        for k,r in enumerate(ex.map(fetch,jobs)):
            miss+=r
            if k%5000==0:print('done',k,'/',len(jobs),'missing',miss,flush=True)
    print('finished, missing',miss,flush=True)
if __name__=='__main__':main()
