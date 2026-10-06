"""Verified ablation fix #4B: post-2R profit floor and safer pyramid (see high_cagr/output/ablation_fixes.json)."""
import copy,json
from pathlib import Path
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import system,cfg
from test_pyramiding import setup

def config():
 return lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))

def open_position(system,side='long',entry=100.,r=2.):
 c=config();system.config.write(c);c=system.config.read();sign=1 if side=='long' else -1
 bar=pd.Series(dict(close=entry,high=entry+2,low=entry-2,kijun=entry-sign*5,atr=1.,timestamp=0))
 p=lb.size_position(system.data,c['symbols'][0],side,bar,10000,c,'4h');system._insert(p);assert system._activate(p,entry,1_800_000_003)
 with system.db.connect() as db:db.execute('UPDATE positions SET active_sl=?,initial_sl=?,root_r_distance=?,initial_r_distance=?,root_entry_price=? WHERE symbol=?',(entry-sign*r,entry-sign*r,r,r,entry,p['symbol']))
 return system.db.position(p['symbol'])

def test_deployed_defaults_are_the_verified_4b_parameters():
 s=config()['strategy_settings']
 assert (s['profit_floor_enabled'],s['profit_floor_trigger_r'],s['profit_floor_lock_r'],s['safe_pyramid_enabled'],s['pyramid_risk_fraction'])==(True,2.0,.25,True,.35)

@pytest.mark.parametrize('side',['long','short'])
def test_floor_triggers_at_2r_and_only_ratchets(system,side):
 sign=1 if side=='long' else -1;p=open_position(system,side)
 system.apply_profit_floor(p,100+sign*3.99);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100-sign*2)
 system.apply_profit_floor(p,100+sign*4.0);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100+sign*.5)
 system.apply_profit_floor(p,100.);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100+sign*.5)   # price falling back never undoes it
 with system.db.connect() as db:db.execute('UPDATE positions SET active_sl=? WHERE symbol=?',(100+sign*3.,p['symbol']))
 system.apply_profit_floor(system.db.position(p['symbol']),100+sign*5);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100+sign*3.)  # never loosens a better trail

def test_floor_off_or_non_donchian_trail_changes_nothing(system):
 p=open_position(system);frozen=json.loads(p['strategy_config'])
 off=copy.deepcopy(frozen);off['strategy_settings']['profit_floor_enabled']=False
 other=copy.deepcopy(frozen);other['strategy_settings']['exit_tp_mode']='CLOSE_TRAIL_KIJUN'
 for variant in (off,other):
  q=dict(p,strategy_config=json.dumps(variant));system.apply_profit_floor(q,110.);assert system.db.position(p['symbol'])['active_sl']==pytest.approx(98.)

def test_watchdog_applies_floor_then_stops_out_at_it(system):
 p=open_position(system);system.data.prices[p['symbol']]=104.5;system.watchdog(1_800_000_100)
 assert system.db.position(p['symbol'])['active_sl']==pytest.approx(100.5)
 system.data.prices[p['symbol']]=100.4;system.watchdog(1_800_000_200)
 assert system.db.position(p['symbol']) is None   # stopped at the floor instead of round-tripping to the old stop

def test_legacy_config_keeps_legacy_behaviour_and_validates_ranges():
 c=config();legacy=copy.deepcopy(c)
 for k in ('profit_floor_enabled','profit_floor_trigger_r','profit_floor_lock_r','safe_pyramid_enabled','pyramid_risk_fraction'):legacy['strategy_settings'].pop(k)
 s=lb.validate_config(legacy)['strategy_settings'];assert (s['profit_floor_enabled'],s['safe_pyramid_enabled'],s['pyramid_risk_fraction'])==(False,False,.5)
 for key,value in (('profit_floor_lock_r',2.0),('profit_floor_trigger_r',0),('pyramid_risk_fraction',1.5),('pyramid_risk_fraction',.01)):
  bad=copy.deepcopy(c);bad['strategy_settings'][key]=value
  with pytest.raises(lb.ConfigError):lb.validate_config(bad)

def test_pyramid_add_uses_configured_risk_fraction(system):
 c,p=setup(system);equity=system.paper_equity();bar=pd.Series(dict(close=110.,timestamp=(1_800_014_400-14400)*1000))
 assert system._pyramid_add(p,'long',bar,c,1_800_014_403)
 with system.db.connect() as db:unit=dict(db.execute('SELECT * FROM scale_in_history').fetchone())
 limit=equity*c['risk_and_exit']['risk_per_trade_pct']*.35;assert unit['modeled_risk_usd']<=limit+1e-8 and unit['modeled_risk_usd']>.9*limit

def test_safe_pyramid_blocks_add_that_would_make_stopout_a_net_loss(system):
 c,p=setup(system);bar=pd.Series(dict(close=110.,timestamp=(1_800_014_400-14400)*1000))
 weak=dict(p,active_sl=100.2)   # covers entry costs (passes arming) but not the add-on's 10-point gap
 assert not system._pyramid_add(weak,'long',bar,c,1_800_014_403) and system.db.position(p['symbol'])['qty']==p['qty']
 legacy=copy.deepcopy(c);legacy['strategy_settings']['safe_pyramid_enabled']=False
 frozen=json.loads(p['strategy_config']);frozen['strategy_settings']['safe_pyramid_enabled']=False
 assert system._pyramid_add(dict(weak,strategy_config=json.dumps(frozen)),'long',bar,legacy,1_800_014_403)   # without the guard the same add goes through
