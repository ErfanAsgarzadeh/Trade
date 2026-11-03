"""Out-of-development stress checks: risk-layer policies already selected before 2025.

This is NOT another optimisation. Reads the frozen pre-2025 policy selected
by mdd10_frontier.py, then tests sensitivity to larger negative daily
reference returns, liquidity shocks and block-bootstrap uncertainty.
Do not change the policy parameters using these post-selection results.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass
from pathlib import Path
from .mdd10_frontier import (
 ROOT, OUT, TEST, VAL, Policy, simulate, stats, load_ref,
)

SEED=20261103
BOOTSTRAPS=400
BLOCK=21
EXPECTED_BASE_WORST=.20

def bootstrap_returns(ref,ind,days,blocks=BLOCK,seed=SEED):
    """21-day moving block bootstrap from data PRE-2025 exclusively."""
    z=np.asarray(ref[ind<pd.Timestamp(TEST,tz="UTC")],float)
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,len(z)-blocks,size=(BOOTSTRAPS,int(np.ceil(days/blocks))))
    paths=np.empty((BOOTSTRAPS,days),dtype=float)
    for i,row in enumerate(starts):
        paths[i]=np.concatenate([z[j:j+blocks] for j in row])[:days]
    return paths

def cases():
    # Nonoptimised diagnostic adversity. Time positions chosen before running.
    return {
        "historical":(1.,[]),
        "losses_10pct_larger":(1.10,[]),
        "losses_25pct_larger":(1.25,[]),
        "losses_50pct_larger":(1.50,[]),
        "losses_100pct_larger":(2.00,[]),
        "one_day_minus10_2025":(1.,[("2025-01-15",-.10)]),
        "one_day_minus20_2025":(1.,[("2025-01-15",-.20)]),
        "two_shocks_minus10":(1.,[("2025-01-15",-.10),("2026-05-01",-.10)]),
    }

def stress_returns(original,ix,scale,shocks):
    a=np.asarray(original,float).copy()
    a[a<0]*=scale
    for t,loss in shocks:
        spot=np.where(ix==pd.Timestamp(t,tz="UTC"))[0]
        if len(spot)!=1:raise ValueError("Out-of-range shock")
        a[spot[0]]+=loss
    if np.min(a)<=-1.:raise ValueError("Invalid synthetic -100% shock")
    return a

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    data=json.loads((OUT/"results.json").read_text())
    _,idx,ref=load_ref()
    from .mdd10_frontier import f_proxy_base
    f=f_proxy_base(ref)
    fr=np.diff(np.r_[1.,f])/np.r_[1.,f[:-1]]
    outcome={}
    paths=bootstrap_returns(ref,idx,len(ref))
    holdout=idx>=pd.Timestamp(TEST,tz="UTC")
    for mode,returns,label in [
        ("NoF",ref,"mode_without_F"),
        ("Fstyle_NotRealF",fr,"mode_F_style_proxy_not_F"),
    ]:
        results={}
        for entry in data[label]["results"]:
            if entry["label"]=="baseline":continue
            policy=Policy(**entry["parameters"])
            table={}
            for case,(scale,shocks) in cases().items():
                ret=stress_returns(returns,idx,scale,shocks)
                eq,k=simulate(ret,policy)
                full=stats(eq,idx)
                test=stats(eq,idx,TEST)
                table[case]={"full_mdd":full["mdd"],"full_cagr":full["cagr"],
                             "holdout_mdd":test["mdd"],"holdout_cagr":test["cagr"],
                             "full_below_10":bool(full["mdd"]<10.)}
            dd=np.empty(BOOTSTRAPS,float);cagr=np.empty(BOOTSTRAPS,float)
            for j,seq in enumerate(paths):
                if mode!="NoF":
                    # Apply the reference F-style daily proxy mechanically
                    # per resampled day; cannot reproduce path-dependent F
                    # from bootstrapped price shocks, so do not assert
                    # bootstrap F-style statistics.
                    dd[j]=np.nan;cagr[j]=np.nan;continue
                eq,_=simulate(seq,policy)
                ind=pd.date_range("2021-01-01",periods=len(eq),freq="D",tz="UTC")
                z=stats(eq,ind)
                dd[j]=z["mdd"];cagr[j]=z["cagr"]
            bootstrap=None
            if mode=="NoF":
                bootstrap={"count":BOOTSTRAPS,"block_days":BLOCK,
                           "source":"2021-10-05 to 2024-12-31 only",
                           "mdd_p50":float(np.percentile(dd,50)),
                           "mdd_p90":float(np.percentile(dd,90)),
                           "mdd_p95":float(np.percentile(dd,95)),
                           "freq_mdd_under10":float(np.mean(dd<10)),
                           "cagr_p10":float(np.percentile(cagr,10)),
                           "cagr_p50":float(np.percentile(cagr,50))}
            results[entry["label"]]={"parameters":entry["parameters"],
                                    "scenario_table":table,
                                    "development_block_bootstrap":bootstrap}
        outcome[mode]=results
    out={
      "goal":"MDD < 10% daily-close, including stress robustness",
      "date_range":"2021-10-05 .. 2026-10-04",
      "holdout":"2025-01-01 .. 2026-10-04 not used to select model",
      "model_selection":"frozen from 2024 with 8.3% drawdown safety buffer",
      "scenario_results":outcome,
      "not_verified":[
        "Intraday and real execution DD cannot be bounded by this daily reference method.",
        "Stress scenarios are hypothetical adjustments to past daily equity and not market resimulation.",
        "Block bootstrap is historical uncertainty illustration, not a guarantee of real-world 10% MDD.",
        "Real F is NOT reconstructed; F-style proxy is not the shipped F controller."
      ]
    }
    (OUT/"stress_results.json").write_text(json.dumps(out,indent=2))
    rows=[]
    for mode,versions in outcome.items():
        for name,r in versions.items():
            for case,x in r["scenario_table"].items():
                rows.append({"mode":mode,"policy":name,"scenario":case,**x})
    pd.DataFrame(rows).to_csv(OUT/"stress_cases.csv",index=False)
    print("STRESS_RESULT",json.dumps({
        mode:{label:{
            "base":z["scenario_table"]["historical"],
            "losses_25pct":z["scenario_table"]["losses_25pct_larger"],
            "losses_50pct":z["scenario_table"]["losses_50pct_larger"],
            "bootstrap":z["development_block_bootstrap"]
        } for label,z in v.items()} for mode,v in outcome.items()
    }),flush=True)
    return out

if __name__=="__main__":run()
