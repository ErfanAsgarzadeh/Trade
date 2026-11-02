"""Checks: all validation folds purge overlapping labels and no test smoothing."""
import numpy as np
import pandas as pd
from ai_research import seven_benchmark as S
from ai_research.walkforward_features import make_features,align_signals

def test_purge_uses_matured_exit_before_train_cutoff():
    t=pd.DataFrame({
        "em":[0,20000,30000,40000,70000,90000],
        "root_exit_min":[10000,69000,50000,60000,80000,91000],
    })
    lo=S.ORIGIN+pd.Timedelta(minutes=75000)
    hi=lo+pd.Timedelta(minutes=10000)
    train,test=S.masks(t,lo,hi)
    # 20*240=4800 minute embargo
    assert train.tolist()==[True,True,True,True,False,False]
    assert test.tolist()==[False,False,False,False,False,False]
    for i in np.flatnonzero(train):
        assert t.root_exit_min.iloc[i]<75000-S.EMBARGO_MINUTES

def test_all_signal_features_causal_to_later_ohlcv():
    ix=pd.date_range("2022-01-01 04:00",periods=460,freq="4h",tz="UTC")
    v=100.+np.cumsum(np.sin(np.arange(len(ix))/15)*.3+.04)
    d=pd.DataFrame({"open":v-.05,"high":v+.3,"low":v-.4,
                    "close":v,"volume":200+np.arange(len(ix))%37},index=ix)
    a=make_features(d)
    mutated=d.copy()
    mutated.iloc[350:,mutated.columns.get_loc("close")]*=1.5
    mutated.iloc[350:,mutated.columns.get_loc("open")]*=1.5
    mutated.iloc[350:,mutated.columns.get_loc("high")]*=1.5
    mutated.iloc[350:,mutated.columns.get_loc("low")]*=1.5
    b=make_features(mutated)
    np.testing.assert_allclose(a.iloc[:349].to_numpy(),b.iloc[:349].to_numpy(),equal_nan=True)
    signals=pd.DataFrame({"timestamp":[ix[300]],"signal":[1]})
    j=align_signals(signals,d)
    assert np.isclose(j.loc[0,"atr_pct"],a.loc[ix[300],"atr_pct"])

def test_hmm_forward_filter_no_future_smoothing():
    from hmmlearn.hmm import GaussianHMM
    rng=np.random.default_rng(3)
    x=rng.normal(0,.25,size=(150,2))
    h=GaussianHMM(n_components=3,covariance_type="diag",min_covar=.01,random_state=11,n_iter=20)
    h.fit(x[:120])
    a=S.hmm_filter(h,x)
    z=x.copy();z[100:]=20
    b=S.hmm_filter(h,z)
    np.testing.assert_allclose(a[:100],b[:100],rtol=0,atol=1e-12)
    np.testing.assert_allclose(a.sum(axis=1),np.ones(150),atol=1e-8)

def test_seven_method_names_fixed():
    assert len(S.NAMES)==7
    assert "Baseline" in S.NAMES[0]
    assert len(S.fold_boundaries())>=7

def test_explicit_source_fee_and_F_gate():
    import inspect
    text=inspect.getsource(S.daily_realized_replay)
    assert "fees=.0012;slip=.0004" in text
    assert "F-style" in inspect.getsource(S.benchmark)
