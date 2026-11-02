"""Small deterministic safety tests for the isolated AI research runner."""
import numpy as np
import pandas as pd
import pytest
from ai_research.experiment import EPOCH, load_ledger, causal_features, split_masks, choices

def sample():
    d=pd.DataFrame([
        ("main","BTCUSDT",1,1000,1002,100.,-2.),
        ("main","BTCUSDT",1,1001,1300,100.,100.),
        ("main","BTCUSDT",1,1100,1110,100.,-1.),
        ("c3","ETHUSDT",-1,1200,1200,100.,3.),
        ("main","BTCUSDT",1,1300,1310,100.,4.),
    ],columns=["bot","coin","side","entry_min","exit_min","notional","pnl"])
    d["when"]=EPOCH+pd.to_timedelta(d.entry_min,unit="m")
    d["ret"]=d.pnl/d.notional
    return d

def test_features_use_completed_trades_only():
    x=causal_features(sample())
    assert int(x.loc[0,"history_bot_n"])==0
    assert int(x.loc[1,"history_bot_n"])==0
    assert int(x.loc[2,"history_bot_n"])==1
    # The long winner exiting at minute 1300 must not leak into the minute 1300 signal.
    assert int(x.loc[4,"history_bot_n"])==2
    assert np.isclose(x.loc[4,"history_bot_r"],(-.02-.01)/2)

def test_future_label_cannot_change_prior_features():
    d=sample();a=causal_features(d)
    d.loc[1,"pnl"]=1e9;d.loc[1,"ret"]=d.loc[1,"pnl"]/d.loc[1,"notional"]
    b=causal_features(d)
    for i in (0,1,2,3,4):
        np.testing.assert_allclose(a.loc[i,"history_bot_r"],b.loc[i,"history_bot_r"])

def test_fixed_train_validation_split():
    d=sample();d["when"]=pd.to_datetime(["2022-01-01","2023-01-01","2024-08-01","2025-03-01","2026-08-01"],utc=True)
    t,v,h=split_masks(d)
    assert [int(t.sum()),int(v.sum()),int(h.sum())]==[2,1,2]
    assert not (t&v).any() and not (v&h).any()

def test_eligibility_does_not_touch_2025_outcome():
    d=sample()
    d["when"]=pd.to_datetime(["2022-01-01","2023-01-01","2024-08-01","2025-03-01","2026-08-01"],utc=True)
    t,v,h=split_masks(d)
    scores={"toy":np.array([.1,.2,.9,.1,.9])}
    w,a=choices(d,scores,t,v)
    d.loc[h,"ret"]=5000.
    ww,b=choices(d,scores,t,v)
    assert (w is None)==(ww is None)
    assert [(z["threshold"],z["val_unit_delta"]) for z in a]==[(z["threshold"],z["val_unit_delta"]) for z in b]

def test_ledger_count_and_ids():
    d=load_ledger()
    assert len(d)==2991
    assert set(d.bot)=={"main","c3","pa"}
    assert (d.when>=EPOCH).all()
