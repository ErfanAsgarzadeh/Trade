import pandas as pd
import pytest
import numpy as np
import backtest as bt


def pending(sim,side='long'):
    sign=1 if side=='long' else -1
    sim.p=dict(symbol=bt.SYMBOL,side=side,entry_price=100.0,qty=2.0,initial_sl=100-sign*10,
               active_sl=100-sign*10,tp1_price=100+sign*15,state=bt.bot.PENDING,
               trigger_price=100.0,cancel_price=100-sign*10,expiry_ts=bt.END//1000+3600,
               contract_size=1.0,fee_rate=.0012,tp1_close_pct=.5,tp1_rr=1.5,
               risk_budget=50.0,max_notional=5000.0,signal_ts=bt.START-3600000)


@pytest.mark.parametrize('side',['long','short'])
def test_entry_tp1_and_breakeven(side):
    sim=bt.Simulator();pending(sim,side);sim.enter(100,bt.START)
    sign=1 if side=='long' else -1
    sim.segment(100,100+sign*20,bt.START,bt.START+20000)
    assert sim.p['state']==bt.bot.TRAILING
    assert sim.p['qty']==1
    sim.segment(100+sign*20,100-sign*5,bt.START+20000,bt.START+40000)
    assert sim.p is None
    assert len(sim.history)==2 and len(sim.trades)==1
    assert sim.trades[0]['exit_reason']=='stop'
    assert sim.balance-10000==pytest.approx(sim.trades[0]['net_pnl'])


@pytest.mark.parametrize('side',['long','short'])
def test_initial_stop_has_no_future_target_profit(side):
    sim=bt.Simulator();pending(sim,side);sim.enter(100,bt.START)
    sign=1 if side=='long' else -1
    sim.segment(100,100-sign*15,bt.START,bt.START+20000)
    sim.segment(100-sign*15,100+sign*20,bt.START+20000,bt.START+40000)
    assert sim.p is None
    assert len(sim.history)==1
    assert sim.trades[0]['net_pnl']<0


def test_pending_invalidation_and_expiry():
    sim=bt.Simulator();pending(sim)
    sim.segment(99,85,bt.START,bt.START+20000)
    assert not sim.trades and sim.p is None
    pending(sim);sim.p['expiry_ts']=bt.START//1000
    sim.point(101,bt.START)
    assert not sim.trades and sim.p is None


def test_gap_fill_not_stale_trigger_fill():
    sim=bt.Simulator();pending(sim);sim.point(150,bt.START)
    assert sim.p['entry_price']==150
    assert sim.p['qty']<1
    assert sim.p['qty']*(60+150*.0012)<=50
    assert sim.p['tp1_price']==240


def test_slippage_applied_against_position_and_accounting():
    baseline=bt.Simulator();pending(baseline);baseline.enter(100,bt.START);baseline.close(110,bt.START+60000,'manual')
    costly=bt.Simulator(slippage_bps=2);pending(costly);costly.enter(100,bt.START);costly.close(110,bt.START+60000,'manual')
    assert costly.trades[0]['entry_price']>100
    assert costly.history[0]['exit_price']<110
    assert costly.balance<baseline.balance
    summary=costly.summary()
    assert summary['net_profit']==pytest.approx(summary['gross_profit']-summary['fees'])


@pytest.mark.parametrize('side,expected',[('long',-.2),('short',.2)])
def test_funding_sign_and_profit_reconciliation(side,expected):
    sim=bt.Simulator(funding=True);pending(sim,side);sim.enter(100,bt.START)
    stamp=bt.END-60000
    minutes=pd.DataFrame([[stamp,100,100.1,99.9,100,1]],columns=['timestamp','open','high','low','close','volume'])
    summary=sim.run(minutes,pd.DataFrame(columns=['timestamp']),{}, {stamp:.001})
    assert summary['funding_pnl']==pytest.approx(expected)
    assert summary['net_profit']==pytest.approx(expected-.24)
    assert sim.trades[0]['funding_pnl']==pytest.approx(expected)


def test_optimized_indicators_equal_engine_and_no_future_leak():
    n=500
    timestamp=np.arange(n)*3600000+bt.START
    center=100+np.sin(np.arange(n)/8)*5+np.arange(n)*.02
    raw=pd.DataFrame({'timestamp':timestamp,'open':center,'high':center+1,'low':center-1,'close':center+.1,'volume':100})
    fast=bt.prepare_indicators(raw)
    assert bt.verify_indicator_equivalence(raw,fast,'1h')==25
    prefix=bt.prepare_indicators(raw.iloc[:350])
    pd.testing.assert_frame_equal(fast.iloc[:350].reset_index(drop=True),prefix.reset_index(drop=True))


def test_htf_match_uses_close_time_not_open_time():
    closes=np.array([8*3600000,12*3600000,16*3600000])
    ltf_close=np.array([11*3600000,12*3600000,13*3600000])
    assert (np.searchsorted(closes,ltf_close,side='right')-1).tolist()==[0,1,1]
