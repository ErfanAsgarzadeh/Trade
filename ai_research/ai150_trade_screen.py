"""Independent 1,010-model trade-level AI filter/sizing study (causal OOS).

This is a SECOND search that targets the *trade expectancy* rather than
just globally reducing a three-bot portfolio risk multiplier. Uses the
historical 35-symbol cached ledger and original bot-entry features.
Latest Mojsavar protected exits and current F intratrade cuts are NOT
in this ledger: results are investigative realized-equity screens, not
actual executable MDD. Taker fee 0.0006/side and slip 0.0002/side already
included in the source unit; do not double count. Requires source fills
for exact requested 0.0005/side repricing.

Every classifier/regressor/anomaly learner uses past EXITED trade roots
only, with 20 completed 4h bars label embargo at 2023/2024/2025/2026
fold starts. Numeric imputation/RobustScaler and OHE bot/side/coin fit
only on TRAIN. Causal historical bot/side/coin expectancy includes ONLY
roots whose exit occurred before current root entry timestamp.

Two development years select ONE algorithm+signal rule (2023-24).
ONLY that winner is re-fit and evaluated in 2025-26. Previous project
experiments have inspected 2025-26: NOT pristine project-level holdout.
The training labels are realized net trade R (not TP/SL triple barrier).
"""
from __future__ import annotations
import json
import math
import warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler,OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from . import ai150_mass_screen as A
from . import seven_benchmark as B

OUT=A.OUT
TRAIN_YEARS=[("2023-01-01","2024-01-01"),("2024-01-01","2025-01-01")]
TEST_YEARS=[("2025-01-01","2026-01-01"),("2026-01-01","2026-10-05")]
RISK=dict(main=.01,c3=.004,pa=.004)
ROOT_LIMIT=2.
SHORT_FACTORS=(.25,.5,1.)
POLICIES=tuple(range(9))
EPOCH=B.ORIGIN

def features(t):
    """Existing fixed 4h entry features and causally completed trade history."""
    tab=t.copy()
    exits=tab.sort_values("root_exit_min",kind="stable")
    from collections import deque
    agg=defaultdict(lambda:[0,0.,0])
    observed=[]
    p=0
    for row in tab.itertuples():
        while p<len(exits) and float(exits.iloc[p].root_exit_min)<float(row.em):
            ex=exits.iloc[p]
            r=float(ex.realized_r)
            for key in [("all","all"),("bot",str(ex.bot)),
                        ("side",str(int(ex.side))),("coin",str(ex.coin)),
                        ("bot_side",str(ex.bot)+":"+str(int(ex.side)))]:
                x=agg[key];x[0]+=1;x[1]+=r;x[2]+=(r>0)
            p+=1
        d={}
        for group,name in [("all","all"),("bot",str(row.bot)),
                           ("side",str(int(row.side))),("coin",str(row.coin)),
                           ("bot_side",str(row.bot)+":"+str(int(row.side)))]:
            n,total,wins=agg[(group,name)]
            d[f"closed_{group}_n"]=np.log1p(n)
            d[f"closed_{group}_mean_r"]=total/n if n>=5 else np.nan
            d[f"closed_{group}_winrate"]=wins/n if n>=5 else np.nan
        observed.append(d)
    engineered=pd.DataFrame(observed,index=tab.index)
    for col in engineered:
        tab[col]=engineered[col]
    # Sides in legacy features often signed in trade direction, so do not
    # multiply them by direction again; side is a separate categorical.
    tab["side"]=tab.side.astype(str)
    tab["bot"]=tab.bot.astype(str)
    tab["coin"]=tab.coin.astype(str)
    cols=B.COLS+list(engineered.columns)
    return tab,cols,["bot","side","coin"]

def train_masks(t,st,en):
    start=pd.Timestamp(st,tz="UTC")
    end=pd.Timestamp(en,tz="UTC")
    cutoff=(start-EPOCH).total_seconds()/60
    limit=(end-EPOCH).total_seconds()/60
    train=((t.em<cutoff)&(t.root_exit_min<cutoff-B.EMBARGO_MINUTES)).to_numpy()
    test=((t.em>=cutoff)&(t.em<limit)).to_numpy()
    if train.sum()<150 or test.sum()<40:raise ValueError("Too few matured roots or test signals")
    assert np.all(t.root_exit_min.to_numpy()[train]+B.EMBARGO_MINUTES<cutoff)
    assert not np.any(train&test)
    return train,test

