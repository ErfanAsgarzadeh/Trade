"""The deployed winner's paper aggregation preserves unit risk and restart state."""
import json
from pathlib import Path
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import system,cfg

def setup(system):
 c=lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))
 c['strategy_settings'].update(pyramid_enabled=True,exit_tp_mode='STOP_TRAIL_DONCHIAN10',hard_tp_rr=0.,breakeven_trigger_rr=0.,initial_stop_anchor='SIGNAL')
 c['risk_and_exit']['leverage_mode']='FIXED_LEVERAGE';system.config.write(c);c=system.config.read()
 bar=pd.Series(dict(close=100.,high=102.,low=98.,kijun=95.,atr=1.,timestamp=0))
 p=lb.size_position(system.data,c['symbols'][0],'long',bar,10000,c,'4h');system._insert(p);assert system._activate(p,100.,1_800_000_003)
 with system.db.connect() as db:db.execute('UPDATE positions SET active_sl=106 WHERE symbol=?',(p['symbol'],))
 p=system.db.position(p['symbol']);system.data.prices[p['symbol']]=110.;system.arm_pyramid(p,110.,1_800_000_100)
 return c,system.db.position(p['symbol'])

def test_add_once_half_risk_and_shared_stop(system):
 c,p=setup(system);equity=system.paper_equity();bar=pd.Series(dict(close=110.,timestamp=(1_800_014_400-14400)*1000))
 assert system._pyramid_add(p,'long',bar,c,1_800_014_403)
 combined=system.db.position(p['symbol']);assert combined['active_sl']==p['active_sl'];assert combined['root_entry_price']==100.;assert combined['root_r_distance']==2
 assert combined['qty']>p['qty'] and combined['pyramid_added']==1
 with system.db.connect() as db:unit=dict(db.execute('SELECT * FROM scale_in_history').fetchone())
 assert unit['modeled_risk_usd']<=equity*c['risk_and_exit']['risk_per_trade_pct']*.5+1e-8
 assert not system._pyramid_add(combined,'long',bar,c,1_800_014_404)
 add={**p,'entry_price':unit['entry_price']}
 assert lb.net_pnl(combined,115.,combined['qty'])==pytest.approx(lb.net_pnl(p,115.,p['qty'])+lb.net_pnl(add,115.,unit['qty']))
 assert lb.position_margin(combined)==pytest.approx(lb.position_margin(p)+unit['entry_price']*unit['qty']/5)
 # A fresh engine sees the persisted add flag and the original root risk.
 restart=lb.Engine(system.config,system.db,system.data)
 assert restart.db.position(p['symbol'])['pyramid_added']==1

@pytest.mark.parametrize('kind',['too_early','micro_stop','wrong_side','margin_exhausted'])
def test_invalid_add_blocked(system,kind):
 c,p=setup(system);bar=pd.Series(dict(close=110.,timestamp=(1_800_014_400-14400)*1000));side='long'
 if kind=='too_early':p['pyramid_eligible_ts']=1_800_014_400
 if kind=='micro_stop':p['active_sl']=109.5
 if kind=='wrong_side':side='short'
 if kind=='margin_exhausted':system.available_notional=lambda *args:0.
 assert not system._pyramid_add(p,side,bar,c,1_800_014_403)
 assert system.db.position(p['symbol'])['qty']==p['qty']

def test_not_armed_without_cost_covered_stop(system):
 c,p=setup(system);p['pyramid_eligible_ts']=0.;p['active_sl']=100.01
 system.arm_pyramid(p,110.,1_800_000_100)
 assert p['pyramid_eligible_ts']==0
