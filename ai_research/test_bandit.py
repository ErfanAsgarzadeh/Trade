"""Causal, normalization and bounded-risk controls for the online expert allocator."""
import numpy as np
from ai_research.bandit_on_f import weights,BOTS,CANDIDATES

def leg(bot,closed,unit=20):
    return dict(bot=bot,xm=closed,em=max(0,closed-100),entry=100.,
                stop_frac=.05,unit=unit,side=1)

def test_weights_do_not_use_future_trade_outcome():
    L=[leg("main",1440*10,100),leg("main",1440*11,20),
       leg("c3",1440*12,-10),leg("pa",1440*13,5),
       leg("main",1440*20,200),leg("main",1440*21,-40)]
    a=weights(L,CANDIDATES["oem_30"],days=40)
    v=[dict(x) for x in L]
    v[-1]["unit"]=10000.
    b=weights(v,CANDIDATES["oem_30"],days=40)
    for bot in BOTS:
        np.testing.assert_array_equal(a[bot][:22],b[bot][:22])
    assert a["main"][30] != b["main"][30]

def test_weights_bounded_and_risk_normalized():
    L=[]
    for d in range(10,110):
        for b,j in zip(BOTS,(20,-10,1)):
            L.append(leg(b,1440*d,j))
    for cfg in CANDIDATES.values():
        a=weights(L,cfg,days=120)
        v=np.array([a[b] for b in BOTS])
        assert np.all(np.isfinite(v)) and np.all(v>0)
        np.testing.assert_allclose(v.mean(axis=0),1,atol=1e-12)
        assert np.max(v)<2 and np.min(v)>0.35

def test_no_current_day_use():
    L=[leg("main",1440*10,100) for _ in range(16)]
    a=weights(L,CANDIDATES["oem_30"],days=16)
    np.testing.assert_allclose([a[b][10] for b in BOTS],[1,1,1])
    assert a["main"][11]>1