def fit_predict(s,t,cols,cats,st,en):
    tr,te=train_masks(t,st,en)
    numeric=Pipeline([("imp",SimpleImputer(strategy="median",keep_empty_features=True)),
                      ("scale",RobustScaler(quantile_range=(10,90)))])
    categ=OneHotEncoder(handle_unknown="ignore",sparse_output=False)
    trans=ColumnTransformer(
        [("numeric",numeric,cols),("categorical",categ,cats)],
        sparse_threshold=0.)
    xtr=trans.fit_transform(t.loc[tr])
    xte=trans.transform(t.loc[te])
    y=t.realized_r.to_numpy(float)
    vals=(y[tr]>0).astype(int) if s["family"] in ("logit","rfclass") else np.clip(y[tr],-5.,7.)
    model=A.make_model(s)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if s["family"] in ("isolation","gmm"):
            model.fit(xtr)
        else:
            model.fit(xtr,vals)
    if s["family"] in ("logit","rfclass"):
        ptrain=model.predict_proba(xtr)[:,1]
        ptest=model.predict_proba(xte)[:,1]
    elif s["family"] in ("isolation","gmm"):
        ptrain=model.score_samples(xtr)
        ptest=model.score_samples(xte)
    else:
        ptrain=model.predict(xtr)
        ptest=model.predict(xte)
    if not np.isfinite(ptrain).all() or not np.isfinite(ptest).all():
        raise ValueError("Non-finite predicted signal value")
    ranks=np.searchsorted(np.sort(ptrain),ptest,side="right")/len(ptrain)
    return ranks,te,int(tr.sum()),int(te.sum())

def size_rule(q,rule):
    """Fixed rank policies, no training or tuning on evaluation trade outcomes."""
    z=np.asarray(q,float)
    if rule==0:return .3+1.7*z
    if rule==1:return np.where(z<.30,0.,np.where(z>.75,2.,1.))
    if rule==2:return np.where(z<.50,0.,np.where(z>.85,2.,1.))
    if rule==3:return np.where(z<.65,0.,2.)
    if rule==4:return np.where(z<.20,.1,np.where(z<.65,.6,1.8))
    if rule==5:return np.where(z<.10,.2,np.where(z<.50,1.,1.8))
    if rule==6:return np.where(z<.15,.0,np.where(z<.85,1.,2.))
    if rule==7:return np.where(z>.75,2.,.25)
    if rule==8:return np.clip(2.5*z-.5,0.,2.)
    raise ValueError(rule)

def surrogate_score(t,scores,have,rule,short_factor):
    """ONLY candidate search ranking: risk-unit trade-return advantage.

    This is NOT an account equity curve: no leverage, MTM or margin/cost
    recomputation. Full event-replay is reserved for the ONE preselected model.
    """
    k=size_rule(scores,rule)
    k[~have]=1.  # All pre-2023 trades unchanged in the research screen
    k=np.asarray(k,dtype=float)
    s=t.side.astype(int).to_numpy()
    k[s<0]*=short_factor
    risk=np.array([RISK[v] for v in t.bot])
    r=t.realized_r.to_numpy(float)
    root_index=t.entry_date
    years=t.entry_date.dt.year.to_numpy()
    # focus on truly OOS 2023 and 2024 decisions only
    a=(years==2023)
    b=(years==2024)
    if a.sum()<50 or b.sum()<50: return -np.inf
    # Restrict excessive "success" by removing all signals.
    if np.mean(k[a]>0)<.35 or np.mean(k[b]>0)<.35:return -np.inf
    roi=r*risk*k
    p23=float(np.sum(roi[a]));p24=float(np.sum(roi[b]))
    # Multiple-testing control heuristic: demand improvement across both
    # development folds and use the WORSE fold as objective.
    base23=float(np.sum((r*risk)[a]));base24=float(np.sum((r*risk)[b]))
    gain23=p23-base23;gain24=p24-base24
    return 0.8*min(gain23,gain24)+.2*(gain23+gain24)/2

