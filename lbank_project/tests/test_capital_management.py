"""Regression coverage for fixed-risk margin sizing and configurable runners."""
import copy
import json
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import lbank_bot as lb
from dashboard_server import create_app
from test_system import system, cfg, bars_for

@pytest.fixture
def modern():
    c=json.loads((Path(__file__).parents[1]/'config.json').read_text())
    c['risk_and_exit'].update(risk_per_trade_pct=.005,max_open_positions=4,engaged_capital_pct=.6,leverage_mode='DYNAMIC_MARGIN')
    c['strategy_settings'].update(ichimoku_preset='crypto',donchian_entry_period=20,initial_stop_mode='ATR2',exit_tp_mode='CLOSE_TRAIL_KIJUN',hard_tp_rr=0.,breakeven_trigger_rr=0.,pyramid_enabled=False,initial_stop_anchor='ENTRY',trail_atr_buffer=0.)
    return lb.validate_config(c)

def open_runner(system, modern, side='long'):
    system.config.write(modern)
    modern = system.config.read()
    bar=pd.Series(dict(close=100.,high=102.,low=98.,kijun=95. if side=='long' else 105.,atr=1.,timestamp=0))
    p=lb.size_position(system.data,modern['symbols'][0],side,bar,10000.,modern,'4h')
    assert p
    system._insert(p)
    assert system._activate(p,100.,1_800_000_003)
    return system.db.position(p['symbol'])

@pytest.mark.parametrize('mode', ['DYNAMIC_MARGIN','FIXED_LEVERAGE'])
@pytest.mark.parametrize('stop_pct', [.012,.02,.04,.1])
def test_fixed_risk_and_slot_cap(modern,mode,stop_pct):
    modern['risk_and_exit']['leverage_mode']=mode
    b=lb.entry_budget(10000,stop_pct,modern)
    assert b['slot_margin_usd']==1500
    assert b['risk_budget']==50
    assert b['final_notional']*(stop_pct+.0012+.0004)==pytest.approx(50)
    assert b['final_notional']/b['isolated_leverage']<=1500
    assert 1<=b['isolated_leverage']<=5
    if mode=='FIXED_LEVERAGE':assert b['isolated_leverage']==5

def test_risk_reduced_when_capped(modern):
    modern['risk_and_exit']['risk_per_trade_pct']=.05
    b=lb.entry_budget(10000,.012,modern)
    assert b['final_notional']==7500
    assert b['final_notional']*.0136 < b['risk_budget']

@pytest.mark.parametrize('mode',['DYNAMIC_MARGIN','FIXED_LEVERAGE'])
def test_remaining_margin_cap(modern,mode):
    modern['risk_and_exit']['leverage_mode']=mode
    b=lb.entry_budget(10000,.012,modern,500*5)
    assert b['final_notional']/b['isolated_leverage']<=500

@pytest.mark.parametrize('side',['long','short'])
def test_fill_atr2_stop_and_sizing(system,modern,side):
    system.config.write(modern)
    bar=pd.Series(dict(close=100.,high=102.,low=98.,kijun=95.,atr=1.,timestamp=0))
    p=lb.size_position(system.data,modern['symbols'][0],side,bar,10000,modern,'4h');system._insert(p)
    assert system._activate(p,104.,1_800_000_003)
    p=system.db.position(p['symbol']);sign=1 if side=='long' else -1
    assert p['initial_sl']==104-sign*2
    modeled_risk=p['qty']*p['contract_size']*(2+104*.0016)
    assert 0<=50-modeled_risk < .001
    assert lb.position_margin(p)<=1500
    assert p['state']==lb.TRAILING

