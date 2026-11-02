"""Execution adapter invariants: fees, slip, funding, tie and next open."""
import numpy as np
import pandas as pd
import pytest
from ai_research.strict_execution import trades_from_signals,FEE_PER_SIDE,SLIPPAGE_PER_SIDE

def fixtures():
    ix=pd.date_range("2023-01-01 00:01",periods=6,freq="min",tz="UTC")
    bars=pd.DataFrame({"open":[100,101,101,102,102,102],
                        "high":[100.5,105,103,105,104,104],
                        "low":[99.5,99,101,100,99,101],
                        "close":[100,102,102,102,102,102]},index=ix)
    return bars,ix

def test_next_bar_entry_stop_wins_tie_and_two_sided_cost():
    bars,ix=fixtures()
    s=pd.DataFrame({"timestamp":[ix[0]],"signal":[1],"stop_price":[100],
                    "target_price":[104],"max_hold_bars":[4]})
    out=trades_from_signals(bars,s,instrument_type="spot")
    assert len(out)==1
    r=out.iloc[0]
    assert r.entry_time==ix[1]
    assert r.exit_time==ix[1]
    assert r.exit_cause=="SL"
    assert np.isclose(r.entry_fill,101*(1+SLIPPAGE_PER_SIDE))
    assert np.isclose(r.exit_fill,100*(1-SLIPPAGE_PER_SIDE))
    assert np.isclose(r.fees_per_unit,FEE_PER_SIDE*(r.entry_fill+r.exit_fill))

def test_perpetual_funding_is_mandatory_and_deducted():
    bars,ix=fixtures()
    bars.loc[ix[1]:,"high"]=103
    bars.loc[ix[1]:,"low"]=101
    s=pd.DataFrame({"timestamp":[ix[0]],"signal":[1],"stop_price":[98],
                    "target_price":[110],"max_hold_bars":[3]})
    with pytest.raises(ValueError,match="funding"):
        trades_from_signals(bars,s,instrument_type="perpetual")
    f=pd.Series([0,.001,.002,.004,.006,.008],index=ix)
    a=trades_from_signals(bars,s,funding_cumulative=f,instrument_type="perpetual")
    b=trades_from_signals(bars,s,instrument_type="spot")
    assert len(a)==len(b)==1
    assert a.iloc[0].funding_per_unit>0
    assert np.isclose(a.iloc[0].net_pnl_per_unit,
                      b.iloc[0].net_pnl_per_unit-a.iloc[0].funding_per_unit)

def test_refuse_invalid_barriers_and_future_timestamp():
    bars,ix=fixtures()
    s=pd.DataFrame({"timestamp":[ix[0]],"signal":[1],"stop_price":[103],
                    "target_price":[110],"max_hold_bars":[2]})
    with pytest.raises(ValueError,match="ordering"):
        trades_from_signals(bars,s,instrument_type="spot")
    s["timestamp"]=ix[-1]+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="no CLOSED"):
        trades_from_signals(bars,s,instrument_type="spot")
