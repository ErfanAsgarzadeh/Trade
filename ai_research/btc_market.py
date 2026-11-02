"""Second, independently named experiment: causal BTC market regime for ALL three bots.

Uses official historical 1m BTCUSDT USD-M futures archives already embedded in
the repository. Every market feature is from a COMPLETED 4h bar preceding entry.
The same frozen train/validation/AI test dates and same selection gates apply.
"""
from pathlib import Path
import glob
import json
import zipfile
import numpy as np
import pandas as pd
from . import experiment as ex

BTC_FIELDS=["btc_r1d","btc_r7d","btc_r30d","btc_vol7d",
            "btc_ema50_dist","btc_ema200_dist","btc_atr_pct","btc_range30d"]

def load_btc_4h(root=ex.ROOT):
    files=sorted(Path(root).glob("btc_backtest/cache/BTCUSDT-1m-*.zip"))
    if len(files)<55:
        raise FileNotFoundError("Requires restored 2021-2026 verified BTC 1m archives; run python restore_data.py")
    parts=[]
    for f in files:
        with zipfile.ZipFile(f) as z:
            with z.open(z.namelist()[0]) as source:
                a=pd.read_csv(source,header=None,usecols=[0,1,2,3,4],
                              names=["timestamp","open","high","low","close"],low_memory=False)
        a=a[pd.to_numeric(a.timestamp,errors="coerce").notna()].astype(float)
        if a.timestamp.max()>1e14:a["timestamp"]=a.timestamp/1000.
        parts.append(a)
    d=pd.concat(parts,ignore_index=True).sort_values("timestamp")
    if d.timestamp.duplicated().any():
        raise ValueError("Duplicated minute timestamps")
    tm=d.timestamp.to_numpy(np.int64)
    if not (np.diff(tm)==60000).all():
        bad=int(np.flatnonzero(np.diff(tm)!=60000)[0])
        raise ValueError(f"BTC minutes not continuous at {tm[bad]}; no fake filling")
    if (d[["open","high","low","close"]]<=0).any().any():
        raise ValueError("Nonpositive BTC historical prices")
    d.index=pd.to_datetime(tm,unit="ms",utc=True)
    bars=d.resample("4h",label="left",closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"})
    if bars.isna().any().any():raise ValueError("Incomplete BTC 4h bars")
    return bars

def completed_market_features(bars):
    c=bars.close
    ret=np.log(c).diff()
    pc=c.shift(1)
    tr=pd.concat([bars.high-bars.low, (bars.high-pc).abs(),(bars.low-pc).abs()],axis=1).max(axis=1)
    ema50=c.ewm(span=50,adjust=False).mean()
    ema200=c.ewm(span=200,adjust=False).mean()
    low=bars.low.rolling(180,min_periods=180).min()
    high=bars.high.rolling(180,min_periods=180).max()
    f=pd.DataFrame({
        "btc_r1d":c.pct_change(6),
        "btc_r7d":c.pct_change(42),
        "btc_r30d":c.pct_change(180),
        "btc_vol7d":ret.rolling(42,min_periods=42).std(),
        "btc_ema50_dist":c/ema50-1,
        "btc_ema200_dist":c/ema200-1,
        "btc_atr_pct":tr.ewm(alpha=1/14,adjust=False).mean()/c,
        "btc_range30d":(c-low)/(high-low).replace(0,np.nan)
    },index=bars.index)
    # A bar beginning at 08:00 is not known until 12:00; 08:00 entries
    # can only access the row BEFORE 08:00.
    return f.shift(1)

def join_at_entry(trades,features):
    idx=trades.when.dt.floor("4h")
    ff=features.reindex(pd.DatetimeIndex(idx),method="ffill")
    if ff.isna().any().any():
        # Only early warmup gaps are allowed, and not on the tested interval.
        bad=ff.isna().any(axis=1)
        if bad.sum()>0:raise ValueError(f"Unwarmed BTC market features on {bad.sum()} trades")
    result=trades.copy()
    for name in BTC_FIELDS:result[name]=ff[name].to_numpy(dtype=float)
    return result

def main():
    ex.OUT.mkdir(parents=True,exist_ok=True)
    x=ex.causal_features(ex.load_ledger())
    bars=load_btc_4h()
    x=join_at_entry(x,completed_market_features(bars))
    ex.NUMS.extend(BTC_FIELDS);ex.FIELDS.extend(BTC_FIELDS)
    r=ex.audit(x)
    # The code in audit uses the standard decision path; move that result.
    decision=ex.OUT/"all_2991_decisions.csv"
    if decision.exists():decision.rename(ex.OUT/"btc_market_decisions.csv")
    r["market_features"]=BTC_FIELDS
    r["market_source"]="verified official Binance USD-M 1m BTCUSDT archive resampled to closed 4h; shifted by one bar"
    r["limitations"].append("BTC macro context only: individual symbol microstructure/order book and funding predictors untested.")
    (ex.OUT/"btc_market_result.json").write_text(json.dumps(r,indent=2))
    print("BTC MARKET regime study",len(bars),"bars",r["selected"])
if __name__=="__main__":main()
