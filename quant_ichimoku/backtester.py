"""Standalone M15/H4 Quant Ichimoku strategy; research-only, no exchange execution.

Signals use CLOSED M15 and H4 bars; entries and signal-driven exits fill
at the NEXT M15 open. Protective stop and TP1 are simulated intrabar with
stop-first priority if their order is unknowable from OHLC.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Settings:
    initial_capital: float = 1000.0
    risk_per_trade: float = 0.015
    fee_per_fill: float = 0.0006  # 0.12% nominal round trip
    slippage_per_fill: float = 0.0002
    leverage: float = 5.0
    margin_cap: float = 0.80
    min_stop_pct: float = 0.004  # original strategy's 0.4% threshold
    start: str = "2021-10-05"
    end: str = "2026-10-05"  # exclusive


def midpoint(high, low, window):
    return (high.rolling(window, min_periods=window).max()
            + low.rolling(window, min_periods=window).min()) / 2.0


def rsi(close, period=14):
    d = close.diff(); up = d.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    value = 100 - 100/(1 + up / down.replace(0, np.nan))
    return value.where(down != 0, 100.0).where((down != 0) | (up != 0), 50.0)


def atr(d, period=14):
    prev = d.close.shift(1)
    tr = pd.concat([d.high-d.low, (d.high-prev).abs(), (d.low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()


def adx(d, period=14):
    up = d.high.diff(); down = -d.low.diff()
    pdm = up.where((up > down) & (up > 0), 0.0)
    mdm = down.where((down > up) & (down > 0), 0.0)
    avtr = atr(d,period)
    plus = 100 * pdm.ewm(alpha=1/period, adjust=False, min_periods=period).mean()/avtr
    minus = 100 * mdm.ewm(alpha=1/period, adjust=False, min_periods=period).mean()/avtr
    dx = 100*(plus-minus).abs()/(plus+minus).replace(0, np.nan)
    return dx.ewm(alpha=1/period,adjust=False,min_periods=period).mean()


def validate_frame(d):
    if not isinstance(d.index, pd.DatetimeIndex) or d.index.tz is None:
        raise ValueError("OHLCV requires a timezone-aware UTC DatetimeIndex of M15 OPEN times")
    if str(d.index.tz) != "UTC":
        raise ValueError("DatetimeIndex must use UTC")
    if len(d)<1200 or not d.index.is_unique or not d.index.is_monotonic_increasing:
        raise ValueError("At least 1200 ordered, unique candles required")
    if (d.index.minute % 15 != 0).any() or (d.index.second != 0).any():
        raise ValueError("M15 candle open timestamps must align to UTC 15min boundaries")
    if not d.index.to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=15)).all():
        raise ValueError("Missing or non-contiguous 15-minute candles: do not forward-fill prices")
    required=['open','high','low','close','volume']
    if any(c not in d for c in required):
        raise ValueError("Missing OHLCV columns")
    a=d[required]
    if a.isna().any().any() or not np.isfinite(a.to_numpy(dtype=float)).all():
        raise ValueError("Invalid finite OHLCV values")
    if (a[['open','high','low','close']]<=0).any().any() or (a.volume<0).any():
        raise ValueError("Prices must be positive and volume nonnegative")
    if (a.high<a[['open','close','low']].max(axis=1)).any() or (a.low>a[['open','close','high']].min(axis=1)).any():
        raise ValueError("Invalid candle high/low")


def features(m15):
    validate_frame(m15)
    d=m15.copy()
    # The 4h index marks its OPEN. A state at t is only usable at t+4h.
    h4=d.resample('4h',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    counts=d.close.resample('4h',label='left',closed='left').count()
    h4=h4.where(counts.eq(16)).dropna()
    ht=midpoint(h4.high,h4.low,9); kj=midpoint(h4.high,h4.low,26)
    sa=((ht+kj)/2).shift(26); sb=midpoint(h4.high,h4.low,52).shift(26)
    top=np.maximum(sa,sb); bot=np.minimum(sa,sb)
    strength=adx(h4)
    h4['bull']=(h4.close>top)&(ht>kj)&(kj>=kj.shift(1))&(strength>22)
    h4['bear']=(h4.close<bot)&(ht<kj)&(kj<=kj.shift(1))&(strength>22)
    # shift one whole H4 bar before broadcast (no H4 repainting).
    state=h4[['bull','bear']].shift(1).reindex(d.index,method='ffill').fillna(False)
    d[['htf_bull','htf_bear']]=state[['bull','bear']].astype(bool).to_numpy()
    d['tenkan']=midpoint(d.high,d.low,9); d['kijun']=midpoint(d.high,d.low,26)
    sa=((d.tenkan+d.kijun)/2).shift(26); sb=midpoint(d.high,d.low,52).shift(26)
    d['kumo_top']=np.maximum(sa,sb)
    d['kumo_bot']=np.minimum(sa,sb)
    d['rsi']=rsi(d.close); d['atr']=atr(d)
    d['swing_low']=d.low.rolling(5).min(); d['swing_high']=d.high.rolling(5).max()
    lo3=d.low.rolling(3).min(); hi3=d.high.rolling(3).max()
    rsilo=d.rsi.rolling(3).min(); rsihi=d.rsi.rolling(3).max()
    bullish=(d.close-d.low)/(d.high-d.low).replace(0,np.nan)>=.66
    bearish=(d.high-d.close)/(d.high-d.low).replace(0,np.nan)>=.66
    in_session=(d.index.hour>=8)&(d.index.hour<21)
    d['long_signal']=(d.htf_bull & in_session & (rsilo<50) & (rsilo>35)
          & (lo3<=d.kijun*1.002) & bullish & (d.high>d.high.shift(1))
          & (d.close>d.tenkan) & (d.close>d.kumo_top))
    d['short_signal']=(d.htf_bear & in_session & (rsihi>50) & (rsihi<65)
          & (hi3>=d.kijun*.998) & bearish & (d.low<d.low.shift(1))
          & (d.close<d.tenkan) & (d.close<d.kumo_bot))
    d[['long_signal','short_signal']]=d[['long_signal','short_signal']].fillna(False)
    return d


def backtest(m15, settings=None):
    s=settings or Settings()
    if s.initial_capital<=0 or not 0<s.risk_per_trade<1 or not 0<s.margin_cap<=1 or s.leverage<=0:
        raise ValueError("Invalid settings")
    d=features(m15)
    d=d[(d.index>=pd.Timestamp(s.start,tz='UTC')) & (d.index<pd.Timestamp(s.end,tz='UTC'))]
    if len(d)==0:raise ValueError("No bars in requested test interval")
    cash=s.initial_capital; p=None; pending=None; exit_next=False; trades=[]; curves=[]; costs=0.; fees=0.
    def fill_price(price, side):
        # side +1=buy, -1=sell; worst-direction slippage
        return price*(1+side*s.slippage_per_fill)
    def close_leg(qty, price, ts, reason):
        nonlocal p,cash,fees,costs
        direction=p['side']; executed=fill_price(price,-direction)
        gross=direction*qty*(executed-p['entry']); commission=qty*executed*s.fee_per_fill
        cash+=gross-commission; fees+=commission; costs+=qty*price*s.slippage_per_fill
        p['pnl']+=gross-commission;p['remaining']-=qty
        if p['remaining']<1e-12:
            trades.append({'entry_time':p['time'].isoformat(),'exit_time':ts.isoformat(),
              'side':'long' if direction==1 else 'short','entry':p['entry'], 'exit':executed,
              'qty':p['qty'],'pnl':p['pnl'],'tp1_hit':p['tp1_hit'],'reason':reason})
            p=None
    for i,(ts,row) in enumerate(d.iterrows()):
        # Orders originated from preceding CLOSED M15 candle execute at this open.
        if p is not None and exit_next:
            close_leg(p['remaining'],float(row.open),ts,'kijun_next_open')
        exit_next=False
        if p is None and pending is not None:
            direction,stop=pending;pending=None
            entry=fill_price(float(row.open), direction)
            distance=direction*(entry-stop)
            if distance/entry>=s.min_stop_pct and distance>0:
                # all-in stop loss incl both taker fees and slippage budget
                capital_at_risk=cash*s.risk_per_trade
                per_unit_risk=distance + entry*2*(s.fee_per_fill+s.slippage_per_fill)
                qty=min(capital_at_risk/per_unit_risk,
                        cash*s.margin_cap*s.leverage/entry)
                if qty*entry>=5:
                    commission=qty*entry*s.fee_per_fill
                    cash-=commission;fees+=commission; costs+=qty*float(row.open)*s.slippage_per_fill
                    p=dict(time=ts,side=direction,entry=entry,stop=stop,
                      tp=entry+direction*distance*1.5,qty=qty,remaining=qty,
                      tp1_hit=False,pnl=-commission)
        if p is not None:
            direction=p['side']; stop=p['stop']; tp=p['tp']
            # Gap-through-stop at open receives open, not unrealistic perfect stop.
            gap_stop=(direction==1 and row.open<=stop) or (direction==-1 and row.open>=stop)
            stop_touch=(direction==1 and row.low<=stop) or (direction==-1 and row.high>=stop)
            tp_touch=(direction==1 and row.high>=tp) or (direction==-1 and row.low<=tp)
            if gap_stop:close_leg(p['remaining'],float(row.open),ts,'gap_stop')
            elif stop_touch:close_leg(p['remaining'],stop,ts,'stop_or_be')
            elif tp_touch and not p['tp1_hit']:
                # Sell 50%, BE becomes active only FROM THE NEXT BAR.
                close_leg(p['remaining']*.5,tp,ts,'tp1')
                if p is not None:
                    p['tp1_hit']=True;p['stop_next']=p['entry']
            if p is not None:
                # Kijun exit uses the completed candle and fills next OPEN.
                if p['tp1_hit'] and pd.notna(row.kijun):
                    exit_next = ((direction==1 and row.close<row.kijun)
                              or (direction==-1 and row.close>row.kijun))
                # TP1 itself was filled this candle; BE activates next candle.
                if 'stop_next' in p:p['stop']=p.pop('stop_next')
        # Detect entry with CURRENT close and queue for NEXT bar. Do not reopen same bar.
        if p is None and pending is None and i+1<len(d):
            if bool(row.long_signal) and np.isfinite(row.swing_low) and np.isfinite(row.atr):
                pending=(1,float(row.swing_low-.5*row.atr))
            elif bool(row.short_signal) and np.isfinite(row.swing_high) and np.isfinite(row.atr):
                pending=(-1,float(row.swing_high+.5*row.atr))
        equity=cash+(p['side']*p['remaining']*(float(row.close)-p['entry']) if p else 0.)
        curves.append((ts,equity,cash))
    # Final mark-to-market: open position valued but not forced closed.
    curve=pd.DataFrame(curves,columns=['timestamp','equity','cash']).set_index('timestamp')
    ledger=pd.DataFrame(trades)
    eq=curve.equity; dd=(eq/eq.cummax()-1)*100
    n=len(ledger); net=(float(eq.iloc[-1])/s.initial_capital-1)*100
    years=(eq.index[-1]-eq.index[0]).total_seconds()/86400/365.25
    win=(ledger.pnl>0).sum() if n else 0
    gains=ledger.loc[ledger.pnl>0,'pnl'].sum() if n else 0
    losses=-ledger.loc[ledger.pnl<0,'pnl'].sum() if n else 0
    months=eq.resample('ME').last().pct_change()
    if len(months):months.iloc[0]=eq.resample('ME').last().iloc[0]/s.initial_capital-1
    monthly={str(k.strftime('%Y-%m')):round(float(v)*100,3) for k,v in months.items()}
    return {'start':str(eq.index[0]),'end':str(eq.index[-1]),'bars':len(d),
      'initial_equity':s.initial_capital,'final_marked_equity':float(eq.iloc[-1]),
      'net_return_pct':net,'cagr_pct':((float(eq.iloc[-1])/s.initial_capital)**(1/years)-1)*100 if years>0 and eq.iloc[-1]>0 else None,
      'max_drawdown_pct':float(dd.min()),'closed_trades':n,'win_rate_pct':float(win/n*100) if n else None,
      'profit_factor':float(gains/losses) if losses>0 else (None if gains==0 else 'inf'),
      'paid_fees':fees,'slippage_cost_est':costs,'open_position_at_end':p is not None,
      'monthly_returns_pct':monthly},ledger,curve