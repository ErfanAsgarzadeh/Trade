"""Data for the TheTrueTrade futures universe (ttt_markets.json, scraped 2026-10-29 from thetruetrade.io/markets).

Every TTT perpetual with at least MIN_MONTHS of Binance USDT-M history (ttt_binance_coverage.json) is downloaded
(SHA-256 verified) and prepared like high_cagr/stage2_data.py into high_cagr/prepared_stage2/<SYM>. Coins listed after
the start of the test (2021-10-05) are PADDED before their first Binance minute with a flat candle (first open, zero
volume) so every engine sees the same minute grid; `first_minute` in the manifest marks the real listing and the study
ignores trades that open before listing + WARMUP_DAYS. The five Shahin coins keep their audited high_cagr/prepared data
(linked into prepared_stage2 so every bench can read them).
"""
from pathlib import Path
import sys,json,concurrent.futures,hashlib
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import stage2_data as S
bt,bot,shared=S.bt,S.bot,S.shared
HERE=Path(__file__).resolve().parent
MIN_MONTHS=18;WARMUP_DAYS=60
MAIN5=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT']

def universe():
    cov=json.loads((HERE/'ttt_binance_coverage.json').read_text())
    ok=[s for s,v in cov.items() if v['n']>=MIN_MONTHS];return sorted(ok),cov

def files(sym,first):
    fy,fm=map(int,first.split('-'))
    mon=[(y,m) for y,m in S.MONTHS if (y,m)>=(fy,fm)]
    out=[f'monthly/klines/{sym}/1m/{sym}-1m-{y}-{m:02d}.zip' for y,m in mon]
    out+=[f'daily/klines/{sym}/1m/{sym}-1m-2026-10-0{d}.zip' for d in range(1,5)]
    out+=[f'monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip' for y,m in mon if (y,m)>=(2021,10)]
    return out

def prepare(sym,first):
    dst=S.PREP/sym;dst.mkdir(parents=True,exist_ok=True);frames=[]
    for rel in [r for r in files(sym,first) if '-1m-' in r]:
        d=S.read_zip(S.CACHE/rel,header=None,usecols=range(6),names=['timestamp','open','high','low','close','volume'],low_memory=False)
        d=d[pd.to_numeric(d.timestamp,errors='coerce').notna()].astype(float)
        if d.timestamp.max()>1e14:d.timestamp/=1000
        frames.append(d)
    d=pd.concat(frames,ignore_index=True).drop_duplicates('timestamp').sort_values('timestamp');d=d[d.timestamp<bt.END]
    listed=int(d.timestamp.iloc[0]);begin=min(listed,bt.START-60*86400000)
    full=np.arange(begin,bt.END,60000,dtype=np.int64);d=d.set_index(d.timestamp.astype(np.int64)).reindex(full)
    pre=full<listed;missing=d.close.isna().to_numpy()&~pre
    first_open=float(d.open.dropna().iloc[0])
    d.loc[pre,['open','high','low','close']]=first_open;d.loc[pre,'volume']=0.
    d['close']=d.close.ffill()
    for c in ['open','high','low']:d[c]=d[c].fillna(d.close)
    d['volume']=d.volume.fillna(0.);d['timestamp']=full.astype(float);d=d.reset_index(drop=True)
    assert np.isfinite(d.to_numpy()).all() and (d[['open','high','low','close']]>0).all().all()
    assert not ((d.high<d[['open','close','low']].max(axis=1))|(d.low>d[['open','close','high']].min(axis=1))).any()
    in_test=(full>=bt.START)&(full>=listed);missing_test=int(missing[in_test].sum())
    raw=bt.aggregate(d,'4h');c=json.loads((ROOT/'optimization/baseline/config.json').read_text());c['ichimoku_params'].update(zip(['tenkan','kijun','senkou_b','displacement'],(9,26,52,26)))
    f=shared.add_features(bt.prepare_indicators(raw,c))
    lo=int(np.searchsorted(raw.timestamp.to_numpy(),listed))+200
    for end in np.linspace(max(199,lo),len(raw)-2,6,dtype=int):   # parity with the live bot's indicator code, after listing
        actual=bot.indicators(raw.iloc[end-198:end+2][['timestamp','open','high','low','close','volume']].values.tolist(),c,'4h',(raw.iloc[end+1].timestamp+3000)/1000).iloc[-1]
        cols=['kijun','atr','kumo_top','kumo_bottom'];np.testing.assert_allclose(f.iloc[end][cols].astype(float),actual[cols].astype(float),rtol=1e-11,atol=1e-8)
    np.savez_compressed(dst/'4h_standard.npz',data=f.to_numpy(),columns=json.dumps(list(f.columns)))
    prices=d[d.timestamp>=bt.START][['open','high','low','close']].to_numpy();assert len(prices)==(bt.END-bt.START)//60000;np.save(dst/'prices.npy',prices)
    fund=np.full(len(prices),np.nan);ev=pd.concat([S.read_zip(S.CACHE/r) for r in files(sym,first) if 'fundingRate' in r and (S.CACHE/r).exists()],ignore_index=True)
    ts=ev.calc_time.astype(np.int64)//60000*60000;ix=((ts-bt.START)//60000).to_numpy();mask=(ix>=0)&(ix<len(fund));fund[ix[mask]]=ev.last_funding_rate.to_numpy()[mask]
    fund[:max(0,(listed-bt.START)//60000)]=0.;np.save(dst/'funding.npy',fund)
    info=dict(symbol=sym,minutes=len(prices),first_minute=listed,listed_min=int(max(0,(listed-bt.START)//60000)),missing_minutes_in_test=missing_test,
              funding_events=int(mask.sum()),parity_windows=6,padded=bool(listed>bt.START),prices_sha256=hashlib.sha256(prices.tobytes()).hexdigest())
    (dst/'manifest.json').write_text(json.dumps(info,indent=1));return info

def listed_min(sym):
    """Minute index (from rs.START) of the coin's first real Binance minute; 0 for coins listed before the test."""
    m=json.loads((S.PREP/sym/'manifest.json').read_text());return int(m.get('listed_min',0))

def main():
    syms,cov=universe()
    for s in MAIN5:
        link=S.PREP/s
        if not link.exists():link.symlink_to(ROOT/'high_cagr/prepared'/s,target_is_directory=True)
    todo=[s for s in syms if s not in MAIN5 and not (S.PREP/s/'manifest.json').exists()]
    rels=[r for s in todo for r in files(s,cov[s]['first'])];print('coins',len(syms),'to prepare',len(todo),'files',len(rels),flush=True)
    def fetch(rel):
        try:return S.fetch(rel)
        except Exception as exc:
            if 'fundingRate' in rel and '404' in str(exc):print('NO FUNDING FILE (funding 0 there)',rel,flush=True);return None
            raise
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        for k,_ in enumerate(pool.map(fetch,rels)):
            if k%300==0:print('verified',k,flush=True)
    for s in todo:
        info=prepare(s,cov[s]['first']);print('PREPARED',s,'listed',pd.Timestamp(info['first_minute'],unit='ms').date(),'missing',info['missing_minutes_in_test'],flush=True)
if __name__=='__main__':main()
