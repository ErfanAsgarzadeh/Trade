"""Binance SPOT 1h closes (SHA-256 verified) for the TTT coins, aligned to the hourly grid from rs.START.
Saved as high_cagr/prepared_spot/<PERP_SYMBOL>.npy (float64, NaN where the spot pair has no candle); the 1000x perps map
to their spot pair (1000PEPEUSDT -> PEPEUSDT x 1000) so prices are directly comparable with the perp."""
from pathlib import Path
import sys,io,re,json,zipfile,hashlib,urllib.request,concurrent.futures,time
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.chabok import research as RS
BASE='https://data.binance.vision/';LIST='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix={}&delimiter=/'
CACHE=ROOT/'high_cagr/cache_spot';PREP=ROOT/'high_cagr/prepared_spot'
START=pd.Timestamp('2021-10-05',tz='UTC');HOURS=1826*24
def spot_of(s):return (s[4:],1000.) if s.startswith('1000') else (s,1.)
def get(url):
    for k in range(6):
        try:return urllib.request.urlopen(url,timeout=90).read()
        except Exception as exc:
            if '404' in str(exc):raise
            time.sleep(2+2*k)
    raise RuntimeError(url)
def months(sym):
    x=get(LIST.format(f'data/spot/monthly/klines/{sym}/1h/')).decode();return sorted(re.findall(rf'{sym}-1h-(\d{{4}}-\d{{2}})\.zip<',x))
def fetch(rel):
    dest=CACHE/rel;dest.parent.mkdir(parents=True,exist_ok=True);sha=get(BASE+rel+'.CHECKSUM').decode().split()[0]
    if not (dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()==sha):
        data=get(BASE+rel);assert hashlib.sha256(data).hexdigest()==sha;dest.write_bytes(data)
    return rel
def build(perp):
    sym,mult=spot_of(perp);ms=[m for m in months(sym) if m>='2021-09']
    if not ms:return perp,0
    rels=[f'data/spot/monthly/klines/{sym}/1h/{sym}-1h-{m}.zip' for m in ms]+[f'data/spot/daily/klines/{sym}/1h/{sym}-1h-2026-10-0{d}.zip' for d in range(1,5)]
    got=[]
    for r in rels:
        try:got.append(fetch(r))
        except Exception as exc:
            if '404' not in str(exc):raise
    out=np.full(HOURS,np.nan)
    for r in got:
        with zipfile.ZipFile(CACHE/r) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None,usecols=[0,4],names=['t','c'])
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float);t=d.t.to_numpy()
        t=np.where(t>1e14,t/1000,t);i=((t-START.timestamp()*1000)//3600000).astype(np.int64);m=(i>=0)&(i<HOURS);out[i[m]]=d.c.to_numpy()[m]*mult
    PREP.mkdir(parents=True,exist_ok=True);np.save(PREP/f'{perp}.npy',out);return perp,int(np.isfinite(out).sum())
def main():
    A,B=RS.groups();res={}
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for perp,n in pool.map(build,A+B):res[perp]=n;print(perp,'spot hours',n,flush=True)
    (PREP/'coverage.json').write_text(json.dumps(res,indent=1))
if __name__=='__main__':main()
