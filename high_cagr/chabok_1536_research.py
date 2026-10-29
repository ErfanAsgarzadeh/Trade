"""Search 1536 causal technical strategies for the experimental Chabok paper sleeve.

1536 = 6 entry families x 4 HTF filters x 4 entry variants x
       4 ATR stops x 2 exit styles x 2 time stops.
NO live trading or production changes.
DATA: BTC/ETH Binance USDT-M 15m + 1h + funding, 2021-01..2026-09.
TRAIN: 2021-2023; VALIDATE: 2024; TEST LOCKED: 2025..2026-09.
The locked test is evaluated for ONLY the single candidate chosen without
looking at test returns. No claim of LBank execution parity.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys
from pathlib import Path

import numba as nb
import numpy as np
import pandas as pd

from chabok_historical_backtest import load_historical, SYMBOLS

HERE = Path(__file__).resolve().parent
BAR_MINUTES = int(os.getenv("CHABOK_BAR_MINUTES", "15"))
if BAR_MINUTES not in (15, 30, 60):
    raise ValueError("Research supports 15m, 30m or 1h entries")
BAR_MS = BAR_MINUTES * 60000
OUT = HERE / "output" / ("chabok_sweep_1536" if BAR_MINUTES == 15 else f"chabok_sweep_1536_{BAR_MINUTES}m")
OUT.mkdir(parents=True, exist_ok=True)
FAMILIES = ("donchian", "kumo_cloud", "ema_pullback", "bollinger_reversion",
            "rsi_momentum", "macd_crossover")
REGIMES = ("none", "htf_ema", "htf_cloud", "htf_ema_cloud_adx")
STOP_CHOICES = (1.5, 2.0, 3.0, 4.0)
EXIT_CHOICES = ("target_2R", "atr_trailing")
HOLD_CHOICES = (32, 96)
FEE = 0.0006
SLIP = 0.0002


def atr_rsi(a):
    c, h, l = a.close, a.high, a.low
    tr = pd.concat((h-l, (h-c.shift()).abs(), (l-c.shift()).abs()),axis=1).max(axis=1)
    a["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    delta = c.diff().fillna(0.)
    up = delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    a["rsi"] = 100 - 100/(1+up/down.where(down>0,1e-12))
    return a


def cloud(a):
    """Ichimoku current-cloud values: spans are displaced +26 in charting,
    so using lag(26) is essential; never use forward-shifted information."""
    t = (a.high.rolling(9).max()+a.low.rolling(9).min())/2
    k = (a.high.rolling(26).max()+a.low.rolling(26).min())/2
    span_a = ((t+k)/2).shift(26)
    span_b = ((a.high.rolling(52).max()+a.low.rolling(52).min())/2).shift(26)
    return t,k,span_a,span_b


def adx14(a):
    high, low, close = a.high, a.low, a.close
    plus = high.diff()
    minus = -low.diff()
    dp = pd.Series(np.where((plus>minus)&(plus>0),plus,0.),index=a.index)
    dm = pd.Series(np.where((minus>plus)&(minus>0),minus,0.),index=a.index)
    tr = pd.concat((high-low,(high-close.shift()).abs(),(low-close.shift()).abs()),axis=1).max(axis=1)
    smooth = tr.ewm(alpha=1/14,adjust=False).mean()
    pdi = 100*dp.ewm(alpha=1/14,adjust=False).mean()/smooth.where(smooth>0)
    mdi = 100*dm.ewm(alpha=1/14,adjust=False).mean()/smooth.where(smooth>0)
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).where((pdi+mdi)>0)
    return dx.fillna(0).ewm(alpha=1/14,adjust=False).mean()


def feature_data(raw):
    prepared={}
    stamps=None
    for sym in SYMBOLS:
        a=raw[(sym,"kline","15m")].copy()
        h=raw[(sym,"kline","1h")].copy()
        if BAR_MINUTES in (30, 60):
            # Aggregate only fully completed, contiguous source 15m candles.
            a = a.groupby(a.ts // BAR_MS, sort=True).agg(
                {"ts":"first","open":"first","high":"max","low":"min",
                 "close":"last","volume":"sum"}
            ).reset_index(drop=True)
            if (np.diff(a.ts.to_numpy(dtype=np.int64)) != BAR_MS).any():
                raise RuntimeError("Aggregated candles not contiguous")
        if BAR_MINUTES == 60:
            # True 4-hour HTF gating for 1h entry, built from contiguous 1h sources.
            h=h.groupby(h.ts // (4*3600000),sort=True).agg(
                {"ts":"first","open":"first","high":"max","low":"min",
                 "close":"last","volume":"sum"}
            ).reset_index(drop=True)
            if (np.diff(h.ts.to_numpy(dtype=np.int64)) != 4*3600000).any():
                raise RuntimeError("4h trend candle gaps")
        assert len(a)>(24000 if BAR_MINUTES == 60 else 90000) and len(h)>(11000 if BAR_MINUTES == 60 else 50000)
        a=atr_rsi(a)
        a["adx"]=adx14(a)
        for n in (10,20,30,50):
            a[f"ema{n}"]=a.close.ewm(span=n,adjust=False).mean()
        for n in (20,30,50,80):
            a[f"hi{n}"]=a.high.shift(1).rolling(n).max()
            a[f"lo{n}"]=a.low.shift(1).rolling(n).min()
        for n in (20,30,40,60):
            mid=a.close.rolling(n).mean()
            std=a.close.rolling(n).std()
            a[f"bblo{n}"]=mid-2*std
            a[f"bbhi{n}"]=mid+2*std
        t,k,sa,sb=cloud(a)
        a["tenkan"]=t
        a["kijun"]=k
        a["sa"]=sa
        a["sb"]=sb
        for fast,slow,signal in ((8,17,9),(12,26,9),(16,35,9),(24,52,18)):
            macd=a.close.ewm(span=fast,adjust=False).mean()-a.close.ewm(span=slow,adjust=False).mean()
            a[f"hist{fast}"]=macd-macd.ewm(span=signal,adjust=False).mean()
        h["ema50"]=h.close.ewm(span=50,adjust=False).mean()
        h["ema200"]=h.close.ewm(span=200,adjust=False).mean()
        _,_,hsa,hsb=cloud(h)
        h["sa"]=hsa
        h["sb"]=hsb
        h["hidx"]=np.arange(len(h))
        h["decision_ts"]=h.ts+(4*3600000 if BAR_MINUTES == 60 else 3600000)
        a["decision_ts"]=a.ts+BAR_MS
        a=pd.merge_asof(
            a.sort_values("decision_ts"),
            h[["decision_ts","close","ema50","ema200","sa","sb","hidx"]]
            .rename(columns={"close":"hclose","ema50":"hema50","ema200":"hema200","sa":"hsa","sb":"hsb"}),
            on="decision_ts",direction="backward",
        )
        if stamps is None:stamps=a.ts.to_numpy(dtype=np.int64)
        elif not np.array_equal(stamps,a.ts.to_numpy(dtype=np.int64)):
            raise RuntimeError("BTC/ETH timestamp mismatch")
        warm=(np.arange(len(a))>=350)&(a.hidx>=350)
        a["warm"]=warm
        prepared[sym]=a
        print(f"FEATURES_READY {sym} bars={len(a)}",flush=True)
    return prepared, stamps


def signals(frame,family,regime,variant):
    a=frame
    c=a.close
    prev=c.shift(1)
    atr=a.atr
    warm=a.warm
    h_ema_long=(a.hema50>a.hema200)&(a.hclose>a.hema50)
    h_ema_short=(a.hema50<a.hema200)&(a.hclose<a.hema50)
    h_cloud_long=(a.hclose>a.hsa)&(a.hclose>a.hsb)&(a.hsa>a.hsb)
    h_cloud_short=(a.hclose<a.hsa)&(a.hclose<a.hsb)&(a.hsa<a.hsb)
    if regime==0:
        regime_long=regime_short=True
    elif regime==1:
        regime_long,regime_short=h_ema_long,h_ema_short
    elif regime==2:
        regime_long,regime_short=h_cloud_long,h_cloud_short
    else:
        regime_long=h_ema_long&h_cloud_long&(a.adx>=20)
        regime_short=h_ema_short&h_cloud_short&(a.adx>=20)

    if family==0:  # price-structure breakout above prior Donchian range
        n=(20,30,50,80)[variant]
        long=(c>a[f"hi{n}"])&(c>a.ema20)&a.rsi.between(53,78)
        short=(c<a[f"lo{n}"])&(c<a.ema20)&a.rsi.between(22,47)
    elif family==1:  # displaced Ichimoku cloud break, Tenkan/Kijun agreement
        buffer=(0.,0.1,0.2,0.3)[variant]
        upper=np.maximum(a.sa,a.sb)
        lower=np.minimum(a.sa,a.sb)
        prev_upper=upper.shift()
        prev_lower=lower.shift()
        long=(prev<=prev_upper)&(c>upper+buffer*atr)&(a.tenkan>a.kijun)
        short=(prev>=prev_lower)&(c<lower-buffer*atr)&(a.tenkan<a.kijun)
    elif family==2:  # EMA crossback after pullback, higher-level trend
        n=(10,20,30,50)[variant]
        ema=a[f"ema{n}"]
        long=(prev<=ema.shift())&(c>ema)&(a.ema20>a.ema50)&(a.rsi>51)
        short=(prev>=ema.shift())&(c<ema)&(a.ema20<a.ema50)&(a.rsi<49)
    elif family==3:  # Bollinger lower/upper-band rejection / mean reversion
        n=(20,30,40,60)[variant]
        lower=a[f"bblo{n}"]
        upper=a[f"bbhi{n}"]
        long=(prev<lower.shift())&(c>lower)&(a.rsi<49)
        short=(prev>upper.shift())&(c<upper)&(a.rsi>51)
    elif family==4:  # threshold RSI momentum cross with MACD sign
        threshold=(52,55,58,62)[variant]
        long=(a.rsi.shift()<=threshold)&(a.rsi>threshold)&(a.ema20>a.ema50)&(a.hist12>0)
        short=(a.rsi.shift()>=100-threshold)&(a.rsi<100-threshold)&(a.ema20<a.ema50)&(a.hist12<0)
    else:  # MACD histogram zero-cross, 4 MACD parameterizations
        n=(8,12,16,24)[variant]
        hist=a[f"hist{n}"]
        long=(hist.shift()<=0)&(hist>0)&(a.ema20>a.ema50)&(a.rsi>50)
        short=(hist.shift()>=0)&(hist<0)&(a.ema20<a.ema50)&(a.rsi<50)

    vol_ok=(a.atr/a.close>=0.0015)
    le=np.asarray(warm & vol_ok & regime_long & long, dtype=np.bool_)
    se=np.asarray(warm & vol_ok & regime_short & short, dtype=np.bool_)
    s=np.where(le,1,np.where(se,-1,0)).astype(np.int8)
    return s


@nb.njit(cache=True)
def replay(opens,highs,lows,closes,atrs,fund,signal_values,ts,start,end,
           stop_multiple,exit_style,hold_bars,slippage):
    """Two-asset synchronous paper replay with capped risk and daily drawdown gate.

    Entry is next-candle open; order stop/target evaluated within bar using
    adversarial STOP-FIRST if both were visited. Funding settlements are exact
    timestamps matching 15m bar close. No intrabar stop trailing with lookahead.
    """
    cash=10000.
    sides=np.zeros(2,np.int8)
    qty=np.zeros(2,np.float64)
    entry=np.zeros(2,np.float64)
    stop=np.zeros(2,np.float64)
    take=np.zeros(2,np.float64)
    best=np.zeros(2,np.float64)
    signal_bar=np.zeros(2,np.int64)
    entryfee=np.zeros(2,np.float64)
    f_paid=np.zeros(2,np.float64)
    marks=np.zeros(2,np.float64)
    trades=0;wins=0;gprof=0.;gloss=0.;fees=0.;slipcost=0.;fundnet=0.
    stopex=0;takeex=0;timeex=0
    peak=cash;maxdd=0.; margin_sum=0.;margin_peak=0.; margin_ticks=0
    day=-1;daily_realized=0.
    for i in range(start,end):
        thisday=ts[i]//86400000
        if thisday!=day:
            day=thisday
            daily_realized=0.
        for j in range(2):
            marks[j]=opens[j,i]
        for j in range(2):
            if sides[j]!=0 or i==start:
                continue
            direction=signal_values[j,i-1]
            if direction==0:
                continue
            eq=cash
            npos=0
            used=0.
            for k in range(2):
                if sides[k]!=0:
                    npos+=1
                    eq+=sides[k]*qty[k]*(marks[k]-entry[k])-FEE*qty[k]*marks[k]
                    used+=qty[k]*entry[k]/5.
            if npos>=2 or eq<=0 or daily_realized<=-.005*eq:
                continue
            px=opens[j,i]
            atr=atrs[j,i-1]
            if atr<=0 or abs(px-closes[j,i-1])>0.5*atr:
                continue
            fill=px*(1+direction*slippage)
            distance=max(stop_multiple*atr,.006*fill)
            desired_notional=eq*.0015/(distance/fill+2*FEE+2*slippage)
            allowed=max(0.,eq*.8-used)
            notional=min(desired_notional,eq*.25,allowed/(1+0.8*5*2*FEE)*5)
            if notional<20 or distance/fill>0.20 or fill-distance<=0:
                continue
            q=notional/fill
            sides[j]=direction
            qty[j]=q;entry[j]=fill
            stop[j]=fill-direction*distance
            take[j]=fill+direction*2*distance
            best[j]=closes[j,i-1]
            signal_bar[j]=i-1
            entryfee[j]=FEE*q*fill
            f_paid[j]=0.
            cash-=entryfee[j]
            fees+=entryfee[j]
            slipcost+=abs(fill-px)*q
        for j in range(2):
            marks[j]=closes[j,i]
            if sides[j]==0:
                continue
            direction=sides[j]
            px=0.
            reason=0
            if (direction==1 and lows[j,i]<=stop[j]) or (direction==-1 and highs[j,i]>=stop[j]):
                px=min(stop[j],opens[j,i]) if direction==1 else max(stop[j],opens[j,i])
                reason=1
            elif exit_style==0 and ((direction==1 and highs[j,i]>=take[j]) or
                                    (direction==-1 and lows[j,i]<=take[j])):
                px=take[j]
                reason=2
            elif i-signal_bar[j]>=hold_bars:
                px=closes[j,i]
                reason=3
            if reason!=0:
                executed=px*(1-direction*slippage)
                exitfee=FEE*qty[j]*executed
                pnl=direction*qty[j]*(executed-entry[j])-entryfee[j]-exitfee+f_paid[j]
                cash+=direction*qty[j]*(executed-entry[j])-exitfee
                daily_realized+=pnl
                fees+=exitfee
                slipcost+=abs(executed-px)*qty[j]
                trades+=1
                if pnl>0:
                    wins+=1;gprof+=pnl
                elif pnl<0:
                    gloss-=pnl
                if reason==1:stopex+=1
                elif reason==2:takeex+=1
                else:timeex+=1
                sides[j]=0;qty[j]=0.
                continue
            # Historical funding settlement timestamp is the current bar close.
            rate=fund[j,i]
            if rate!=0:
                cash_delta=-direction*qty[j]*closes[j,i]*rate
                cash+=cash_delta
                f_paid[j]+=cash_delta
                fundnet+=cash_delta
            if exit_style==1:
                if direction==1:
                    best[j]=max(best[j],closes[j,i])
                    stop[j]=max(stop[j],best[j]-2.5*atrs[j,i])
                else:
                    best[j]=min(best[j],closes[j,i])
                    stop[j]=min(stop[j],best[j]+2.5*atrs[j,i])
        eq=cash
        used=0.
        for j in range(2):
            if sides[j]!=0:
                eq+=sides[j]*qty[j]*(marks[j]-entry[j])-FEE*qty[j]*marks[j]
                used+=qty[j]*entry[j]/5.
        if eq>peak:peak=eq
        if peak>0:maxdd=max(maxdd,(peak-eq)/peak)
        if eq>0:
            m=used/eq
            margin_sum+=m
            margin_peak=max(margin_peak,m)
            margin_ticks+=1
    final=cash
    for j in range(2):
        if sides[j]!=0:
            final+=sides[j]*qty[j]*(closes[j,end-1]-entry[j])-FEE*qty[j]*closes[j,end-1]
    return (final,maxdd,trades,wins,gprof,gloss,fees,slipcost,fundnet,
            stopex,takeex,timeex,margin_sum/max(1,margin_ticks),margin_peak)


def make_arrays(raw,prepared,ts):
    matrix={}
    for c in ("open","high","low","close","atr"):
        matrix[c]=np.ascontiguousarray(np.stack(
            [prepared[s][c].to_numpy(dtype=np.float64) for s in SYMBOLS]))
    fund=[]
    for sym in SYMBOLS:
        src=raw[(sym,"funding","")]
        times=src.ts.to_numpy(dtype=np.int64)
        rates=src.rate.to_numpy(dtype=np.float64)
        if len(times)==0:
            raise RuntimeError("Funding must exist: "+sym)
        # Unlike a casual shortcut, funding print must not be shifted to earlier bars.
        indexed=np.searchsorted(times,ts+BAR_MS,side="left")
        values=np.zeros(len(ts),dtype=np.float64)
        mask=indexed<len(times)
        mask[mask]=times[indexed[mask]]==ts[mask]+BAR_MS
        values[mask]=rates[indexed[mask]]
        fund.append(values)
    matrix["fund"]=np.ascontiguousarray(np.stack(fund))
    return matrix


def stats(metrics, years):
    final,dd,n,w,profit,loss,fees,slip,fund,stop,tp,timeout,avgmargin,maxmargin=metrics
    pf=profit/loss if loss>0 else 0.
    cagr=100*(max(final,0.00001)/10000)**(1/years)-100.
    return dict(
        final_equity=round(float(final),2),
        net_return_pct=round(float((final/10000-1)*100),3),
        cagr_pct=round(float(cagr),3),
        max_dd_pct=round(float(dd*100),3),
        trades=int(n), win_rate_pct=round(float(100*w/n),3) if n else 0.,
        profit_factor=round(float(pf),4),
        fees_usd=round(float(fees),2),slippage_usd=round(float(slip),2),
        funding_usd=round(float(fund),2),
        stop_exits=int(stop),target_exits=int(tp),time_exits=int(timeout),
        avg_margin_pct=round(float(avgmargin*100),3),
        max_margin_pct=round(float(maxmargin*100),3),
    )


def date_index(ts, day):
    return int(np.searchsorted(ts,int(pd.Timestamp(day,tz="UTC").timestamp()*1000)))


def main():
    print(f"RESEARCH_START 1536 fixed candidates, timeframe={BAR_MINUTES}m, OOS locked 2025-2026",flush=True)
    raw,misses=load_historical()
    if misses:
        raise RuntimeError(f"Missing any required funding or candle archive: {misses[:5]}")
    prepared,ts=feature_data(raw)
    matrices=make_arrays(raw,prepared,ts)
    train=(0,date_index(ts,"2024-01-01"))
    valid=(train[1],date_index(ts,"2025-01-01"))
    locked=(valid[1],len(ts))
    if not (train[1]>(25000 if BAR_MINUTES == 60 else 50000)
            and valid[1]-valid[0]>(8000 if BAR_MINUTES == 60 else 15000)
            and locked[1]-locked[0]>(15000 if BAR_MINUTES == 60 else 30000)):
        raise RuntimeError("Split not as expected")
    starts={"train":str(pd.to_datetime(ts[0],unit="ms",utc=True)),
            "valid":str(pd.to_datetime(ts[valid[0]],unit="ms",utc=True)),
            "locked_test":str(pd.to_datetime(ts[locked[0]],unit="ms",utc=True))}
    print("SPLITS "+json.dumps(dict(starts=starts,ends=[
        str(pd.to_datetime(ts[x[1]-1]+BAR_MS,unit="ms",utc=True)) for x in (train,valid,locked)
    ])),flush=True)
    years_train=(ts[train[1]-1]-ts[train[0]])/86400000/365.25
    years_valid=(ts[valid[1]-1]-ts[valid[0]])/86400000/365.25
    years_test=(ts[locked[1]-1]-ts[locked[0]])/86400000/365.25
    call=lambda ss,interval,sm,style,hold,slip: replay(
        matrices["open"],matrices["high"],matrices["low"],matrices["close"],
        matrices["atr"],matrices["fund"],ss,ts,
        interval[0],interval[1],sm,style,hold,slip)
    records=[]
    signal_counts={}
    for family,regime,variant in itertools.product(range(6),range(4),range(4)):
        sig=np.ascontiguousarray(np.stack([
            signals(prepared[s],family,regime,variant) for s in SYMBOLS
        ]))
        signal_counts[f"{family}-{regime}-{variant}"]=[
            int(np.count_nonzero(sig[:,train[0]:train[1]])),
            int(np.count_nonzero(sig[:,valid[0]:valid[1]])),
        ]
        for sm,style,hold in itertools.product(STOP_CHOICES,range(2),HOLD_CHOICES):
            tr=stats(call(sig,train,sm,style,hold,SLIP),years_train)
            va=stats(call(sig,valid,sm,style,hold,SLIP),years_valid)
            row=dict(family=FAMILIES[family],family_id=family,regime=REGIMES[regime],
                     regime_id=regime,variant=variant,stop_atr=sm,
                     exit_style=EXIT_CHOICES[style],exit_id=style,hold_bars=hold,
                     train=tr,validation=va)
            # Conservative gates are fixed before observing locked OOS results.
            row["eligible"]=bool(
                tr["trades"]>=80 and va["trades"]>=20 and
                tr["cagr_pct"]>4 and va["cagr_pct"]>2 and
                tr["profit_factor"]>=1.05 and va["profit_factor"]>=1.05 and
                tr["max_dd_pct"]<30 and va["max_dd_pct"]<25
            )
            row["score"]=round(
                min(tr["cagr_pct"],va["cagr_pct"])-0.4*max(
                    tr["max_dd_pct"],va["max_dd_pct"]),4)
            records.append(row)
        if len(records)%256==0:
            viable=sum(int(x["eligible"]) for x in records)
            print(f"SEARCH_PROGRESS {len(records)}/1536 eligible={viable}",flush=True)
    if len(records)!=1536:
        raise AssertionError(f"Distinct grid size mismatch: {len(records)}")
    print("GRID_COMPLETE candidates=1536",flush=True)
    eligible=[r for r in records if r["eligible"]]
    sorted_candidates=sorted(eligible,key=lambda r:r["score"],reverse=True)
    # Transparent diagnostics: never touch the locked test for unsuccessful rows.
    top_unfiltered=sorted(records,key=lambda r:r["score"],reverse=True)[:10]
    diagnostic={
        "train_positive_cagr":sum(r["train"]["cagr_pct"]>0 for r in records),
        "validation_positive_cagr":sum(r["validation"]["cagr_pct"]>0 for r in records),
        "positive_both":sum(r["train"]["cagr_pct"]>0 and r["validation"]["cagr_pct"]>0 for r in records),
        "min_trades_both":sum(r["train"]["trades"]>=80 and r["validation"]["trades"]>=20 for r in records),
        "pf_above_one_both":sum(r["train"]["profit_factor"]>=1.05 and r["validation"]["profit_factor"]>=1.05 for r in records),
        "best_score_even_if_rejected":top_unfiltered,
        "family":{}
    }
    for f in FAMILIES:
        rows=[r for r in records if r["family"]==f]
        diagnostic["family"][f]={
            "positive_train":sum(r["train"]["cagr_pct"]>0 for r in rows),
            "positive_validation":sum(r["validation"]["cagr_pct"]>0 for r in rows),
            "positive_both":sum(r["train"]["cagr_pct"]>0 and r["validation"]["cagr_pct"]>0 for r in rows),
            "top_training_cagr":max(r["train"]["cagr_pct"] for r in rows),
            "top_validation_cagr":max(r["validation"]["cagr_pct"] for r in rows),
            "best_common_score":max(r["score"] for r in rows),
        }
    print("DIAGNOSTIC_JSON "+json.dumps({
        k:v for k,v in diagnostic.items() if k!="best_score_even_if_rejected"
    }),flush=True)
    print("TOP_REJECTED_CANDIDATES "+json.dumps(top_unfiltered[:5]),flush=True)
    status="train_validation_pass" if eligible else "NO_TRAIN_VALIDATION_PASS"
    winner=sorted_candidates[0] if eligible else None
    test=None
    stress=None
    gate="NO_DEPLOY"
    if winner is not None:
        family,regime,variant=winner["family_id"],winner["regime_id"],winner["variant"]
        sig=np.ascontiguousarray(np.stack([
            signals(prepared[s],family,regime,variant) for s in SYMBOLS
        ]))
        sm=winner["stop_atr"]
        style=winner["exit_id"]
        hold=winner["hold_bars"]
        # LOCKED TEST EVALUATED ONCE; never modify candidate choice after this.
        test=stats(call(sig,locked,sm,style,hold,SLIP),years_test)
        stress=stats(call(sig,locked,sm,style,hold,0.0004),years_test)
        if (test["cagr_pct"]>5 and test["profit_factor"]>1.1 and
            test["trades"]>=50 and test["max_dd_pct"]<25 and
            stress["cagr_pct"]>0 and stress["profit_factor"]>1.0):
            gate="OOS_METRIC_PASS_REQUIRES_1M_LBANK_REPLAY_AND_PAPER"
        print("SELECTED_LOCKED_TEST "+json.dumps(dict(winner=winner,test=test,stress=stress,gate=gate)),flush=True)
    else:
        print("NO_CANDIDATE_MET_PRECOMMITTED_TRAIN_VALIDATION_GATES",flush=True)

    result=dict(
        experiment=f"chabok-1536-indicator-technical-kumo-sweep-{BAR_MINUTES}m-v1",
        entry_timeframe_minutes=BAR_MINUTES,
        source="Binance USDT-M actual 15m/1h kline/funding monthly archives, not LBank",
        candidates_tested=len(records),successful_train_validation=len(eligible),
        families=list(FAMILIES),regimes=list(REGIMES),
        htf_timeframe_hours=4 if BAR_MINUTES == 60 else 1,
        periods=dict(train="2021-01-01 to 2023-12-31",
                     validation="2024-01-01 to 2024-12-31",
                     locked_test="2025-01-01 to 2026-09-30"),
        initial_equity_usd=10000, fee_per_side_pct=0.06,
        slippage_per_side_bps=2,
        stop_first_if_target_and_stop_same_bar=True,
        funding_archive_missing_months=len(misses),
        eligibility_gates=dict(train_min_trades=80,validation_min_trades=20,
          train_cagr_gt=4,validation_cagr_gt=2,
          min_pf=1.05,train_dd_lt=30,valid_dd_lt=25),
        selection_method="max(min(train_CAGR,validation_CAGR)-0.4*max(train_DD,validation_DD)); locked test evaluated only for first chosen eligible candidate",
        status=status, recommendation=gate,diagnostics=diagnostic,selected=winner,
        locked_test_metrics=test,locked_test_slippage_4bps_per_side=stress,
        top_20_train_validation=sorted_candidates[:20],
        caveats=[
            "1000+ combinations amplify data-snooping risk even when locked test is respected",
            f"{BAR_MINUTES}m high/low adverse stop-first policy, not 1m tick-level exits",
            "No LBank fill, exchange precision, depth, dynamic spread or liquidations",
            "Combined account with Shahin/Mojsavar/Ghoghnous not simulated",
            "Candidate family is not automatically deployed; review required",
            "PAPER trades use 10-second quote sampled LBank candles not native Binance OHLCV"
        ]
    )
    (OUT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    with (OUT/"all_candidates.jsonl").open("w") as f:
        for r in records:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    pd.DataFrame([{
        "family":r["family"],"regime":r["regime"],"variant":r["variant"],
        "stop_atr":r["stop_atr"],"exit_style":r["exit_style"],"hold_bars":r["hold_bars"],
        "eligible":r["eligible"],"score":r["score"],
        **{f"train_{k}":v for k,v in r["train"].items()},
        **{f"valid_{k}":v for k,v in r["validation"].items()}
    } for r in records]).to_csv(OUT/"all_candidates.csv",index=False)
    print("SEARCH_RESULT_JSON "+json.dumps({k:result[k] for k in (
        "candidates_tested","successful_train_validation","status","recommendation",
        "selected","locked_test_metrics","locked_test_slippage_4bps_per_side"
    )},ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    sys.exit(main())
