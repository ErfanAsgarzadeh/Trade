"""Second-stage exploratory resilience selection using only PRE-2025 blocks.

This study was designed AFTER the first-stage 2025 result was inspected.
Therefore its 2025-26 evaluation is *NOT a pristine research-design
holdout*, even though algorithm uses ONLY pre-2025 to fit/select params.
Forward PAPER must provide new validation before deployment.

Select a policy by 2024 CAGR with: pre2025 MDD<=8.3%, pre2025
losses +25% MDD<=9.5%, and 5-year synthetic pre2025 21-day block
bootstrap 95th percentile MDD<9.5%. No future-derived features.
"""
import json
import numpy as np
import pandas as pd
from dataclasses import asdict
from .mdd10_frontier import (
    OUT,Policy,candidates,load_ref,simulate,stats,score_before_2025,VAL,TEST
)
from .mdd10_stress import bootstrap_returns,stress_returns,BOOTSTRAPS

B_SELECTION=140
P95_LIMIT=9.5
HIST_STRESS_LIMIT=9.5

def pre_safety(r,ix,p,bootstrap):
    eq,_=simulate(r,p)
    select=score_before_2025(eq,ix)
    if not np.isfinite(select):return None
    adverse=stress_returns(r,ix,1.25,[])
    e2,_=simulate(adverse,p)
    bad=stats(e2,ix,None,TEST)
    if bad["mdd"]>HIST_STRESS_LIMIT:return None
    dd=np.empty(len(bootstrap))
    for j,seq in enumerate(bootstrap):
        e,_=simulate(seq,p)
        dd[j]=100*np.max(1-np.r_[1.,e]/np.maximum.accumulate(np.r_[1.,e]))
    p95=float(np.quantile(dd,.95))
    if p95>=P95_LIMIT:return None
    return {"validation_score":select,"development_plus25_loss_mdd":bad["mdd"],
            "development_bootstrap_p95":p95,
            "development_bootstrap_under10":float((dd<10).mean())}

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    _,idx,r=load_ref()
    from .mdd10_frontier import f_proxy_base
    proxy=f_proxy_base(r)
    proxy_r=np.diff(np.r_[1.,proxy])/np.r_[1.,proxy[:-1]]
    rows={};all_curves={}
    for key,source in (("NoF",r),("Fstyle_NotRealF",proxy_r)):
        sample=bootstrap_returns(source,idx,len(source))[:B_SELECTION]
        surviving=[]
        print("ROBUST_SEARCH",key,"candidates",len(candidates()),"bootstrap",len(sample),flush=True)
        for p in candidates():
            v=pre_safety(source,idx,p,sample)
            if v is None:continue
            surviving.append((v["validation_score"],p,v))
        if not surviving:
            rows[key]={"selected":None,"reason":"no candidate met pre-2025 robustness gate"}
            print("ROBUST",key,"no robust candidate",flush=True)
            continue
        score,p,fit=max(surviving,key=lambda q:q[0])
        eq,k=simulate(source,p)
        all_result=stats(eq,idx)
        hold=stats(eq,idx,TEST)
        full_boot=bootstrap_returns(source,idx,len(source))
        dd=np.array([stats(simulate(x,p)[0],
                            pd.date_range("2021-01-01",periods=len(x),tz="UTC"))["mdd"]
                     for x in full_boot])
        rows[key]={"selected":asdict(p),"selection_evidence":fit,
                   "eligible_policies":len(surviving),
                   "full":all_result,"post_hoc_2025_26":hold,
                   "full_400_bootstrap_p95":float(np.quantile(dd,.95)),
                   "full_400_bootstrap_under10":float(np.mean(dd<10)),
                   "mean_risk":float(np.mean(k)),"min_risk":float(np.min(k)),
                   "full_daily_mdd_under10":bool(all_result["mdd"]<10),
                   "adverse_loss50_full_mdd":stats(simulate(stress_returns(source,idx,1.5,[]),p)[0],idx)["mdd"]}
        all_curves[key]=eq
        print("ROBUST_WINNER",key,json.dumps(rows[key]),flush=True)
    result={"research_stage":"EXPLORATORY second-stage 95% drawdown constraint",
            "holdout_note":"2025-26 tested previously in first-stage; no longer pristine for new research design",
            "criteria":{"bootstrap_paths":B_SELECTION,"block_days":21,
                        "dev_bootstrap_95pct_mdd_below":P95_LIMIT,
                        "dev_plus25pct_loss_mdd_below":HIST_STRESS_LIMIT,
                        "dev_and_validation_MDD_below":8.3},
            "date":"2021-10-05 to 2026-10-04",
            "results":rows,"is_true_F":False,
            "is_full_execution_backtest":False,
            "future_validation_required":"Forward PAPER shadow + intraday 35-coin full replay"}
    (OUT/"robust_selection.json").write_text(json.dumps(result,indent=2))
    pd.DataFrame({"date":idx.astype(str),**all_curves}).to_csv(OUT/"robust_policy_daily.csv",index=False)
    return result

if __name__=="__main__":run()
