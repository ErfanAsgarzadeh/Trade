"""Deterministic, causal, scale-invariant OHLCV feature builder.

"timestamp" is the CLOSE/availability time of each completed base-timeframe bar.
Call at the signal-trigger time or earlier: never join later timestamps.
No labels, future return, cross-sectional global scaling, or fitted indicator.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

def _div(n,d):
    return n / d.replace(0.,np.nan)

def _rsi(close,n=14):
    delta=close.diff()
    up=delta.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    down=(-delta).clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=_div(up,down)
    return 100-100/(1+rs)

def make_features(bars:pd.DataFrame, higher_timeframe:str="1D")->pd.DataFrame:
    """At a completed bar t, uses nothing at t+1 onward.

    Bars index: UTC timezone-aware close timestamp, strictly increasing.
    Volume ROC and multi-TF alignment require source timeframe regularity.
    """
    if not isinstance(bars.index,pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("UTC timezone-aware DatetimeIndex of completed bar CLOSE times required")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("Bars must be time-ordered and unique")
    required=["open","high","low","close","volume"]
    if not set(required).issubset(bars):
        raise ValueError("Missing OHLCV")
    d=bars[required].astype(float)
    if (d[["open","high","low","close"]]<=0).any().any():
        raise ValueError("Invalid OHLC price")
    o,h,l,c,v=[d[x] for x in required]
    prev=c.shift(1)
    tr=pd.concat([h-l,(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    std20=c.rolling(20,min_periods=20).std()
    ret=np.log(c).diff()
    rng=(h-l).replace(0,np.nan)
    body=(c-o).abs()
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2
    kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    # Visible Kumo at t is projected 26 bars in the past, NOT future-shifted.
    span_a=((tenkan+kijun)/2).shift(26)
    span_b=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    swing_h=h.rolling(20,min_periods=20).max().shift(1)
    swing_l=l.rolling(20,min_periods=20).min().shift(1)
    rsi=_rsi(c)
    f=pd.DataFrame(index=d.index)
    f["atr_pct"]=_div(atr,c)
    f["bb_width"]=_div(4*std20,c.rolling(20).mean())
    f["logvol_10"]=ret.rolling(10,min_periods=10).std()
    f["logvol_30"]=ret.rolling(30,min_periods=30).std()
    f["body_to_range"]=_div(body,rng)
    f["wick_up"]=_div(h-pd.concat([o,c],axis=1).max(axis=1),rng)
    f["wick_down"]=_div(pd.concat([o,c],axis=1).min(axis=1)-l,rng)
    f["swing_hi_atr"]=_div(swing_h-c,atr)
    f["swing_lo_atr"]=_div(c-swing_l,atr)
    f["rsi14"]=rsi
    f["rsi_slope"]=rsi.diff(3)/3
    f["kijun_atr"]=_div(c-kijun,atr)
    f["tenkan_atr"]=_div(c-tenkan,atr)
    f["kumo_width_pct"]=_div((span_a-span_b).abs(),c)
    f["relative_volume"]=_div(v,v.rolling(20,min_periods=20).mean())
    f["volume_roc"]=v.pct_change(5).replace([np.inf,-np.inf],np.nan)
    f["momentum_6"]=ret.rolling(6).sum()
    f["logvol_60"]=ret.rolling(60).std()
    # Higher timeframe is only stamped once its bucket COMPLETES. Need the
    # input data at a regular frequency; 1D close at midnight is available then.
    htf=d.resample(higher_timeframe,closed="left",label="right").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    full=(htf.close>htf.close.ewm(span=50,adjust=False,min_periods=50).mean()).astype(float)
    # Resample may include final unfinished HTF bucket. Drop its last value:
    # close at bucket end is outside last available lower-TF close timestamp.
    full=full.loc[full.index<=d.index[-1]]
    f["htf_alignment"]=full.reindex(f.index,method="ffill").to_numpy()
    return f.replace([np.inf,-np.inf],np.nan)

def align_signals(signals:pd.DataFrame,bars:pd.DataFrame)->pd.DataFrame:
    """Only completed history known at each actual signal timestamp."""
    if not {"timestamp","signal"}.issubset(signals):
        raise ValueError("Need timestamp + signal")
    s=signals.copy()
    s["timestamp"]=pd.to_datetime(s.timestamp,utc=True)
    if not s.signal.isin([-1,0,1]).all():raise ValueError("Invalid base signals")
    f=make_features(bars)
    avail=f.reset_index().rename(columns={f.index.name or "index":"timestamp"})
    joined=pd.merge_asof(s.sort_values("timestamp"),avail.sort_values("timestamp"),
                         on="timestamp",direction="backward",allow_exact_matches=True)
    return joined
