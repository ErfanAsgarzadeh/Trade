"""Stress suite cannot tune winners or reach into post-2024 sample."""
import numpy as np
import pandas as pd
from ai_research import mdd10_stress as S

def test_bootstrap_cannot_access_2025_plus():
    idx=pd.date_range("2021-10-05",periods=1826,freq="D",tz="UTC")
    x=np.sin(np.arange(len(idx)))*.01
    y=x.copy();y[idx>=pd.Timestamp("2025-01-01",tz="UTC")]=-.5
    a=S.bootstrap_returns(x,idx,250)
    b=S.bootstrap_returns(y,idx,250)
    np.testing.assert_array_equal(a,b)
    assert a.shape==(S.BOOTSTRAPS,250)

def test_fixed_shocks_are_deterministic():
    idx=pd.date_range("2025-01-01",periods=200,freq="D",tz="UTC")
    x=np.ones(len(idx))*.01;x[12]=-.05
    a=S.stress_returns(x,idx,1.25,[("2025-01-15",-.10)])
    assert np.isclose(a[12],-.0625)
    assert np.isclose(a[14],-.09)
    assert np.isclose(a[11],.01)
    assert np.array_equal(x,S.stress_returns(x,idx,1.,[]))

def test_scenarios_frozen():
    assert "losses_50pct_larger" in S.cases()
    assert "one_day_minus20_2025" in S.cases()
    assert S.SEED==20261103
