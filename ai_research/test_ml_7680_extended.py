"""Causality and frozen search specification for 7,680 extended policies."""
import numpy as np
from ai_research import ml_7680_extended as E

def test_7680_fixed_candidate_space():
    assert len(E.policies())==192
    assert len(E.model_grid())*len(E.policies())==7680
    assert E.PRE_MDD_LIMIT < E.MDD_GOAL

def test_score_rank_has_no_future_dependency():
    rng=np.random.default_rng(1103)
    values=rng.normal(size=1400)
    a=E.causal_score_rank(values)
    b=values.copy();b[900:]*=-6
    bb=E.causal_score_rank(b)
    np.testing.assert_allclose(a[:900],bb[:900],equal_nan=True)
    assert np.isnan(a[:45]).all()

def test_risk_follows_prior_equity_only():
    rng=np.random.default_rng(32)
    returns=rng.normal(.002,.021,1300)
    pred=E.causal_score_rank(rng.normal(size=1300))
    p=E.policies()[100]
    a,k=E.simulate(returns,pred,p.low,p.mid,p.high,p.q,p.soft,p.hard,p.release)
    later=returns.copy();later[700:]=-.06
    b,z=E.simulate(later,pred,p.low,p.mid,p.high,p.q,p.soft,p.hard,p.release)
    np.testing.assert_array_equal(k[:701],z[:701])
    np.testing.assert_array_equal(a[:700],b[:700])