@pytest.mark.parametrize('side',['long','short'])
def test_hard_target_and_breakeven(system,modern,side):
    modern['strategy_settings'].update(exit_tp_mode='HYBRID_TRAIL_AND_HARD_TP',hard_tp_rr=3.,breakeven_trigger_rr=2.)
    p=open_runner(system,modern,side);sign=1 if side=='long' else -1
    assert p['hard_tp_price']==100+sign*6
    system.data.prices[p['symbol']]=100+sign*4
    system.watchdog(1_800_000_004)
    p=system.db.position(p['symbol']);assert p['active_sl']==100
    assert p['qty']>0
    system.data.prices[p['symbol']]=100+sign*6
    system.watchdog(1_800_000_005)
    assert not system.db.position(p['symbol'])
    with system.db.connect() as db:assert db.execute('SELECT reason FROM trade_history').fetchone()[0]=='hard_tp'

def test_be_disabled_and_frozen_exit(system,modern):
    p=open_runner(system,modern)
    changed=copy.deepcopy(modern);changed['strategy_settings'].update(hard_tp_rr=3.,breakeven_trigger_rr=2.)
    system.config.write(changed);system.data.prices[p['symbol']]=110.
    system.watchdog(1_800_000_004)
    stored=system.db.position(p['symbol']);assert stored['active_sl']==98
    assert stored['hard_tp_price']==0
    assert stored['be_trigger_rr']==0

def test_total_margin_uses_actual_leverage(system,modern):
    p=open_runner(system,modern)
    used=lb.position_margin(p)
    assert system.available_notional(10000,modern)==pytest.approx((6000-used)*5)
    changed=copy.deepcopy(modern);changed['risk_and_exit']['default_isolated_leverage']=10
    assert system.available_notional(10000,changed)==pytest.approx((6000-used)*10)

def test_budget_hot_reload_and_daily_stop(system,modern):
    p=open_runner(system,modern)
    changed=copy.deepcopy(modern);changed['risk_and_exit']['engaged_capital_pct']=.001
    assert system.available_notional(10000,changed)==0
    system.close_symbol(p['symbol'],1_800_000_003)
    system.config.write(modern)
    with system.db.connect() as db:
        db.execute("INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason,dry_run) VALUES(?,?,?,?,?,?,?,?,?)",('BTC/USDT:USDT','long',-200.,1_800_000_003,1.,100.,80.,'stop',1))
    bar=pd.Series(dict(close=100.,high=102.,low=98.,kijun=95.,atr=1.,timestamp=0))
    q=lb.size_position(system.data,modern['symbols'][0],'long',bar,10000,modern,'4h');system._insert(q)
    assert not system._activate(q,100.,1_800_000_004)
    assert not system.db.position(q['symbol'])

@pytest.mark.parametrize('change',[
    {'exit_tp_mode':'INVALID'}, {'initial_stop_mode':'SIGNAL_BAR'},
    {'ichimoku_preset':'INVALID'}, {'hard_tp_rr':float('nan')},
    {'breakeven_trigger_rr':-1.}, {'exit_tp_mode':'HYBRID_TRAIL_AND_HARD_TP','hard_tp_rr':0.}])
def test_invalid_strategy_rejected(modern,change):
    modern['strategy_settings'].update(change)
    with pytest.raises(lb.ConfigError):lb.validate_config(modern)

@pytest.mark.parametrize('key,value',[('engaged_capital_pct',0),('engaged_capital_pct',1.01),('leverage_mode','INVALID'),('min_stop_policy','WIDEN'),('min_stop_distance_pct',.011)])
def test_risk_invariants(modern,key,value):
    modern['risk_and_exit'][key]=value
    with pytest.raises(lb.ConfigError):lb.validate_config(modern)

def test_preset_and_donchian_mapping(modern):
    modern['strategy_settings'].update(ichimoku_preset='standard',donchian_entry_period=10,initial_stop_mode='KIJUN',exit_tp_mode='STOP_TRAIL_DONCHIAN10')
    c=lb.validate_config(modern)
    assert [c['ichimoku_params'][k] for k in ('tenkan','kijun','senkou_b','displacement')]==[9,26,52,26]
    assert c['archetype_strategy']['donchian_lookback']==10
    assert c['archetype_strategy']['trail_source']=='DONCHIAN10'
    assert not c['archetype_strategy']['trail_close_only']
    assert c['archetype_strategy']['stop_source']=='KIJUN'

