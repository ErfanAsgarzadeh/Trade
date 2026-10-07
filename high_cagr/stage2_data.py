"""Download (SHA-256 verified, resumable) and prepare the stage-2 symbols with the same feature code as prepare.py."""
from pathlib import Path
import sys,json,io,zipfile,hashlib,urllib.request,concurrent.futures,time
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'btc_backtest'),str(ROOT/'lbank_project')]
import backtest as bt, lbank_bot as bot, strategy_archetypes as shared
BASE='https://data.binance.vision/data/futures/um/';CACHE=ROOT/'high_cagr/cache_stage2';PREP=ROOT/'high_cagr/prepared_stage2';OUT=ROOT/'high_cagr/output'
MONTHS=[(y,m) for y in range(2021,2027) for m in range(1,13) if (2021,8)<=(y,m)<=(2026,9)]
def get(url):
    for k in range(6):
        try:return urllib.request.urlopen(url,timeout=120).read()
        except Exception:
            if k==5:raise
            time.sleep(2*(k+1))
def files(sym):
    out=[f'monthly/klines/{sym}/1m/{sym}-1m-{y}-{m:02d}.zip' for y,m in MONTHS]
    out+=[f'daily/klines/{sym}/1m/{sym}-1m-2026-10-0{d}.zip' for d in range(1,5)]
    out+=[f'monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip' for y,m in MONTHS if (y,m)>=(2021,10)]
    return out
def fetch(rel):
    dest=CACHE/rel;dest.parent.mkdir(parents=True,exist_ok=True)
    expected=get(BASE+rel+'.CHECKSUM').decode().split()[0]
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()==expected:return rel,expected,'cached'
    data=get(BASE+rel);assert hashlib.sha256(data).hexdigest()==expected,'checksum mismatch '+rel
    tmp=dest.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(dest);return rel,expected,'downloaded'
def read_zip(p,**kw):
    with zipfile.ZipFile(p) as z:return pd.read_csv(z.open(z.namelist()[0]),**kw)
def prepare(sym,manifest):
    dst=PREP/sym;dst.mkdir(parents=True,exist_ok=True)
    frames=[]
    for rel in [r for r in files(sym) if '-1m-' in r]:
        d=read_zip(CACHE/rel,header=None,usecols=range(6),names=['timestamp','open','high','low','close','volume'],low_memory=False)
        d=d[pd.to_numeric(d.timestamp,errors='coerce').notna()].astype(float)
        if d.timestamp.max()>1e14:d.timestamp/=1000
        frames.append(d)
    d=pd.concat(frames,ignore_index=True).drop_duplicates('timestamp').sort_values('timestamp');d=d[d.timestamp<bt.END]
    full=np.arange(int(d.timestamp.iloc[0]),bt.END,60000,dtype=np.int64);d=d.set_index(d.timestamp.astype(np.int64)).reindex(full)
    missing=d.close.isna().to_numpy();d['close']=d.close.ffill()
    for c in ['open','high','low']:d[c]=d[c].fillna(d.close)
    d['volume']=d.volume.fillna(0.);d['timestamp']=full.astype(float);d=d.reset_index(drop=True)
    assert np.isfinite(d.to_numpy()).all() and (d[['open','high','low','close']]>0).all().all()
    assert not ((d.high<d[['open','close','low']].max(axis=1))|(d.low>d[['open','close','high']].min(axis=1))).any()
    in_test=full>=bt.START;missing_test=int(missing[in_test].sum());frac=missing_test/int(in_test.sum())
    raw=bt.aggregate(d,'4h');c=json.loads((ROOT/'optimization/baseline/config.json').read_text());c['ichimoku_params'].update(zip(['tenkan','kijun','senkou_b','displacement'],(9,26,52,26)))
    f=shared.add_features(bt.prepare_indicators(raw,c))
    for end in np.linspace(199,len(raw)-2,6,dtype=int):   # parity with the live bot's indicator code
        actual=bot.indicators(raw.iloc[end-198:end+2][['timestamp','open','high','low','close','volume']].values.tolist(),c,'4h',(raw.iloc[end+1].timestamp+3000)/1000).iloc[-1]
        cols=['kijun','atr','kumo_top','kumo_bottom'];np.testing.assert_allclose(f.iloc[end][cols].astype(float),actual[cols].astype(float),rtol=1e-11,atol=1e-8)
    np.savez_compressed(dst/'4h_standard.npz',data=f.to_numpy(),columns=json.dumps(list(f.columns)))
    prices=d[d.timestamp>=bt.START][['open','high','low','close']].to_numpy();assert len(prices)==(bt.END-bt.START)//60000;np.save(dst/'prices.npy',prices)
    fund=np.full(len(prices),np.nan);ev=pd.concat([read_zip(CACHE/r) for r in files(sym) if 'fundingRate' in r],ignore_index=True)
    ts=ev.calc_time.astype(np.int64)//60000*60000;ix=((ts-bt.START)//60000).to_numpy();mask=(ix>=0)&(ix<len(fund));fund[ix[mask]]=ev.last_funding_rate.to_numpy()[mask];np.save(dst/'funding.npy',fund)
    info=dict(symbol=sym,minutes=len(prices),missing_minutes_in_test=missing_test,missing_fraction=frac,first_minute=int(full[0]),funding_events=int(mask.sum()),parity_windows=6,prices_sha256=hashlib.sha256(prices.tobytes()).hexdigest())
    (dst/'manifest.json').write_text(json.dumps(info,indent=1));return info
def main():
    chosen=[c['symbol'] for c in json.loads((OUT/'stage2_selection.json').read_text())['chosen']]
    rels=[r for s in chosen for r in files(s)];print('files',len(rels),flush=True);manifest=[]
    with concurrent.futures.ThreadPoolExecutor(12) as pool:
        for k,(rel,sha,how) in enumerate(pool.map(fetch,rels)):
            manifest.append(dict(file=rel,sha256=sha))
            if k%100==0:print('verified',k,flush=True)
    (OUT/'stage2_data_manifest.json').write_text(json.dumps(manifest,indent=0))
    infos=[]
    for s in chosen:
        info=prepare(s,manifest);infos.append(info);print('PREPARED',s,'missing',info['missing_minutes_in_test'],f"({info['missing_fraction']*100:.3f}%)",flush=True)
    (OUT/'stage2_coverage.json').write_text(json.dumps(infos,indent=1))
if __name__=='__main__':main()
