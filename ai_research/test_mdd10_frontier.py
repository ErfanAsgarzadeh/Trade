"""Risk-layer causality, no future leakage, drawdown-bound math and split tests."""
import numpy as np
import pandas as pd
from ai_research import mdd10_frontier as R

def test_policy_grid_and_safe_baseline():
    cand=R.candidates()
    assert len(cand)>200
    assert {"constant","dd_brake","stress_budget","hybrid"}==set(p.family for p in cand)
    r=np.zeros(300)
    p=R.Policy("constant",.28,0,0,0,0,0,0)
    e,k=R.simulate(r,p)
    np.testing.assert_allclose(e,1.)
    np.testing.assert_allclose(k,.28)

def test_returns_from_future_cannot_change_earlier_sizing():
    g=np.random.default_rng(22)
    r=g.normal(.002,.024,800)
    p=R.Policy("hybrid",.9,.04,.085,.02,.008,.16,.085)
    e,k=R.simulate(r,p)
    changed=r.copy()
    changed[350:]=g.normal(-.04,.07,450)
    e2,k2=R.simulate(changed,p)
    np.testing.assert_array_equal(e[:350],e2[:350])
    np.testing.assert_array_equal(k[:351],k2[:351])
    assert not np.array_equal(k[400:],k2[400:])

def test_shock_budget_mathematically_caps_daily_close_dd():
    # With all future realized benchmark daily losses >= -specified shock,
    # the upper bound on daily MDD is the PRE-SPECIFIED budget, no foresight.
    r=np.r_[-.15*np.ones(20),.02*np.ones(80)]
    p=R.Policy("budget",1.1,0,0,0,0,.15,.085)
    eq,k=R.simulate(r,p)
    index=pd.date_range("2022-01-01",periods=len(eq),tz="UTC")
    dd=R.stats(eq,index)["mdd"]
    assert dd<=8.500001
    assert np.isfinite(eq).all() and np.all((k>=0)&(k<=1.6))

def test_selection_only_uses_pre_2025():
    idx=pd.date_range(R.START,periods=1826,tz="UTC")
    rng=np.random.default_rng(11)
    r=rng.normal(.002,.011,len(idx))
    p=R.Policy("hybrid",.8,.04,.08,.02,.007,.15,.08)
    eq,_=R.simulate(r,p)
    score=R.score_before_2025(eq,idx)
    r2=r.copy()
    r2[idx>=pd.Timestamp("2025-01-01",tz="UTC")]=-0.12
    eq2,_=R.simulate(r2,p)
    assert R.score_before_2025(eq2,idx)==score

def test_no_fake_F_label_and_daily_close_limitations():
    import inspect
    s=inspect.getsource(R.main)
    assert "mode_F_style_proxy_not_F" in s
    assert "real_F_replay_status" in s
    assert R.SEED==10000
