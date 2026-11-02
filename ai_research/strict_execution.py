"""Strict OHLC executable signal wrapper (independent of strategy logic).

If real 1m bars, current strategy signal, original STOP and TP are supplied,
rebuild labels/fills without the cached ledger approximation. No new strategy
signals are generated here. This is an adapter to feed exact walk-forward ML,
not a replacement for the existing three-bot 35-symbol shared-account engine.

Trading convention: signal at COMPLETED bar timestamp; enter NEXT bar open.
TP/SL on minute extremes thereafter; SL wins ambiguous same-minute touches.
Taker fee=0.0005 and slip=0.0002 EACH side. No hidden default funding: PERP
requires a time-aligned cumulative funding series, spot may supply zero.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FEE_PER_SIDE=.0005
SLIPPAGE_PER_SIDE=.0002

def trades_from_signals(bars:pd.DataFrame, signals:pd.DataFrame,
                        funding_cumulative:pd.Series|None=None,
                        instrument_type:str="perpetual") -> pd.DataFrame:
    """One open position per instrument; account sizing elsewhere.

    bars: UTC one-minute CLOSE timestamps and open/high/low/close columns.
    signals: columns timestamp, signal (+1/-1/0), stop_price, target_price,
             max_hold_bars. signal is copied; entry logic remains untouched.
    Funding series is the CUMULATIVE per-minute funding fraction at close,
    whose difference between entry and exit determines funding cost.
    """
    if instrument_type not in {"perpetual","spot"}:raise ValueError("Unknown instrument")
    if not isinstance(bars.index,pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("Bars need UTC-aware closing timestamps")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("Bars must be ordered and unique")
    if not {"open","high","low","close"}.issubset(bars):raise ValueError("Missing OHLC")
    if not {"timestamp","signal","stop_price","target_price","max_hold_bars"}.issubset(signals):
        raise ValueError("Signals must carry native stop/target/time-barrier")
    if instrument_type=="perpetual" and funding_cumulative is None:
        raise ValueError("Perpetual funding data required: no implicit free funding")
    funding=(funding_cumulative.reindex(bars.index) if funding_cumulative is not None
             else pd.Series(0.,index=bars.index))
    if funding.isna().any():raise ValueError("Funding does not cover all bars")
    signal=signals.copy()
    signal["timestamp"]=pd.to_datetime(signal.timestamp,utc=True)
    if not signal.signal.isin([-1,0,1]).all():raise ValueError("Invalid primary strategy signal")
    signal=signal[signal.signal!=0].sort_values("timestamp")
    records=[];next_allowed=0
    for row in signal.itertuples(index=False):
        ts=row.timestamp
        if ts not in bars.index:raise ValueError(f"Signal timestamp has no CLOSED source bar: {ts}")
        sigidx=int(bars.index.get_loc(ts))
        entryidx=sigidx+1
        if entryidx>=len(bars) or entryidx<next_allowed:continue
        side=int(row.signal);st=float(row.stop_price);tp=float(row.target_price)
        if not np.isfinite([st,tp]).all():raise ValueError("Nonfinite native barrier")
        op=float(bars.iloc[entryidx].open)
        entry=op*(1+side*SLIPPAGE_PER_SIDE)
        if not (st<entry<tp if side==1 else tp<entry<st):
            raise ValueError(f"Invalid original TP/SL ordering for signal at {ts}")
        limit=min(len(bars)-1,entryidx+int(row.max_hold_bars)-1)
        if limit<entryidx:raise ValueError("max_hold_bars must be positive")
        exitidx=limit;exit_kind="TIME";px=float(bars.iloc[limit].close)
        for i in range(entryidx,limit+1):
            b=bars.iloc[i]
            hit_stop=b.low<=st if side==1 else b.high>=st
            hit_tp=b.high>=tp if side==1 else b.low<=tp
            if hit_stop:
                px=min(float(b.open),st) if side==1 else max(float(b.open),st)
                exitidx=i;exit_kind="SL";break
            if hit_tp:
                px=tp;exitidx=i;exit_kind="TP";break
        exit_fill=px*(1-side*SLIPPAGE_PER_SIDE)
        gross=side*(exit_fill-entry)
        paid_fee=FEE_PER_SIDE*(entry+exit_fill)
        fund_cost=side*entry*(float(funding.iloc[exitidx])-float(funding.iloc[entryidx]))
        net=gross-paid_fee-fund_cost
        records.append({"signal_time":ts,"entry_time":bars.index[entryidx],
                        "exit_time":bars.index[exitidx],"signal":side,
                        "exit_cause":exit_kind,"entry_fill":entry,
                        "exit_fill":exit_fill,"native_stop":st,"native_target":tp,
                        "gross_pnl_per_unit":gross,"fees_per_unit":paid_fee,
                        "slip_per_side":SLIPPAGE_PER_SIDE,"funding_per_unit":fund_cost,
                        "net_pnl_per_unit":net,"native_risk_per_unit":abs(entry-st),
                        "net_r":net/abs(entry-st)})
        next_allowed=exitidx+1
    return pd.DataFrame(records)
