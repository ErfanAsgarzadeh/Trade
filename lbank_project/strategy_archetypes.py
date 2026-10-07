"""Closed-candle definitions shared by the runtime and benchmark suite.

No ADX, Barb-Wire, extension cap or legacy RSI gate is applied here.
"""
import numpy as np
import pandas as pd

DEFAULTS=dict(family='LEGACY',entry_variant='KUMO_CROSS',donchian_lookback=20,
              stop_source='KIJUN',trail_source='KIJUN',require_h2_l2=False,
              trail_close_only=False,pending_policy='ONE_BAR')

ICHIMOKU_PRESETS = {'crypto': (20, 60, 120, 30), 'standard': (9, 26, 52, 26)}

def apply_strategy_settings(config):
    """Map the public Donchian settings to the shared benchmark definitions.

    Older benchmark configurations keep their original explicit fields.
    A hybrid uses hybrid_trail_mode to select the underlying unlimited runner.
    """
    settings = config.get('strategy_settings')
    if settings is None:
        return
    periods = ICHIMOKU_PRESETS[settings['ichimoku_preset']]
    config['ichimoku_params'].update(zip(('tenkan', 'kijun', 'senkou_b', 'displacement'), periods))
    mode = settings['exit_tp_mode']
    if mode == 'HYBRID_TRAIL_AND_HARD_TP':
        mode = settings['hybrid_trail_mode']
    close_only = mode == 'CLOSE_TRAIL_KIJUN'
    config['archetype_strategy'].update(family='DONCHIAN', entry_variant='MARKET',
        donchian_lookback=settings['donchian_entry_period'],
        stop_source=settings['initial_stop_mode'],
        trail_source='KIJUN' if close_only else 'DONCHIAN10',
        trail_close_only=close_only, require_h2_l2=False, pending_policy='GTC_REGIME')
    config['risk_and_exit'].update(exit_scheme='PURE_KIJUN', tp1_close_pct=0.0,
        breakeven_policy='NONE', trail_atr_buffer=0.0, trail_timeframe='ENTRY',
        hard_tp_rr=settings['hard_tp_rr'], breakeven_trigger_rr=settings['breakeven_trigger_rr'])
    config['al_brooks_filters'].update(require_signal_bar_breakout=False,
        require_h2_l2_pullback=False, enable_barb_wire_filter=False)

def ema_sma(values,period):
    x=np.asarray(values,dtype=float);out=np.full(len(x),np.nan)
    if len(x)>=period:
        out[period-1]=np.mean(x[:period]);alpha=2/(period+1)
        for i in range(period,len(x)):out[i]=alpha*x[i]+(1-alpha)*out[i-1]
    return out

def add_features(df):
    df=df.copy()
    for n in [20,50]:df[f'ema{n}']=ema_sma(df.close,n)
    for n in [10,20]:
        df[f'donchian_high_{n}']=df.high.rolling(n).max().shift(1)
        df[f'donchian_low_{n}']=df.low.rolling(n).min().shift(1)
    df['opposite_low_10']=df.low.rolling(10).min()
    df['opposite_high_10']=df.high.rolling(10).max()
    return df

def regime_masks(df,config):
    family=config['archetype_strategy']['family']
    if family=='EMA_PULLBACK':
        long=(df.close>df.ema50)&(df.ema20>df.ema50)
        short=(df.close<df.ema50)&(df.ema20<df.ema50)
    else:
        long=df.close>df.kumo_top;short=df.close<df.kumo_bottom
        if family=='ICHI_PULLBACK':
            long&=(df.tenkan>=df.kijun)&(df.senkou_a_future>df.senkou_b_future)
            short&=(df.tenkan<=df.kijun)&(df.senkou_a_future<df.senkou_b_future)
        if family=='DONCHIAN':
            n=config['archetype_strategy']['donchian_lookback']
            long&=df.close>df[f'donchian_high_{n}']
            short&=df.close<df[f'donchian_low_{n}']
    return long.fillna(False),short.fillna(False)

