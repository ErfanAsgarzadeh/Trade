"""Shared pool removes unit caps without increasing target risk or racing slots."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
import lbank_bot as B,c3_sleeve as C
from test_shared_paper_account import shared,put
from test_system import system,cfg

def config():return B.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))
@pytest.mark.parametrize('slots',[1,4,8])
def test_pool_does_not_divide_risk_or_margin(slots):
 c=config();c['risk_and_exit'].update(max_open_positions=slots,risk_per_trade_pct=.05)
 b=B.entry_budget(10000,.012,c,20000)
 assert b['risk_budget']==500 and b['slot_margin_usd']==4000
 assert b['final_notional']==20000 and b['isolated_leverage']==5
 assert b['final_notional']*.0136<=500
@pytest.mark.parametrize('free',[0,100,6000])
def test_dynamic_pool_never_exceeds_remaining_margin(free):
 c=config();c['risk_and_exit']['leverage_mode']='DYNAMIC_MARGIN'
 b=B.entry_budget(10000,.012,c,free*5)
 assert b['final_notional']/b['isolated_leverage']<=free
 assert b['final_notional']*.0136<=b['risk_budget']+1e-9

def pooled(shared):
 e,a,sl=shared;c=e.config.read();c['portfolio_risk']['margin_allocation_mode']='SHARED_POOL';e.config.write(c)
 sl.c.update(risk_per_trade_pct=.004,max_notional_pct=.4,max_open_positions=4)
 return e,a,sl

def test_c3_uses_target_notional_above_old_cap(shared):
 e,a,sl=pooled(shared);sym='UNI/USDT:USDT';e.data.prices[sym]=100
 assert sl.open(sym,'long',pd.Series(dict(close=100.,atr=.25,timestamp=0)),10)
 p=a.store.positions()[0];n=p['qty']*p['entry']
 assert n>4000 and n*.0066<=40+1e-8
 assert a.snapshot()['reserved_margin_usd']<=a.snapshot()['allowed_margin_usd']

def test_c3_four_slots_atomic_and_reopen_after_close(shared):
 e,a,sl=pooled(shared);syms=sl.c['symbols'][:6];b=pd.Series(dict(close=100.,atr=5.,timestamp=0))
 for s in syms:e.data.prices[s]=100
 with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda s:sl.open(s,'long',b,10),syms))
 assert len(a.store.positions())==4
 # Reducing the live cap only blocks new entries; it does not close existing ones.
 sl.c['max_open_positions']=2
 missing=next(s for s in syms if not any(p['symbol']==s for p in a.store.positions()))
 assert sl.open(missing,'long',b,11) is None and len(a.store.positions())==4
 sl.c['max_open_positions']=4;p=a.store.positions()[0];sl.close(p,100,'test',12)
 assert sl.open(missing,'long',b,13) and len(a.store.positions())==4
@pytest.mark.parametrize('value',[0,True,4.5,101])
def test_invalid_c3_count(value):
 c=json.loads((Path(__file__).parents[1]/'c3_config.json').read_text());c['max_open_positions']=value
 with pytest.raises(ValueError):C.validate(c)
def test_invalid_pool_mode():
 c=config();c['portfolio_risk']['margin_allocation_mode']='invalid'
 with pytest.raises(B.ConfigError):B.validate_config(c)
def test_shipped_request():
 c=config();s=C.load(Path(__file__).parents[1]/'c3_config.json')
 assert c['risk_and_exit']['risk_per_trade_pct']==.0075 and s['risk_per_trade_pct']==.004
 assert c['risk_and_exit']['max_open_positions']==s['max_open_positions']==4
 assert c['bot_control']['dry_run_mode'] and s['dry_run_mode']
