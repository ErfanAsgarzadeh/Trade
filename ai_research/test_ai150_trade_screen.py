"""Test strict exit-time causality and trade-only AI selection invariants."""
import numpy as np
import pandas as pd
from ai_research import ai150_trade_screen as S
from ai_research import seven_benchmark as B
from ai_research import ai150_mass_screen as A

def fake_roots(n=800):
    times=np.arange(n)*1440
    rand=np.random.default_rng(2027)
    roots=pd.DataFrame({c:rand.normal(0,.2,n) for c in B.COLS})
    roots["em"]=times
    roots["root_exit_min"]=times+240
    roots["bot"]=np.resize(["main","c3","pa"],n)
    roots["side"]=np.where(np.arange(n)%2==0,1,-1)
    roots["coin"]=np.resize(["BTC","ETH","SOL","XRP"],n)
    roots["realized_r"]=rand.normal(.25,1.15,n)
    roots["entry_date"]=B.ORIGIN+pd.to_timedelta(times,unit="m")
    roots["root"]=np.arange(n)
    return roots

def test_historical_trade_expectancy_only_includes_closed_past():
    d=fake_roots(80)
    d.loc[0,"realized_r"]=10.
    d.loc[0,"root_exit_min"]=d.loc[12,"em"]+10
    x,cols,cats=S.features(d)
    assert x.loc[1,"closed_all_n"]==0.
    assert np.isclose(x.loc[13,"closed_all_n"],np.log1p(12))
    assert all(col in x for col in cols)
    assert cats==["bot","side","coin"]

def test_2023_2024_expanding_folds_purge_pending_exits():
    d=fake_roots(1200)
    tr,te=S.train_masks(d,"2023-01-01","2024-01-01")
    assert tr.any() and te.any()
    assert not np.any(tr&te)
    fold=(pd.Timestamp("2023-01-01",tz="UTC")-B.ORIGIN).total_seconds()/60
    assert np.all(d.loc[tr,"root_exit_min"]+B.EMBARGO_MINUTES<fold)

def test_train_only_fits_real_models_and_percentiles():
    d=fake_roots(930)
    t,cols,cats=S.features(d)
    specs=A.model_specs()
    for spec in (specs[0],specs[450],specs[-1]):
        ranks,mask,ntr,nte=S.fit_predict(spec,t,cols,cats,"2023-01-01","2024-01-01")
        assert ntr>150 and nte>40
        assert len(ranks)==nte and mask.sum()==nte
        assert (ranks>=0).all() and (ranks<=1).all()
        assert np.isfinite(ranks).all()

def test_surrogate_dev_score_ignores_future_2025_26_labels():
    d=fake_roots(1800)
    q=np.resize([.1,.7,.9],len(d)).astype(float)
    seen=np.ones(len(d),dtype=bool)
    a=S.surrogate_score(d,q,seen,1,.5)
    changed=d.copy()
    changed.loc[changed.entry_date>=pd.Timestamp("2025-01-01",tz="UTC"),"realized_r"]=-50.
    b=S.surrogate_score(changed,q,seen,1,.5)
    assert a==b

def test_risk_size_gate_bounds_and_exact_policy_count():
    p=np.linspace(0,1,400)
    assert len(S.POLICIES)*len(S.SHORT_FACTORS)==27
    for i in S.POLICIES:
        v=S.size_rule(p,i)
        assert len(v)==len(p)
        assert v.min()>=0 and v.max()<=2.