def selection():
    OUT.mkdir(parents=True,exist_ok=True)
    legs,t,source=B.load()
    t,cols,cats=features(t)
    specs=A.model_specs()
    winners=[]
    diagnostics={"trained_models":0,"specifications":len(specs),"families":11,
                 "policies_per_model":len(POLICIES)*len(SHORT_FACTORS),
                 "feasible_per_model":0,"source":source,"error_counts":{},
                 "folds":TRAIN_YEARS,"raw_num_features":len(cols)}
    for i,s in enumerate(specs):
        ranks=np.full(len(t),.5,float);known=np.zeros(len(t),bool)
        feasible=True;count=[]
        for st,en in TRAIN_YEARS:
            try:
                p,mask,ntr,nte=fit_predict(s,t,cols,cats,st,en)
                ranks[mask]=p;known[mask]=True
                diagnostics["trained_models"]+=1
                count.append({"start":st,"end":en,"train":ntr,"test":nte})
            except Exception as exc:
                err=str(exc)[:140]
                diagnostics["error_counts"][err]=diagnostics["error_counts"].get(err,0)+1
                feasible=False
                break
        if not feasible:continue
        scorelist=[]
        for rule in POLICIES:
            for short in SHORT_FACTORS:
                value=surrogate_score(t,ranks,known,rule,short)
                if np.isfinite(value):
                    scorelist.append((value,rule,short))
        if scorelist:
            val,rule,short=max(scorelist,key=lambda z:z[0])
            winners.append({"spec":s,"dev_score":float(val),"rule":rule,
                            "short_factor":short,"fold_counts":count})
        if (i+1)%100==0:
            print("TRADE_PROGRESS",i+1,"fitted",diagnostics["trained_models"],
                  "dev_eligible",len(winners),flush=True)
    if not winners:
        out={"status":"NO_TRADE_AI_CANDIDATE","diagnostics":diagnostics}
        (OUT/"trade_ai_result.json").write_text(json.dumps(out,indent=2))
        print("TRADE_AI_RESULT",json.dumps(out),flush=True)
        return out
    winners.sort(key=lambda x:x["dev_score"],reverse=True)
    chosen=winners[0]
    # NEVER pick winner by its 2025+ results.
    q=np.full(len(t),.5,float);has=np.zeros(len(t),bool)
    testfits=[]
    for st,en in TRAIN_YEARS+TEST_YEARS:
        pred,mask,ntr,nte=fit_predict(chosen["spec"],t,cols,cats,st,en)
        q[mask]=pred;has[mask]=True
        testfits.append({"start":st,"train":ntr,"test":nte})
    k=size_rule(q,chosen["rule"])
    k[~has]=1.
    side=t.side.astype(int).to_numpy()
    k[side<0]*=chosen["short_factor"]
    keep={str(r.root):bool(k[j]>.01) for j,r in enumerate(t.itertuples())}
    sizing={str(r.root):float(min(2.,max(0.,k[j]))) for j,r in enumerate(t.itertuples())}
    base_accept={str(r.root):True for r in t.itertuples()}
    base_size={str(r.root):1. for r in t.itertuples()}
    comparisons={}
    for mode in ("off","proxy"):
        b_daily,b_closed=B.daily_realized_replay(legs,base_accept,base_size,mode=mode)
        d_daily,d_closed=B.daily_realized_replay(legs,keep,sizing,mode=mode)
        key="no_F" if mode=="off" else "F_style_proxy_NOT_real_F"
        comparisons[key]={
            "baseline":B.metrics(b_daily,b_closed),
            "selected_ai":B.metrics(d_daily,d_closed),
            "screen_goal_pass":bool(B.metrics(d_daily,d_closed)["CAGR (%)"]>=150
                  and B.metrics(d_daily,d_closed)["Max Drawdown (%)"]<10),
            "subset_no_mtm":True}
        index=pd.date_range(B.ORIGIN,periods=len(d_daily),freq="D")
        pd.DataFrame({"date":index.astype(str),
                      "realized_only_baseline":b_daily,
                      "realized_only_selected_ai":d_daily}).to_csv(
            OUT/("trade_ai_"+key+".csv"),index=False)
    result={
      "status":"SCREEN_ONLY_NOT_FULL_MTM",
      "fitted_models":diagnostics["trained_models"],
      "model_specs":diagnostics["specifications"],
      "selection_candidates":len(winners),
      "train_dev_summary":diagnostics,
      "winning_selection_pre2025":chosen,
      "refitted_predictions":testfits,
      "all_scenarios":comparisons,
      "pre2025_top_20":winners[:20],
      "accepted_signals":int(np.sum(k>.01)),
      "total_base_signal_roots":len(t),
      "limitations":[
        "Cached ledger predates latest protected Mojsavar exits, unlike current authoritative daily NAV",
        "Event replay credits PnL only at exit; measured MaxDD can miss worst open-position loss",
        "F proxy only. Actual F's AI and cuts unavailable",
        "Source fees/slippage 0.0006/0.0002 per side already embedded; 0.0005 needs real fills",
        "35-symbol minute tapes and counterfactual fills absent, so this cannot confirm user's 150/10 goal",
        "Historical original 3-bot strategy selection looked at 2025-26 in earlier work",
        "Only ONE model selected pre2025 evaluated on 2025-26; test results cannot reselect a model",
      ]}
    (OUT/"trade_ai_result.json").write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print("TRADE_AI_RESULT",json.dumps({
        "status":result["status"],"fitted_models":result["fitted_models"],
        "selected":chosen,"comparisons":comparisons,
        "accepted_signals":result["accepted_signals"]}),flush=True)
    return result

if __name__=="__main__":
    selection()
