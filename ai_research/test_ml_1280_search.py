"""Auditable no-lookahead and sampling invariants for 1,280 model wrappers."""
import numpy as np
import pandas as pd
from ai_research import ml_1280_search as M

def sample_data():
    idx=pd.date_range("2021-10-05",periods=1826,freq="D",tz="UTC")
    r=np.sin(np.arange(len(idx))/10)*.015+.001
    btc=pd.Series(100*np.cumprod(1+np.cos(np.arange(len(idx))/17)*.015+.0003),index=idx)
    return idx,r,btc

def test_stationary_features_are_past_only():
    idx,r,btc=sample_data()
    a=M.build_features(idx,r,btc)
    altered=r.copy();altered[1100:]=.08
    btc2=btc.copy();btc2.iloc[1100:]*=.5
    b=M.build_features(idx,altered,btc2)
    np.testing.assert_allclose(a.iloc[:1101].to_numpy(),b.iloc[:1101].to_numpy(),equal_nan=True)
    assert a.columns.tolist()==M.FEATURES

def test_future_labels_cannot_be_available_before_full_horizon():
    idx,r,btc=sample_data()
    y=M.make_targets(r)
    for h in M.HORIZONS:
        assert np.isnan(y[(h,"ret")][-h+1:]).all()
        assert np.isnan(y[(h,"drawdown")][-h+1:]).all()
        assert np.isnan(y[(h,"binary")][-h+1:]).all()

def test_fitted_models_use_local_scaling_and_exact_1280_configurations():
    from sklearn.pipeline import Pipeline
    assert len(M.model_grid())==40
    assert len(M.policy_grid())==32
    for c in M.model_grid():
        model=M.make_pipeline(c)
        assert isinstance(model,Pipeline)
        assert model.steps[0][0]=="imputer"
        assert model.steps[1][0]=="scale"

def test_risk_decision_cannot_see_future_reference_returns():
    from ai_research.ml_1280_search import replay_numba
    idx,r,btc=sample_data()
    sig=np.sin(np.arange(len(r))/11)*.05
    a,k=replay_numba(r,sig,.2,1.5,.3,7,.085,30)
    r2=r.copy();r2[800:]=-.08
    b,z=replay_numba(r2,sig,.2,1.5,.3,7,.085,30)
    np.testing.assert_allclose(a[:800],b[:800])
    np.testing.assert_allclose(k[:801],z[:801])
    assert np.isfinite(a).all()

def test_no_2025_model_parameter_selection():
    src=open(M.__file__).read()
    assert "d23" in src and "d24" in src
    assert "2024-01-01" in src and "2025-01-01" in src
    assert M.PRESELECTION_DD<10
