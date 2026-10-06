"""Clean entry definitions and execution/state safeguards for all four families."""
import copy,json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import lbank_bot as lb
import strategy_archetypes as shared
from test_system import cfg,system,setup_position,bars_for

def configuration(cfg,family):
    c=copy.deepcopy(cfg);c['archetype_strategy'].update(family=family,entry_variant='MARKET',pending_policy='GTC_REGIME')
    c['structural_filters'].update(enable_htf_slope_filter=False,min_htf_adx=0.)
    return c

def frame(side):
    df=pd.DataFrame([dict(open=100.,close=100.,high=101.,low=99.,tenkan=100.,kijun=100.,senkou_a_future=102.,senkou_b_future=98.,kumo_top=102.,kumo_bottom=98.,atr=1.,rsi=50.,ema20=100.,ema50=98.,donchian_high_20=105.,donchian_low_20=95.)]*100)
    if side=='long':df.loc[99,['open','close','high','low','tenkan','kijun','senkou_a_future','rsi']]=[109.,110.,110.5,109.5,112.,108.,106.,42.]
    else:df.loc[99,['open','close','high','low','tenkan','kijun','senkou_a_future','senkou_b_future','rsi']]=[91.,90.,91.5,89.5,88.,92.,94.,100.,58.]
    return df

@pytest.mark.parametrize('side',['long','short'])
def test_pullback_accepts_rsi_dip_and_either_line(cfg,side):
    c=configuration(cfg,'ICHI_PULLBACK');df=frame(side)
    assert lb.entry_signal(df,side,c)
    if side=='long':
        assert df.iloc[-1].rsi<50
        assert df.iloc[-1].low>df.iloc[-1].kijun+.3*df.iloc[-1].atr # Tenkan touch qualifies
    else:assert df.iloc[-1].rsi>50

@pytest.mark.parametrize('side',['long','short'])
def test_momentum_strict_rsi_and_real_cross(cfg,side):
    c=configuration(cfg,'ICHI_BREAKOUT');c['archetype_strategy']['entry_variant']='KUMO_CROSS'
    df=frame(side)
    df.loc[99,'tenkan']=109 if side=='long' else 91
    df.loc[99,'rsi']=56 if side=='long' else 44
    assert lb.entry_signal(df,side,c)
    df.loc[99,'rsi']=55 if side=='long' else 45
    assert not lb.entry_signal(df,side,c)
    df.loc[99,'rsi']=56 if side=='long' else 44
    df.loc[98,'close']=103 if side=='long' else 97
    assert not lb.entry_signal(df,side,c) # already outside Kumo, not a new break

@pytest.mark.parametrize('side',['long','short'])
def test_donchian_excludes_current_bar_extreme(cfg,side):
    c=configuration(cfg,'DONCHIAN');c['archetype_strategy']['donchian_lookback']=20
    values=pd.DataFrame(dict(high=np.full(100,101.),low=np.full(100,99.),close=np.full(100,100.)))
    values.loc[99,['high','low','close']]=[1000,98,110] if side=='long' else [102,1,90]
    df=shared.add_features(values);df['kumo_top']=102.;df['kumo_bottom']=98.;df['atr']=1.
    assert df.iloc[-1].donchian_high_20==101 and df.iloc[-1].donchian_low_20==99
    assert lb.entry_signal(df,side,c)

@pytest.mark.parametrize('side',['long','short'])
def test_h2_requires_second_attempt_after_renewed_pullback(side):
    high=np.array([10.,12.,11.,13.]);low=np.array([9.,10.,9.,10.])
    if side=='short':high,low=20-low,20-high
    df=pd.DataFrame(dict(high=high,low=low))
    out=shared.second_attempt(df,side)
    assert not out.iloc[1] and out.iloc[-1]

@pytest.mark.parametrize('side',['long','short'])
def test_hard_target_has_no_early_partial(system,side):
    p=setup_position(system,side=side,state=lb.INITIAL);sign=1 if side=='long' else -1
    with system.db.connect() as db:
        db.execute("UPDATE positions SET exit_scheme='HARD_TARGET',tp1_close_pct=0,hard_tp_price=? WHERE symbol=?",(100+sign*30,p['symbol']))
    system.data.prices[p['symbol']]=100+sign*20;system.watchdog(1_800_000_010)
    assert system.db.position(p['symbol'])['state']==lb.INITIAL
    assert system.db.position(p['symbol'])['qty']==2
    system.data.prices[p['symbol']]=100+sign*30;system.watchdog(1_800_000_025)
    assert not system.db.positions()
    with system.db.connect() as db:assert db.execute('SELECT reason FROM trade_history').fetchone()[0]=='hard_tp'