def second_attempt(df,side,lookback=8):
    """Mechanical H2/L2 proxy: prior attempt, renewed pullback, second attempt.

    Current high/low must exceed the previous high/low. No discretionary bar reading.
    """
    is_long=side=='long';attempt=(df.high>df.high.shift(1)) if is_long else (df.low<df.low.shift(1))
    found=pd.Series(False,index=df.index)
    for offset in range(2,lookback+1):
        pullback=pd.Series(False,index=df.index)
        for j in range(1,offset):
            pullback|=(df.low.shift(j)<df.low.shift(offset)) if is_long else (df.high.shift(j)>df.high.shift(offset))
        found|=attempt.shift(offset,fill_value=False)&pullback
    return attempt&found

def entry_masks(df,config):
    spec=config['archetype_strategy'];family=spec['family'];variant=spec['entry_variant']
    outside_long=df.close>df.kumo_top;outside_short=df.close<df.kumo_bottom
    if family=='ICHI_BREAKOUT':
        d=config['ichimoku_params']['displacement']
        long=outside_long&(df.tenkan>df.kijun)&(df.senkou_a_future>df.senkou_b_future)&(df.close>df.high.shift(d))&(df.rsi>55)
        short=outside_short&(df.tenkan<df.kijun)&(df.senkou_a_future<df.senkou_b_future)&(df.close<df.low.shift(d))&(df.rsi<45)
        if variant=='KUMO_CROSS':
            long&=df.close.shift(1)<=df.kumo_top.shift(1)
            short&=df.close.shift(1)>=df.kumo_bottom.shift(1)
        else:
            long&=(df.close>df.tenkan)&(df.close.shift(1)<=df.tenkan.shift(1))
            short&=(df.close<df.tenkan)&(df.close.shift(1)>=df.tenkan.shift(1))
    elif family=='ICHI_PULLBACK':
        long=outside_long&(df.low<=df[['tenkan','kijun']].max(axis=1)+.3*df.atr)&(df.close>df.kijun)&df.rsi.between(38,65)&(df.close>df.open)
        short=outside_short&(df.high>=df[['tenkan','kijun']].min(axis=1)-.3*df.atr)&(df.close<df.kijun)&df.rsi.between(35,62)&(df.close<df.open)
    elif family=='EMA_PULLBACK':
        body=(df.close-df.open).abs();span=(df.high-df.low).clip(lower=1e-8)
        lower=df[['open','close']].min(axis=1)-df.low;upper=df.high-df[['open','close']].max(axis=1)
        long=(df.low<=df.ema20)&(df.close>df.ema20)&((df.close-df.low)/span>=.6)&((lower>=1.2*body)|((df.close>df.open)&(body>=.5*span)))
        short=(df.high>=df.ema20)&(df.close<df.ema20)&((df.high-df.close)/span>=.6)&((upper>=1.2*body)|((df.close<df.open)&(body>=.5*span)))
        if spec['require_h2_l2']:
            long&=second_attempt(df,'long',config['al_brooks_filters']['h2_l2_lookback_bars'])
            short&=second_attempt(df,'short',config['al_brooks_filters']['h2_l2_lookback_bars'])
    elif family=='DONCHIAN':long,short=regime_masks(df,config)
    else:raise ValueError('Unsupported archetype family')
    valid=df.atr.gt(0)&np.isfinite(df.atr)
    return (long&valid).fillna(False),(short&valid).fillna(False)

def initial_stop(bar,side,config):
    sign=1 if side=='long' else -1
    source=config['archetype_strategy']['stop_source'];buffer=config['risk_and_exit']['sl_atr_buffer']
    if source=='SIGNAL_BAR':return float(bar.low-buffer*bar.atr if sign==1 else bar.high+buffer*bar.atr)
    if source=='ATR2':return float(bar.close-sign*config.get('strategy_settings',{}).get('initial_stop_atr_mult',2.0)*bar.atr)
    return float(bar.kijun-sign*buffer*bar.atr)

def trail_line(bar,side,source):
    if source=='EMA20':return float(bar.ema20)
    if source=='DONCHIAN10':return float(bar.opposite_low_10 if side=='long' else bar.opposite_high_10)
    return float(bar.kijun)


def breakout_strength(bar,side,lookback=20):
    if side=='long':return (float(bar.close)-max(float(bar[f'donchian_high_{lookback}']),float(bar.kumo_top)))/float(bar.close)
    return (min(float(bar[f'donchian_low_{lookback}']),float(bar.kumo_bottom))-float(bar.close))/float(bar.close)
