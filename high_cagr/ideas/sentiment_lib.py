"""Sentiment / positioning criteria on the 4h grid (causal: values known at the close of bar b).
Sources: taker buy volume share (Binance 1m klines, whole period), Binance futures metrics from Dec-2021 (open interest,
top-trader position long/short ratio, global account long/short ratio, taker long/short volume ratio; 5-min, value at or
before the bar close), Crypto Fear & Greed index (daily, value of the previous UTC day), total stablecoin supply (DefiLlama,
previous day). Missing values (before Dec-2021 for metrics) stay NaN and are filled with the TRAIN median by the studies.
"""
import sys,json,glob,zipfile,functools
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import criteria_lib as C
CACHE=ROOT/'high_cagr/cache_sentiment';BAR=240*60000
SENT_SIGNED=['tbr6','tbr_z','oi_price','ls_global','ls_global_z','ls_top','smart_vs_crowd','taker_ls6','fng','fng_chg7','stable_g30','mkt_oi_chg42']
SENT_UNSIGNED=['oi_chg6','oi_chg42','fng_extreme']
SENT=SENT_SIGNED+SENT_UNSIGNED
FAMILY={k:'sentiment' for k in SENT}

def kline_files(s):
    if s=='BTCUSDT':base=ROOT/'btc_backtest/cache';pats=[f'{s}-1m-*.zip']
    elif s in rs.SYMBOLS:base=ROOT/'portfolio/cache';pats=[f'{s}-1m-*.zip']
    else:base=ROOT/f'high_cagr/cache_stage2';pats=[f'monthly/klines/{s}/1m/*.zip',f'daily/klines/{s}/1m/*.zip']
    out=[]
    for p in pats:out+=sorted(glob.glob(str(base/p)))
    return out

@functools.lru_cache(None)
def taker(s):
    f=CACHE/f'taker_{s}.npy'
    if f.exists():return np.load(f)
    n=len(C.own(s)['trend50']);tb=np.zeros(n);vv=np.zeros(n)
    for z in kline_files(s):
        with zipfile.ZipFile(z) as zz:d=pd.read_csv(zz.open(zz.namelist()[0]),header=None,usecols=[0,5,9],names=['t','v','tb'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        b=((d.t.to_numpy()-rs.START)//BAR).astype(np.int64);m=(b>=0)&(b<n)
        np.add.at(tb,b[m],d.tb.to_numpy()[m]);np.add.at(vv,b[m],d.v.to_numpy()[m])
    out=np.vstack([tb,vv]);np.save(f,out);return out

@functools.lru_cache(None)
def metrics(s):
    f=CACHE/f'metrics4h_{s}.npy';n=len(C.own(s)['trend50'])
    if f.exists():return np.load(f)
    parts=[]
    for z in sorted(glob.glob(str(CACHE/'metrics'/s/'*.zip'))):
        try:
            with zipfile.ZipFile(z) as zz:parts.append(pd.read_csv(zz.open(zz.namelist()[0])))
        except Exception:pass
    out=np.full((6,n),np.nan)
    if parts:
        d=pd.concat(parts,ignore_index=True);t=pd.to_datetime(d.create_time).astype('int64')//10**6
        d=d.assign(t=t).sort_values('t').drop_duplicates('t')
        cols=['sum_open_interest','sum_open_interest_value','count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']
        closes=rs.START+(np.arange(n)+1)*BAR;ix=np.searchsorted(d.t.to_numpy(),closes,side='right')-1;ok=ix>=0
        for i,c in enumerate(cols):
            v=pd.to_numeric(d[c],errors='coerce').to_numpy();o=np.full(n,np.nan);o[ok]=v[ix[ok]]
            stale=np.full(n,True);stale[ok]=(closes[ok]-d.t.to_numpy()[ix[ok]])>6*3600*1000;o[stale]=np.nan;out[i]=o
    np.save(f,out);return out

@functools.lru_cache(1)
def daily_market():
    n=C.market()['n'];closes=rs.START+(np.arange(n)+1)*BAR
    fng=json.loads((CACHE/'fng.json').read_text())['data'];fd=pd.Series({int(x['timestamp'])*1000:float(x['value']) for x in fng}).sort_index()
    st=json.loads((CACHE/'stablecoins.json').read_text());sd=pd.Series({int(x['date'])*1000:float(x['totalCirculatingUSD']['peggedUSD']) for x in st}).sort_index()
    def asof(ser,lag_ms):   # value of the latest day that had ended (published) before the bar close
        ix=np.searchsorted(ser.index.to_numpy(),closes-lag_ms,side='right')-1;o=np.where(ix>=0,ser.to_numpy()[np.maximum(ix,0)],np.nan);return o
    f=asof(fd,86400000);s=asof(sd,86400000);sh=lambda x,k:np.concatenate([np.full(k,np.nan),x[:-k]])
    oiv=np.nansum([metrics(c)[1][:n] for c in C.COINS],axis=0);oiv[oiv==0]=np.nan
    return dict(fng=f,fng_chg7=f-sh(f,42),stable_g30=s/sh(s,180)-1,mkt_oi_chg42=oiv/sh(oiv,42)-1)

@functools.lru_cache(None)
def own(s):
    n=len(C.own(s)['trend50']);tb,vv=taker(s);m=metrics(s);sh=lambda x,k:np.concatenate([np.full(k,np.nan),x[:-k]]);r={}
    ratio=np.where(vv>0,tb/np.maximum(vv,1e-12),np.nan)
    r['tbr6']=pd.Series(tb).rolling(6).sum().to_numpy()/np.maximum(pd.Series(vv).rolling(6).sum().to_numpy(),1e-12)-.5
    mu=pd.Series(ratio).rolling(60).mean().to_numpy();sd=pd.Series(ratio).rolling(60).std().to_numpy();r['tbr_z']=(ratio-mu)/(sd+1e-12)
    oi=m[0];r['oi_chg6']=oi/sh(oi,6)-1;r['oi_chg42']=oi/sh(oi,42)-1;ret6=C.own(s)['ret5']
    r['oi_price']=np.sign(C.own(s)['ret5'])*r['oi_chg6']
    lg=np.log(m[4]);r['ls_global']=lg;r['ls_global_z']=(lg-pd.Series(lg).rolling(180,min_periods=60).mean().to_numpy())/(pd.Series(lg).rolling(180,min_periods=60).std().to_numpy()+1e-12)
    lt=np.log(m[3]);r['ls_top']=lt;r['smart_vs_crowd']=lt-lg;r['taker_ls6']=pd.Series(np.log(m[5])).rolling(6,min_periods=3).mean().to_numpy()
    return r

def at(coin,b,side):
    o=own(coin);d=daily_market();s=side;r={}
    for k in ('tbr6','tbr_z','oi_price','ls_global','ls_global_z','ls_top','smart_vs_crowd','taker_ls6'):r[k]=s*o[k][b]
    for k in ('oi_chg6','oi_chg42'):r[k]=o[k][b]
    f=d['fng'][b] if b<len(d['fng']) else np.nan;r['fng']=s*(f-50)/50;r['fng_extreme']=abs(f-50)/50
    r['fng_chg7']=s*(d['fng_chg7'][b] if b<len(d['fng']) else np.nan)/50;r['stable_g30']=s*(d['stable_g30'][b] if b<len(d['fng']) else np.nan)
    r['mkt_oi_chg42']=s*(d['mkt_oi_chg42'][b] if b<len(d['fng']) else np.nan);return r
