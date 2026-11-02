"""Safety invariants for 20d conformal risk allocation vs daily proxy."""
import numpy as np
import pandas as pd
from ai_research.cdra_daily import features,future_tail,sim_proxy,risk_gates,START,VAL_START,TEST_START

def series():
    idx=pd.date_range(START,periods=1500,freq="D",tz="UTC")
    t=np.arange(len(idx))
    r=np.sin(t/13)*.0025+.001
    b=pd.Series(100*np.cumprod(1+np.sin(t/19)*.003+.0003),index=idx)
    return idx,r,b

def test_features_cannot_peek_at_day_or_future():
    idx,r,b=series()
    original=features(idx,r,b)
    d=1050
    changed=r.copy();changed[d:]+=0.005
    b2=b.copy();b2.iloc[d:]*=1.5
    modified=features(idx,changed,b2)
    np.testing.assert_allclose(original.loc[idx[:d+1]].to_numpy(),
                               modified.loc[idx[:d+1]].to_numpy(),equal_nan=True)
    assert not np.allclose(original.iloc[d+2].to_numpy(),
                           modified.iloc[d+2].to_numpy(),equal_nan=True)

def test_future_target_exact_and_last_horizon_missing():
    r=np.array([.1,-.2,.1,.1,.1])
    y=future_tail(r,h=3)
    assert np.isclose(y[0],-.12)
    assert np.isclose(y[1],-.2)
    assert np.isnan(y[-1]) and np.isnan(y[-2])

def test_sim_uses_only_past_returns_for_sizing():
    idx,r,b=series()
    scale=np.ones(len(r))
    q,k=sim_proxy(r,scale)
    r2=r.copy();r2[500:]=0.15
    q2,k2=sim_proxy(r2,scale)
    np.testing.assert_allclose(k[:501],k2[:501],rtol=0,atol=0)
    assert np.isfinite(q).all() and np.isfinite(q2).all()
    assert np.all((k>=0)&(k<=3.))

def test_gates_are_fixed_without_validation_or_test_knowledge():
    idx,r,b=series()
    loss=np.full(len(r),-.03)
    loss[:500]=-.03 + np.sin(np.arange(500)/30)*.01
    a,_=risk_gates(loss,idx)
    changed=loss.copy()
    changed[idx>=VAL_START]=-.5
    out,_=risk_gates(changed,idx)
    # future can change its OWN decision but not earlier calibrated thresholds
    for n in a:
        np.testing.assert_allclose(a[n][idx<VAL_START],out[n][idx<VAL_START])
        assert np.all(a[n][idx<VAL_START]==1.)
        assert np.isfinite(a[n]).all()
