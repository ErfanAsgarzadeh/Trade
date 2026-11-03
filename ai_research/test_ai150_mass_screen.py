"""Anti-lookahead unit tests for the 1010-model risk-layer hypothesis search."""
import numpy as np
import pandas as pd
from ai_research import ai150_mass_screen as S

def test_exactly_1010_unique_trained_model_specs_and_128_risk_wrappers():
    x=S.model_specs()
    assert len(x)==1010
    assert len(set(r["id"] for r in x))==1010
    assert len(set(r["family"] for r in x))==11
    assert len(S.policy_specs())==128

def test_stationary_features_use_only_completed_previous_days():
    n=450;idx=pd.date_range("2021-10-05",periods=n,freq="D",tz="UTC")
    a=np.sin(np.arange(n)/6)*.01+.002
    b=100*np.cumprod(1+.001+np.sin(np.arange(n)/9)*.008)
    x=S.feature_matrix(idx,a,b)
    newer=a.copy();newer[250:]=-.5
    b2=b.copy();b2[250:]=b2[250:]*.7
    y=S.feature_matrix(idx,newer,b2)
    np.testing.assert_allclose(x.iloc[:251].to_numpy(),y.iloc[:251].to_numpy(),
                               equal_nan=True)
    assert not np.allclose(x.iloc[252].to_numpy(),y.iloc[252].to_numpy(),equal_nan=True)

def test_forward_five_day_labels_and_train_purge():
    n=600;idx=pd.date_range("2021-10-05",periods=n,freq="D",tz="UTC")
    r=np.zeros(n);r[454]=.1
    y=S.target_forward_ret(r)
    assert np.isclose(y[450],.1)
    assert np.isclose(y[451],.1)
    assert np.isclose(y[454],.1)
    assert np.isclose(y[455],0.)
    assert np.isnan(y[-1])
    tr,te=S.eligible_masks(idx,y,"2023-01-01","2023-05-01")
    assert tr.sum()>200 and te.any()
    assert idx[tr][-1]+pd.Timedelta(days=S.HORIZON_DAYS-1)<pd.Timestamp("2023-01-01",tz="UTC")
    assert not np.any(tr&te)

def test_model_fits_only_outer_train_and_predicts_percentile_of_train_distribution():
    n=620;idx=pd.date_range("2021-10-05",periods=n,freq="D",tz="UTC")
    rng=np.random.default_rng(10)
    ref=rng.normal(.002,.015,n)
    btc=100*np.cumprod(1+rng.normal(.0002,.014,n))
    x=S.feature_matrix(idx,ref,btc)
    y=S.target_forward_ret(ref)
    cand=S.model_specs()
    for spec in (cand[0],cand[400],cand[550],cand[-1]):
        p,ntr,nte=S.fitted_scores(spec,x,y,idx,"2023-01-01","2023-04-01")
        assert len(p)==nte and ntr>200
        assert np.isfinite(p).all()
        assert (p>=0).all() and (p<=1).all()

def test_counterfactual_future_returns_cannot_change_past_sizing():
    n=450;r=np.sin(np.arange(n)/7)*.02+.001
    q=np.linspace(0,1,n);seen=np.arange(n)>=100
    eq,k=S.overlay(r,q,seen,1.35,3,*S.RISK_CONTROLS[2])
    newer=r.copy();newer[210:]=-.085
    eq2,k2=S.overlay(newer,q,seen,1.35,3,*S.RISK_CONTROLS[2])
    np.testing.assert_array_equal(eq[:210],eq2[:210])
    np.testing.assert_array_equal(k[:211],k2[:211])

def test_daily_loss_guard_is_hypothetical_not_real_broker_stop():
    n=180
    r=np.r_[-.12*np.ones(22),np.zeros(n-22)]
    rank=np.ones(n);seen=np.ones(n,dtype=bool)
    eq,k=S.overlay(r,rank,seen,1.7,3,.05,.11,.1,.12,.09)
    v=np.r_[1.,eq]
    assert 100*np.max(1-v/np.maximum.accumulate(v))<9.01
    assert np.all(k>=0)
