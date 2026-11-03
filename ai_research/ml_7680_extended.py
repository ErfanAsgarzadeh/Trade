"""Second 7,680-configuration AI/Risk search. Research-level counterfactual ONLY.

This stage is explicitly EXPLORATORY because 2025-26 performance of previous
risk experiments has been inspected. Candidate construction does not use
2025-26, and parameters are selected strictly by 2023-24 results; but the
research-design holdout is NOT untouched.

40 causal pretrained-in-each-fold models x 192 policies = 7,680 arms per
mode (NoF and F-style proxy). All model features/labels predated decision.
Policy comparisons are accurate only for daily account-return overlays,
NOT actual 35-symbol replays with dynamic margin / exits / funding.

An efficiency improvement precomputes percentile rank of each OOS model
score from ONLY earlier OOS forecasts, then evaluates policies in numba.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import itertools,json
import numpy as np,pandas as pd
from numba import njit
from .ml_1280_search import get_data,build_features,make_targets,train_predictions,model_grid
from .mdd10_frontier import OUT as ROOT_OUT,stats,TEST,f_proxy_base

OUT=ROOT_OUT/"ml_150_10"
CAGR_GOAL=150.
MDD_GOAL=10.
PRE_MDD_LIMIT=8.5

@dataclass(frozen=True)
class RiskPolicy:
    low:float
    mid:float
    high:float
    q:float
    soft:float
    hard:float
    release:int

def policies():
    p=[]
    for low,mid,high,q,soft,hard,release in itertools.product(
            (0.,.25),(.75,1.25),(2.,3.),(.25,.5),
            (.03,.05),(.075,.095),(0,40,90)):
        if hard<=soft:continue
        p.append(RiskPolicy(low,mid,high,q,soft,hard,release))
    assert len(p)==192
    return p

@njit(cache=True)
def causal_score_rank(score,window=400):
    n=len(score);pct=np.full(n,np.nan)
    for i in range(n):
        if not np.isfinite(score[i]):continue
        found=0;under=0
        for j in range(max(0,i-window),i):
            if np.isfinite(score[j]):
                found+=1
                if score[j]<score[i]:under+=1
        if found>=45:pct[i]=under/found
    return pct

@njit(cache=True)
def simulate(r,pct,low,mid,high,q,soft,hard,release):
    n=len(r);e=np.ones(n+1);K=np.zeros(n)
    highwater=1.
    for i in range(n):
        # Begin with safe untrained warmup, not the original 200% strategy.
        if not np.isfinite(pct[i]):
            k=.32
        elif pct[i]<q:
            k=low
        elif pct[i]>(1.-q*.5):
            k=high
        else:
            k=mid
        # DD uses only equity at BEGINNING of day i.
        highest=highwater
        if release>0 and i>=release:
            highest=e[i]
            for j in range(i-release,i):highest=max(highest,e[j])
        dd=max(0.,1-e[i]/highest)
        if dd>soft:
            k*=max(.01,1-(dd-soft)/(hard-soft))
        if dd>=hard:k=min(k,.025)
        k=min(3.5,max(0.,k))
        daily=max(1e-10,1+k*r[i])
        e[i+1]=e[i]*daily
        highwater=max(highwater,e[i+1])
        K[i]=k
    return e[1:],K

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    idx,ref,btc=get_data()
    x=build_features(idx,ref,btc)
    pred,folds=train_predictions(x,make_targets(ref),idx)
    percentiles=[causal_score_rank(pred[i]) for i in range(len(model_grid()))]
    f=f_proxy_base(ref)
    fr=np.diff(np.r_[1.,f])/np.r_[1.,f[:-1]]
    out={"stage":"EXPLORATORY, constructed after viewing earlier 2025 results",
         "selection_data":"2023 and 2024 only; train expanding 2021-2025 with 21d label embargo",
         "models":len(model_grid()),"risk_policies":len(policies()),
         "arms_per_mode":len(model_grid())*len(policies()),"folds":folds,
         "modes":{},"full_F_replay":False,
         "limitation":"Daily NAV overlays, not actual 35-symbol execution or real F",
         "final_target_met_by_fully_verified_executable_strategy":False}
    paths={}
    for mode,r in (("NoF",ref),("Fstyle_NOT_RealF",fr)):
        scored=[];all_found=0
        pre_ok=0
        full_hindsight_hits=0
        test_hindsight_hits=0
        all_hindsight_best=None
        for m,c in enumerate(model_grid()):
            pct=percentiles[m]
            for k,p in enumerate(policies()):
                eq,siz=simulate(r,pct,p.low,p.mid,p.high,p.q,p.soft,p.hard,p.release)
                # HINDSIGHT DIAGNOSTIC ONLY: do not use future results to select.
                full_diag=stats(eq,idx)
                test_diag=stats(eq,idx,TEST)
                if full_diag["cagr"]>CAGR_GOAL and full_diag["mdd"]<MDD_GOAL:
                    full_hindsight_hits+=1
                    if all_hindsight_best is None or full_diag["cagr"]>all_hindsight_best["full"]["cagr"]:
                        all_hindsight_best={"model":model_grid()[m],"policy":asdict(p),
                                            "full":full_diag,"posthoc_2025_26":test_diag,
                                            "warning":"HINDSIGHT ORACLE. NOT valid out-of-sample model selection."}
                if test_diag["cagr"]>CAGR_GOAL and test_diag["mdd"]<MDD_GOAL:
                    test_hindsight_hits+=1
                v23=stats(eq,idx,"2023-01-01","2024-01-01")
                v24=stats(eq,idx,"2024-01-01","2025-01-01")
                if v23["mdd"]<=PRE_MDD_LIMIT and v24["mdd"]<=PRE_MDD_LIMIT:
                    pre_ok+=1
                    # Only 2023 and 2024 for ranking, no 2025+ here.
                    score=.5*(v23["cagr"]+v24["cagr"])-.3*abs(v23["cagr"]-v24["cagr"])
                    scored.append((score,m,k,v23,v24))
        scored.sort(reverse=True,key=lambda z:z[0])
        winners=[]
        for rank,(score,m,k,v23,v24) in enumerate(scored[:50],1):
            p=policies()[k]
            eq,size=simulate(r,percentiles[m],p.low,p.mid,p.high,p.q,p.soft,p.hard,p.release)
            full=stats(eq,idx);holdout=stats(eq,idx,TEST)
            winners.append({"rank":rank,"model":model_grid()[m],"risk":asdict(p),
                  "selection_score":score,"year2023":v23,"year2024":v24,
                  "full":full,"posthoc_2025_26":holdout,
                  "meets_150_10_full":bool(full["cagr"]>CAGR_GOAL and full["mdd"]<MDD_GOAL),
                  "meets_150_10_posthoc":bool(holdout["cagr"]>CAGR_GOAL and holdout["mdd"]<MDD_GOAL),
                  "mean_exposure_scale":float(size.mean())})
            if rank==1:paths[mode]=eq
        out["modes"][mode]={"pre2025_eligible":pre_ok,"ranked":len(scored),
             "full_hindsight_goal_hits_NOT_valid":full_hindsight_hits,
             "2025_26_hindsight_goal_hits_NOT_valid":test_hindsight_hits,
             "best_full_hindsight_ORACLE_NOT_deployable":all_hindsight_best,
             "winner":winners[0] if winners else None,
             "top50":winners}
        print("EXTENDED_ML_RESULTS",mode,json.dumps({
          "tested":len(model_grid())*len(policies()),
          "pre2025_eligible":pre_ok,
          "hindsight_goal_hits":full_hindsight_hits,
          "selected":winners[0] if winners else None
        },default=float),flush=True)
    (OUT/"extended_7680_result.json").write_text(json.dumps(out,indent=2,default=float))
    pd.DataFrame({"date":idx.astype(str),**paths}).to_csv(OUT/"extended_7680_equity.csv",index=False)
    return out

if __name__=="__main__":main()
