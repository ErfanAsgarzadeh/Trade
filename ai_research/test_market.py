"""Prove strict lag of BTC market context with synthetic 4h bars."""
import numpy as np
import pandas as pd
from ai_research.btc_market import completed_market_features, join_at_entry
from ai_research.experiment import EPOCH

def test_market_regime_reads_no_partial_or_future_bar():
    ix=pd.date_range("2021-08-01",periods=260,freq="4h",tz="UTC")
    close=np.linspace(100,160,len(ix))
    b=pd.DataFrame({"open":close,"high":close+2,"low":close-2,"close":close},index=ix)
    f=completed_market_features(b)
    # At the 220th bar open only previous (219th) bar is completed
    t=ix[220]
    d=pd.DataFrame({"when":[t,t+pd.Timedelta(minutes=60),t+pd.Timedelta(hours=4)]})
    a=join_at_entry(d,f)
    assert a.loc[0,"btc_r1d"]==a.loc[1,"btc_r1d"]
    assert a.loc[2,"btc_r1d"]!=a.loc[0,"btc_r1d"]
    before=a.loc[0,"btc_r1d"]
    b.loc[t:,"close"]*=3
    b.loc[t:,"open"]*=3
    b.loc[t:,"high"]*=3
    b.loc[t:,"low"]*=3
    new=join_at_entry(d,completed_market_features(b))
    assert new.loc[0,"btc_r1d"]==before
    assert new.loc[1,"btc_r1d"]==before
