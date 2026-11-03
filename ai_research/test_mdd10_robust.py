"""Conservative bootstrap selection must not read post-2024 labels or prices."""
import numpy as np
import pandas as pd
from ai_research import mdd10_robust as Q
from ai_research.mdd10_frontier import Policy

def test_robust_selection_causally_ignores_future_losses():
    idx=pd.date_range("2021-10-05",periods=1826,tz="UTC")
    r=np.zeros(len(idx))
    sample=np.zeros((4,len(idx)),float)
    p=Policy("constant",.25,0,0,0,0,0,0)
    a=Q.pre_safety(r,idx,p,sample)
    changed=r.copy()
    changed[idx>=pd.Timestamp("2025-01-01",tz="UTC")]=-.8
    b=Q.pre_safety(changed,idx,p,sample)
    assert a==b
    assert a is not None

def test_robust_protocol_fixed():
    assert Q.P95_LIMIT==9.5
    assert Q.B_SELECTION>=100
    assert Q.HIST_STRESS_LIMIT==9.5
