"""Causal system return + BTC hedge and fee accounting audit."""
import numpy as np
import pandas as pd
from ai_research.mdd10_growth_hedge import Configuration,simulate,grid,rank_dev,ROUND_SIDE,CARRY

def test_hedge_costs_and_short_payoff():
    r=np.zeros(100);b=np.zeros(100);b[10]=-.10
    bear=np.zeros(100,bool);bear[10]=True
    p=Configuration("test",0.,0,0,1.,1.,"always",0,1,0,0)
    eq,k,h=simulate(r,b,bear,p)
    assert eq[9]==1.
    assert eq[10]>1.09
    assert h[10]==1 and h[11]==0
    # 1 hedge buy-and-sell commission+slippage and the short carrying drag
    assert np.isclose(eq[10],1+.1-ROUND_SIDE-CARRY,atol=1e-10)
    assert eq[11]<eq[10]

def test_trade_risk_decision_no_future_inputs():
    gen=np.random.default_rng(11)
    r=gen.normal(.002,.025,300)
    b=gen.normal(.001,.020,300)
    sig=np.array([i%3==0 for i in range(300)])
    p=Configuration("test",1.,.04,.09,.2,.5,"bear50",.01,1.5,.08,.09)
    eq,k,h=simulate(r,b,sig,p)
    r2=r.copy();b2=b.copy();s2=sig.copy()
    r2[170:]=.08
    b2[170:]=-.11
    s2[171:]=~s2[171:]
    eq2,k2,h2=simulate(r2,b2,s2,p)
    np.testing.assert_array_equal(eq[:170],eq2[:170])
    np.testing.assert_array_equal(k[:171],k2[:171])
    assert not np.array_equal(eq[171:],eq2[171:])

def test_growth_grid_is_frozen_and_contains_hedges():
    g=grid()
    assert len(g)>500
    assert any(x.hedge>=1 for x in g)
    assert all(x.market in ("bear50","bear100","bearmom","bear50mom") for x in g)
    assert ROUND_SIDE==.0007
    assert CARRY>0

def test_development_gate_ignores_2025():
    ix=pd.date_range("2021-10-05",periods=1826,tz="UTC")
    eq=np.cumprod(1+.001*np.sin(np.arange(len(ix))))
    score=rank_dev(eq,ix)
    z=eq.copy();z[ix>=pd.Timestamp("2025-01-01",tz="UTC")]*=.05
    assert rank_dev(z,ix)==score
