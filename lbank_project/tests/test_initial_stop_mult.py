"""initial_stop_atr_mult: the ATR2 initial stop distance is configurable (default 2.0 = previous behaviour)."""
import copy,json
from pathlib import Path
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import system,cfg

def config(mult=None):
    c=lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))
    if mult is not None:c['strategy_settings']['initial_stop_atr_mult']=mult
    return lb.validate_config(c)

@pytest.mark.parametrize('side',['long','short'])
@pytest.mark.parametrize('mult',[2.0,2.5])
def test_stop_distance_follows_multiplier(system,side,mult):
    c=config(mult);sign=1 if side=='long' else -1
    bar=pd.Series(dict(close=100.,high=101.,low=99.,kijun=100.-sign*5,atr=1.,timestamp=0))
    p=lb.size_position(system.data,c['symbols'][0],side,bar,10000,c,'4h')
    assert p['initial_sl']==pytest.approx(100.-sign*mult) and p['initial_r_distance']==pytest.approx(mult)

def test_deployed_and_legacy_default_is_two():
    assert config()['strategy_settings']['initial_stop_atr_mult']==2.0
    legacy=copy.deepcopy(config());legacy['strategy_settings'].pop('initial_stop_atr_mult')
    assert lb.validate_config(legacy)['strategy_settings']['initial_stop_atr_mult']==2.0

@pytest.mark.parametrize('bad',[0.5,6.0])
def test_out_of_range_rejected(bad):
    c=config();c['strategy_settings']['initial_stop_atr_mult']=bad
    with pytest.raises(lb.ConfigError):lb.validate_config(c)

def test_wider_stop_means_smaller_position_same_risk(system):
    bar=pd.Series(dict(close=100.,high=101.,low=99.,kijun=95.,atr=1.,timestamp=0))
    a=lb.size_position(system.data,config(2.0)['symbols'][0],'long',bar,10000,config(2.0),'4h')
    b=lb.size_position(system.data,config(2.5)['symbols'][0],'long',bar,10000,config(2.5),'4h')
    assert b['qty']<a['qty'] and b['risk_budget']==pytest.approx(a['risk_budget'])
