"""Structural exits, slope/ADX and closed-HTF timing regressions."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import cfg, system, setup_position, bars_for, FakeData

@pytest.mark.parametrize('side', ['long', 'short'])
@pytest.mark.parametrize('policy', ['REJECT', 'WIDEN'])
def test_minimum_stop(side, policy, cfg):
    cfg['al_brooks_filters']['require_signal_bar_breakout'] = False
    cfg['risk_and_exit'].update(min_stop_distance_pct=.012, min_stop_policy=policy)
    bar = pd.Series(dict(high=100.1, low=99.9, close=100., kijun=100., atr=.01, timestamp=0))
    p = lb.size_position(FakeData(), 'BTC/USDT:USDT', side, bar, 10000, cfg, '1h')
    if policy == 'REJECT': assert p is None
    else:
        assert abs(p['entry_price']-p['initial_sl'])/p['entry_price'] == pytest.approx(.012)
        assert p['qty']*p['entry_price'] < p['max_notional']
        assert p['qty']*(abs(p['entry_price']-p['initial_sl'])+p['entry_price']*p['fee_rate']) <= 50.000001

@pytest.mark.parametrize('side', ['long', 'short'])
@pytest.mark.parametrize('policy', ['QUARTER_R', 'CLOSE_CONFIRM'])
def test_partial_stop_transition(side, policy):
    sign = 1 if side == 'long' else -1
    p=dict(side=side, entry_price=100., initial_sl=100-sign*10, active_sl=100-sign*10,
           initial_r_distance=10., be_policy=policy)
    stop, confirmed = lb.runner_transition(p)
    assert stop == pytest.approx(100-sign*(2.5 if policy=='QUARTER_R' else 10))
    assert confirmed == (policy == 'QUARTER_R')

@pytest.mark.parametrize('side', ['long', 'short'])
def test_runner_no_partial_before_2r_and_hard4(system, side):
    p=setup_position(system, side=side, state=lb.INITIAL);sign=1 if side=='long' else -1
    with system.db.connect() as db:
        db.execute("UPDATE positions SET exit_scheme='PURE_RUNNER',be_policy='MILESTONE',tp1_price=?,tp1_close_pct=0,hard_tp_price=? WHERE symbol=?", (100+sign*20,100+sign*40,p['symbol']))
    system.data.prices[p['symbol']]=100+sign*19.99
    system.watchdog(1_800_003_000)
    before=system.db.position(p['symbol'])
    assert before['state']==lb.INITIAL and before['active_sl']==p['initial_sl']
    system.data.prices[p['symbol']]=100+sign*20
    system.watchdog(1_800_003_015)
    after=system.db.position(p['symbol'])
    assert after['state']==lb.TRAILING and after['qty']==p['qty'] and after['active_sl']==100
    assert system.db.history_summary(1_800_003_015)[1]==0
    system.data.prices[p['symbol']]=100+sign*40
    system.watchdog(1_800_003_030)
    assert system.db.position(p['symbol']) is None
    with system.db.connect() as db:
        row=db.execute('SELECT reason,qty FROM trade_history').fetchone()
    assert tuple(row)==('hard_tp',2.)

@pytest.mark.parametrize('side', ['long', 'short'])
def test_htf_trail_waits_for_new_close(system, monkeypatch, side):
    c=system.config.read();c['bot_control']['auto_trade_enabled']=False;system.config.write(c)
    p=setup_position(system,side=side,state=lb.INITIAL);sign=1 if side=='long' else -1
    boundary=1_800_000_000//14400*14400;now=boundary+3600+10
    with system.db.connect() as db:
        db.execute("UPDATE positions SET exit_scheme='PURE_RUNNER',be_policy='MILESTONE',tp1_price=?,trail_timeframe='4h',trail_atr=.5 WHERE symbol=?", (100+sign*20,p['symbol']))
    system.data.prices[p['symbol']]=100+sign*20;system.watchdog(now)
    original=lb.indicators
    def frame(bars,c,tf,stamp):
        result=original(bars,c,tf,stamp)
        result.loc[len(result)-1,['kijun','close','atr']]=[100+sign*5,100+sign*6,2]
        return result
    monkeypatch.setattr(lb,'indicators',frame)
    system.data.bars[(p['symbol'],'4h')]=bars_for(now,'4h')
    system.scan(now)
    assert system.db.position(p['symbol'])['active_sl']==100 # old 4h candle ignored
    later=boundary+14400+3
    system.data.bars[(p['symbol'],'4h')]=bars_for(later,'4h')
    system.scan(later)
    assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100+sign*4)

@pytest.mark.parametrize('kind',['flat','up','down'])
def test_adx_initialization_and_known_trends(kind):
    x=np.zeros(200) if kind=='flat' else np.arange(200)*(1 if kind=='up' else -1)
    frame=pd.DataFrame(dict(high=x+300,low=x+298,close=x+299))
    out=lb.adx_wilder(frame)
    assert out.iloc[:27].isna().all()
    assert np.allclose(out.iloc[27:],0 if kind=='flat' else 100)

def test_deployed_config_matches_eligible_winner():
    root=Path(__file__).parents[2]
    c=lb.validate_config(json.loads((root/'lbank_project/config.json').read_text()))
    if (root/'high_cagr/output/winning_config.json').exists():
        expected=lb.validate_config(json.loads((root/'high_cagr/output/winning_config.json').read_text()))
        result=json.loads((root/'high_cagr/output/matrix.json').read_text())['winner']
        # The deployed config is the audited winner plus ONLY the overrides that passed the ablation decision gate.
        fixes=json.loads((root/'high_cagr/output/verified_fixes.json').read_text()) if (root/'high_cagr/output/verified_fixes.json').exists() else None
        if fixes and fixes['final_subset']!='0_BASELINE':
            ablation=json.loads((root/'high_cagr/output/ablation_fixes.json').read_text())
            assert ablation['verdicts']['0.0075'][fixes['final_subset']]['verdict']=='ACCEPTED'
            expected['strategy_settings'].update(fixes['config_overrides']['strategy_settings'])
        extra=root/'high_cagr/output/deployed_overrides.json'
        if extra.exists():
            d=json.loads(extra.read_text());assert all((root/v.split(' ')[0]).exists() for k,v in d['evidence'].items() if v.startswith('high_cagr'))
            expected['strategy_settings'].update(d['config_overrides']['strategy_settings'])
        assert c==expected
        assert result['eligible'] and result['worst_period_dd_pct']<=35
        assert c['risk_and_exit']['risk_per_trade_pct']==result['risk']
        assert c['strategy_settings']['pyramid_enabled']==result['pyramid']
        assert c['strategy_settings']['donchian_entry_period']==result['lookback']
        assert c['risk_and_exit']['min_stop_policy']=='REJECT'
        assert c['risk_and_exit']['min_stop_distance_pct']==.012
        return
    output=root/'portfolio/output' if (root/'portfolio/output/winning_config.json').exists() else root/'archetypes/output'
    expected=lb.validate_config(json.loads((output/'winning_config.json').read_text()))
    result=json.loads((output/'matrix.json').read_text())['winner']
    if output.parent.name=='portfolio':
        assert all(result[p]['max_dd_pct']<=25 for p in ['full','train','oos'])
    # Deployment changes only the user-requested universe/risk controls; the
    # eligible frozen benchmark still anchors the underlying signal and runner.
    for section in ['strategy_mode','ichimoku_params','filters_and_triggers',
                    'al_brooks_filters','structural_filters','archetype_strategy','portfolio_risk']:
        assert c[section]==expected[section]
    assert c['symbols']==[s for s in expected['symbols'] if s!='BNB/USDT:USDT']
    assert result['full']['trades']>=40
    assert result['train']['net_profit']>0 and result['oos']['net_profit']>0
    assert c['risk_and_exit']['min_stop_policy']=='REJECT'
    assert c['risk_and_exit']['min_stop_distance_pct']==.012
    assert c['risk_and_exit']['risk_per_trade_pct']==.005
    assert c['risk_and_exit']['engaged_capital_pct']==.60
    assert c['strategy_settings']['exit_tp_mode']=='CLOSE_TRAIL_KIJUN'
    assert c['strategy_settings']['breakeven_trigger_rr']==0
    assert c['strategy_settings']['hard_tp_rr']==0

@pytest.mark.parametrize('side',['long','short'])
def test_slope_and_adx_thresholds(cfg,side):
    frame=pd.DataFrame([dict(close=100.,high=101.,low=99.,tenkan=100.,kijun=100.,
        senkou_a_future=102.,senkou_b_future=98.,kumo_top=102.,kumo_bottom=98.,atr=2.,adx=25.)]*100)
    if side=='long':frame.loc[99,['close','tenkan','kijun']]=[110,108,105]
    else:frame.loc[99,['close','tenkan','kijun','senkou_a_future','senkou_b_future']]=[90,92,95,98,102]
    cfg['structural_filters'].update(enable_htf_slope_filter=True,min_htf_adx=25.)
    assert lb.regime(frame,cfg)==side
    frame.loc[99,'adx']=24.999
    assert lb.regime(frame,cfg) is None
    frame.loc[99,'adx']=25.
    frame.loc[97,'tenkan']=frame.loc[99,'tenkan']
    assert lb.regime(frame,cfg) is None # flat Tenkan rejected even when price outside Kumo

@pytest.mark.parametrize('side',['long','short'])
def test_close_confirm_freezes_stop_until_2r(system,monkeypatch,side):
    cfg=system.config.read();cfg['bot_control']['auto_trade_enabled']=False;system.config.write(cfg)
    p=setup_position(system,side=side,state=lb.TRAILING);sign=1 if side=='long' else -1
    with system.db.connect() as db:
        db.execute("UPDATE positions SET be_policy='CLOSE_CONFIRM',be_confirmed=0,initial_r_distance=10,be_trigger_rr=2,trail_atr=.6 WHERE symbol=?",(p['symbol'],))
    original=lb.indicators;closed=[100+sign*19.9]
    def frame(bars,c,tf,stamp):
        result=original(bars,c,tf,stamp)
        result.loc[len(result)-1,['kijun','close','atr']]=[100+sign*5,closed[0],2]
        return result
    monkeypatch.setattr(lb,'indicators',frame)
    now=1_800_000_003
    system.data.bars[(p['symbol'],'1h')]=bars_for(now)
    system.scan(now)
    assert system.db.position(p['symbol'])['active_sl']==p['initial_sl']
    closed[0]=100+sign*20;now+=3600
    system.data.bars[(p['symbol'],'1h')]=bars_for(now)
    system.scan(now)
    updated=system.db.position(p['symbol'])
    assert updated['be_confirmed']==1
    assert updated['active_sl']==pytest.approx(100+sign*3.8)