@pytest.mark.parametrize('side',['long','short'])
def test_close_trail_ignores_wick_until_closed_break(system,monkeypatch,side):
    c=system.config.read();c['bot_control']['auto_trade_enabled']=False;system.config.write(c)
    p=setup_position(system,side=side,state=lb.TRAILING);sign=1 if side=='long' else -1
    with system.db.connect() as db:db.execute('UPDATE positions SET trail_close_only=1 WHERE symbol=?',(p['symbol'],))
    original=lb.indicators;closed=[100+sign*6]
    def indicator(bars,c,tf,now):
        df=original(bars,c,tf,now);df.loc[len(df)-1,['kijun','close','atr']]=[100+sign*5,closed[0],2]
        return df
    monkeypatch.setattr(lb,'indicators',indicator);now=1_800_000_003
    system.data.bars[p['symbol'],'1h']=bars_for(now)
    system.scan(now);assert system.db.position(p['symbol'])['active_sl']==p['initial_sl']
    system.data.prices[p['symbol']]=100+sign*4;system.watchdog(now+15)
    assert system.db.position(p['symbol']) # wick across line alone cannot exit
    closed[0]=100+sign*4;now+=3600;system.data.bars[p['symbol'],'1h']=bars_for(now)
    system.scan(now);assert not system.db.positions()

@pytest.mark.parametrize('side',['long','short'])
def test_gtc_rechecks_regime_before_pending_fill(system,cfg,monkeypatch,side):
    c=configuration(cfg,'EMA_PULLBACK');p=setup_position(system,side=side)
    with system.db.connect() as db:
        db.execute("UPDATE positions SET pending_policy='GTC_REGIME',expiry_ts=?,strategy_config=? WHERE symbol=?",(9_000_000_000_000,json.dumps(c),p['symbol']))
    now=1_800_000_003;system.data.bars[p['symbol'],'4h']=bars_for(now,'4h')
    system.data.prices[p['symbol']]=101 if side=='long' else 99
    monkeypatch.setattr(lb,'regime',lambda df,c:None)
    system.watchdog(now)
    assert not system.db.positions() and system.db.history_summary(now)[1]==0

@pytest.mark.parametrize('side',['long','short'])
def test_opposite_channel_trail_uses_correct_side(system,cfg,monkeypatch,side):
    c=configuration(cfg,'DONCHIAN');c['bot_control']['auto_trade_enabled']=False;system.config.write(c)
    p=setup_position(system,side=side,state=lb.TRAILING)
    with system.db.connect() as db:
        db.execute("UPDATE positions SET trail_source='DONCHIAN10',trail_atr=0,strategy_config=? WHERE symbol=?",(json.dumps(c),p['symbol']))
    original=lb.indicators
    def indicator(bars,c,tf,now):
        df=original(bars,c,tf,now)
        df.loc[len(df)-1,['opposite_low_10','opposite_high_10','close']]=[104,96,106 if side=='long' else 94]
        return df
    monkeypatch.setattr(lb,'indicators',indicator);now=1_800_000_003;system.data.bars[p['symbol'],'1h']=bars_for(now)
    system.scan(now);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(104 if side=='long' else 96)

def test_math_counterexample_touch_and_rsi50_can_coexist(cfg):
    now=1_800_000_003;bars=bars_for(now)
    bars[-2][3]=100. # wick touches slow Kijun; RSI depends on closes, not this wick
    out=lb.indicators(bars,cfg,'1h',now);b=out.iloc[-1]
    assert b.low<=b.kijun and b.tenkan>=b.kijun and b.rsi>=50

@pytest.mark.parametrize('side',['long','short'])
def test_market_gap_rejects_actual_micro_stop(system,cfg,side):
    c=configuration(cfg,'DONCHIAN');c['risk_and_exit'].update(min_stop_distance_pct=.012,min_stop_policy='REJECT')
    p=setup_position(system,side=side);sign=1 if side=='long' else -1
    p.update(initial_sl=100-sign*1.2,strategy_config=json.dumps(c))
    with system.db.connect() as db:
        db.execute('UPDATE positions SET initial_sl=?,strategy_config=? WHERE symbol=?',(p['initial_sl'],p['strategy_config'],p['symbol']))
    assert not system._activate(p,100-sign*.02,1_800_000_003)
    assert not system.db.positions()
