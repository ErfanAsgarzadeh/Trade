"""Stop-width filter ("V2"): skip >5.6% 2*ATR stops, halve risk for 4.5-5.6%. On in the deployed config, off for legacy configs."""
import copy,json
from pathlib import Path
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import system,cfg

def config(enabled):
 c=lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()));c['strategy_settings']['stop_width_filter_enabled']=enabled;return c

def signal(system,c,width_pct):
 """Signal bar whose 2*ATR stop is `width_pct` of price (close 100)."""
 bar=pd.Series(dict(close=100.,high=101.,low=99.,kijun=95.,atr=width_pct/2,timestamp=0))
 return lb.size_position(system.data,c['symbols'][0],'long',bar,10000,c,'4h')

def test_deployed_has_declared_v2_and_legacy_configs_default_off():
 deployed=json.loads((Path(__file__).parents[1]/'config.json').read_text())['strategy_settings']
 assert deployed['stop_width_filter_enabled'] is True and (deployed['stop_width_skip_pct'],deployed['stop_width_mid_pct'],deployed['stop_width_mid_risk_fraction'])==(.056,.045,.5)   # the declared V2 rule
 legacy=config(False)
 for k in ('stop_width_filter_enabled','stop_width_skip_pct','stop_width_mid_pct','stop_width_mid_risk_fraction'):legacy['strategy_settings'].pop(k)
 assert lb.validate_config(legacy)['strategy_settings']['stop_width_filter_enabled'] is False

@pytest.mark.parametrize('width,expected',[(3.,1.),(4.5,1.),(4.6,.5),(5.6,.5),(5.7,None),(9.,None)])
def test_bands_match_the_backtest_rule(system,width,expected):
 p=signal(system,config(True),width)
 if expected is None:assert p is None
 else:assert p['risk_mult']==expected

def test_disabled_changes_nothing(system):
 for width in (3.,5.,8.):
  p=signal(system,config(False),width);assert p is not None and p['risk_mult']==1.0

def test_half_risk_survives_activation_at_the_fill(system):
 """_activate re-sizes from the live config at fill time: the halving must not be lost there."""
 sizes={}
 for enabled,width in ((False,5.),(True,5.)):
  c=config(enabled);system.config.write(c);c=system.config.read()
  with system.db.connect() as db:db.execute('DELETE FROM positions')
  p=signal(system,c,width);system._insert(p);assert system._activate(p,100.,1_800_000_003);sizes[enabled]=system.db.position(p['symbol'])
 assert sizes[True]['risk_budget']==pytest.approx(sizes[False]['risk_budget']/2) and sizes[True]['qty']==pytest.approx(sizes[False]['qty']/2,rel=1e-6)

def test_validation_rejects_bad_bands():
 for key,value in (('stop_width_mid_pct',.06),('stop_width_skip_pct',.7),('stop_width_mid_pct',.005),('stop_width_mid_risk_fraction',0.),('stop_width_mid_risk_fraction',1.5)):
  bad=config(True);bad['strategy_settings'][key]=value
  with pytest.raises(lb.ConfigError):lb.validate_config(bad)