def test_dashboard_margin_and_hot_reload(system,modern,monkeypatch):
    monkeypatch.setenv('BOT_PIN','test');p=open_runner(system,modern)
    with TestClient(create_app(system)) as client:
        headers={'X-Bot-Pin':'test'};s=client.get('/api/status',headers=headers).json()
        assert s['engaged_margin_usd']==pytest.approx(lb.position_margin(p))
        assert s['allowed_margin_usd']==pytest.approx(s['equity_usd']*.6)
        assert s['engaged_margin_pct']==pytest.approx(lb.position_margin(p)/s['equity_usd']*100)
        current=client.get('/api/config',headers=headers)
        c=current.json();c['strategy_settings'].update(ichimoku_preset='standard',exit_tp_mode='STOP_TRAIL_DONCHIAN10');c['risk_and_exit']['leverage_mode']='FIXED_LEVERAGE'
        result=client.put('/api/config',headers={**headers,'If-Match':current.headers['ETag']},json=c)
        assert result.status_code==200
        assert result.json()['archetype_strategy']['trail_source']=='DONCHIAN10'
        assert system.db.position(p['symbol'])['trail_source']=='KIJUN'
        system.data.fail.add(p['symbol']);s=client.get('/api/status',headers=headers).json()
        assert s['equity_usd'] is None and s['engaged_margin_pct'] is None
        assert s['engaged_margin_usd']>0

@pytest.mark.parametrize('side',['long','short'])
@pytest.mark.parametrize('exit_mode',['CLOSE_TRAIL_KIJUN','STOP_TRAIL_DONCHIAN10'])
def test_closed_4h_trail_and_ratchet(system,modern,monkeypatch,side,exit_mode):
    modern['strategy_settings']['exit_tp_mode']=exit_mode
    p=open_runner(system,modern,side);sign=1 if side=='long' else -1
    c=system.config.read();c['bot_control']['auto_trade_enabled']=False;system.config.write(c)
    later=1_800_014_403
    system.data.bars[(p['symbol'],'4h')]=bars_for(later,'4h')
    def indicator(raw,c,tf,now):
        stamp=(int(now)//lb.TIMEFRAMES[tf]-1)*lb.TIMEFRAMES[tf]*1000
        return pd.DataFrame([dict(timestamp=stamp,close=100.,kijun=100+sign,
            atr=1.,opposite_low_10=99.,opposite_high_10=101.)])
    monkeypatch.setattr(lb,'indicators',indicator)
    assert system.scan(later)
    if exit_mode=='CLOSE_TRAIL_KIJUN':
        assert not system.db.position(p['symbol'])
        with system.db.connect() as db:assert db.execute('SELECT reason FROM trade_history').fetchone()[0]=='kijun_break'
    else:
        assert system.db.position(p['symbol'])['active_sl']==100-sign
        def lower_line(raw,c,tf,now):
            f=indicator(raw,c,tf,now);f['opposite_low_10']=97.;f['opposite_high_10']=103.;return f
        monkeypatch.setattr(lb,'indicators',lower_line)
        assert system.scan(later+14400)
        assert system.db.position(p['symbol'])['active_sl']==100-sign

def test_pending_does_not_count_as_engaged_margin(system,modern,monkeypatch):
    monkeypatch.setenv('BOT_PIN','test');system.config.write(modern)
    bar=pd.Series(dict(close=100.,high=102.,low=98.,kijun=95.,atr=1.,timestamp=0))
    p=lb.size_position(system.data,modern['symbols'][0],'long',bar,10000,modern,'4h');system._insert(p)
    with TestClient(create_app(system)) as client:
        s=client.get('/api/status',headers={'X-Bot-Pin':'test'}).json()
        assert s['engaged_margin_usd']==0
        assert s['reserved_pending_margin_usd']==pytest.approx(lb.position_margin(p))
