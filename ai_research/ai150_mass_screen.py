"""Thousands-of-fits leak-audited ML alpha-versus-DD research. DO NOT DEPLOY.

Goal: full-period CAGR >=150% and MAX DAILY CLOSE DD <10%, with no changes to
the Shahin/Mojsavar/Ghoghnous entry logic. 1010 distinct ML configurations
are fitted in TWO independently timed development folds (2023 and 2024),
with 5-day outcome label purge + 5 extra days embargo. The model predicts
NEXT FIVE CLOSED-DAY reference account returns from signals known at the
BEGINNING of the forecasting day. All imputers/scalers fit only in that
fold's TRAIN and models are then trained only on X_train. Models do not
learn directly from their own future labels or 2025+ during selection.

LIMITATION: We multiply the stored latest protected-rule 3-bot DAILY EQUITY
returns by AI-selected risk. This is NOT a 35-coin event-level backtest, and
no execution path, funding or F's open-position cuts are replayed.
ML input includes shadow *baseline strategy* past returns; production would
require a running untouched reference shadow ledger even when trades are
filtered/reduced. Intraday DD may be larger. Original 2025-26 data have
been viewed in previous research, therefore NO pristine research-level OOS.
The 2025/2026 test can reject but never tune this candidate family.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import itertools
import json
import math
import warnings
import numpy as np
import pandas as pd
from numba import njit
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import Ridge,ElasticNet,SGDRegressor,LogisticRegression
from sklearn.ensemble import (
 RandomForestRegressor,ExtraTreesRegressor,HistGradientBoostingRegressor,
 GradientBoostingRegressor,RandomForestClassifier,IsolationForest,
)
from sklearn.mixture import GaussianMixture
from .mdd10_frontier import load_ref,stats,OUT as BASE_OUT
from .btc_market import load_btc_4h

OUT=BASE_OUT/"ai1000"
SEED=20261103
HORIZON_DAYS=5
EMBARGO_DAYS=5
VAL_FOLDS=[("2023-01-01","2024-01-01"),("2024-01-01","2025-01-01")]
FUTURE_FOLDS=[("2025-01-01","2026-01-01"),("2026-01-01","2026-10-05")]
DATE_ORIGIN="2021-10-05"
DATE_END="2026-10-04"
# The 4 risk-budget modes and 6 score-to-risk maps were specified before test.
# Controls 2-3 use hypothetical reference-return shock guards; not hard stops.
RISK_CONTROLS=[
 (0.04,0.085,0.10,0.0,0.0),
 (0.06,0.10,0.15,0.0,0.0),
 (0.06,0.11,0.15,0.10,0.085),
 (0.05,0.11,0.10,0.12,0.09),
]
BASE_LEVELS=(0.7,1.0,1.35,1.7)
MAPS=tuple(range(8))
WARMUP_MULTIPLIER=.30
MAX_RISK_SCALE=3.0

def model_specs():
    """Each yielded entry represents a separately FIT real scikit-learn model."""
    items=[]
    def add(family,params):
        items.append({"id":f"{family}_{sum(x['family']==family for x in items):03d}",
                      "family":family,"params":params})
    for a in np.logspace(-5,5,150):
        add("ridge",{"alpha":float(a)})
    for l1 in (.10,.35,.70,.95):
        for a in np.logspace(-5,-.3,25):
            add("elasticnet",{"alpha":float(a),"l1_ratio":l1})
    for penalty in ("l2","l1","elasticnet"):
        for alpha in np.logspace(-6,-1,25):
            for learning in ("optimal","invscaling"):
                add("sgd",{"penalty":penalty,"alpha":float(alpha),"learning_rate":learning})
    for C in np.logspace(-4,3,50):
        for cw in ("none","balanced","upweight"):
            add("logit",{"C":float(C),"class_weight":cw})
    for depth in (2,3,4,6,9):
        for leaf in (5,12,20,35,60):
            for feat in (.5,.7,.9,1.):
                add("rfreg",{"max_depth":depth,"min_samples_leaf":leaf,"max_features":feat})
                add("extratrees",{"max_depth":depth,"min_samples_leaf":leaf,"max_features":feat})
    for leaf in (5,9,15,25,40):
        for depth in (3,5,8,12):
            for rate in (.025,.045,.075,.12):
                add("hgbreg",{"max_leaf_nodes":leaf,"max_iter":65,"max_depth":depth,
                              "learning_rate":rate})
    for depth in (1,2,3,4,5):
        for minleaf in (8,16,30,50):
            for lr in (.025,.05,.10):
                add("gbreg",{"max_depth":depth,"min_samples_leaf":minleaf,
                             "learning_rate":lr})
    for depth in (2,3,5,7,10):
        for minleaf in (8,15,30,50):
            for feat in (.5,.7,1.):
                add("rfclass",{"max_depth":depth,"min_samples_leaf":minleaf,"max_features":feat})
    for cont in (.025,.05,.08,.12,.2):
        for samp in (.5,.8,1.):
            for trees in (40,70):
                add("isolation",{"contamination":cont,"max_samples":samp,"n_estimators":trees})
    for nc in (2,3,4,5,7):
        for reg in (.001,.015,.07):
            for cov in ("diag","spherical"):
                add("gmm",{"n_components":nc,"reg_covar":reg,"covariance_type":cov})
    assert len(items)==1010,len(items)
    assert len(set(x["id"] for x in items))==len(items)
    return items

def make_model(s):
    f,p=s["family"],s["params"]
    if f=="ridge":return Ridge(**p)
    if f=="elasticnet":return ElasticNet(**p,max_iter=350,random_state=SEED)
    if f=="sgd":return SGDRegressor(**p,max_iter=210,tol=1e-3,
                                     shuffle=False,random_state=SEED)
    if f=="logit":
        args=p.copy()
        cw=args.pop("class_weight")
        cw=None if cw=="none" else ("balanced" if cw=="balanced" else {0:1.,1:1.4})
        return LogisticRegression(C=args["C"],class_weight=cw,solver="liblinear",
                                  max_iter=250,random_state=SEED)
    if f=="rfreg":return RandomForestRegressor(**p,n_estimators=24,n_jobs=1,random_state=SEED)
    if f=="extratrees":return ExtraTreesRegressor(**p,n_estimators=24,n_jobs=1,random_state=SEED)
    if f=="hgbreg":return HistGradientBoostingRegressor(**p,min_samples_leaf=20,
                                    l2_regularization=5.,random_state=SEED)
    if f=="gbreg":return GradientBoostingRegressor(**p,n_estimators=45,
                                            loss="huber",random_state=SEED)
    if f=="rfclass":return RandomForestClassifier(**p,n_estimators=24,n_jobs=1,
                                                 random_state=SEED)
    if f=="isolation":return IsolationForest(**p,random_state=SEED,n_jobs=1)
    if f=="gmm":return GaussianMixture(**p,max_iter=80,n_init=1,random_state=SEED)
    raise ValueError(f)

def feature_matrix(ix,reference_ret,btc_close):
    """Stationary, AVAILABLE at UTC day open. No current day's return/price."""
    ref=pd.Series(np.asarray(reference_ret,float),index=ix)
    price=pd.Series(np.asarray(btc_close,float),index=ix)
    bret=np.log(price).diff()
    logret=np.log1p(ref)
    d=pd.DataFrame(index=ix)
    for k in (1,2,3,5,10,20,40,90):
        d[f"ref_logsum_{k}"]=logret.rolling(k,min_periods=k).sum().shift(1)
    for k in (5,10,20,40,90):
        d[f"ref_vol_{k}"]=ref.rolling(k,min_periods=k).std().shift(1)
        d[f"ref_negprob_{k}"]=ref.lt(0).astype(float).rolling(k,min_periods=k).mean().shift(1)
    shadow_eq=(1+ref).cumprod()
    d["ref_dd"]=(shadow_eq/shadow_eq.cummax()-1).shift(1)
    d["ref_gainloss20"]=(ref.clip(lower=0).rolling(20).mean()/
                         (-ref.clip(upper=0).rolling(20).mean()).replace(0,np.nan)).shift(1)
    for k in (1,3,7,14,30,60,90):
        d[f"btc_logsum_{k}"]=bret.rolling(k,min_periods=k).sum().shift(1)
    for k in (5,10,20,40,90):
        d[f"btc_vol_{k}"]=bret.rolling(k,min_periods=k).std().shift(1)
    for k in (20,50,100,200):
        d[f"btc_ema_{k}"]=(price/price.ewm(span=k,adjust=False,min_periods=k).mean()-1).shift(1)
    for k in (20,60):
        roll_hi=price.rolling(k,min_periods=k).max()
        roll_lo=price.rolling(k,min_periods=k).min()
        d[f"btc_range_{k}"]=((price-roll_lo)/(roll_hi-roll_lo).replace(0,np.nan)).shift(1)
    d["btc_ref_corr20"]=ref.rolling(20).corr(bret).shift(1)
    # Calendar known at the decision time; stationary cyclic encoding.
    day=ix.dayofweek.to_numpy(float)
    doy=ix.dayofyear.to_numpy(float)
    d["dow_sin"]=np.sin(2*np.pi*day/7.)
    d["dow_cos"]=np.cos(2*np.pi*day/7.)
    d["year_sin"]=np.sin(2*np.pi*doy/365.25)
    d["year_cos"]=np.cos(2*np.pi*doy/365.25)
    return d.replace([np.inf,-np.inf],np.nan)

def target_forward_ret(reference_ret,n=HORIZON_DAYS):
    ret=np.asarray(reference_ret,float)
    y=np.full(len(ret),np.nan)
    for i in range(len(y)-n+1):
        y[i]=float(np.clip(np.prod(1+ret[i:i+n])-1,-.20,.20))
    return y

def prepare():
    eq,idx,ret=load_ref()
    btc=load_btc_4h().close.resample("1D").last().reindex(idx)
    if btc.isna().any():
        raise ValueError(f"BTC missing daily closes {btc.isna().sum()}")
    x=feature_matrix(idx,ret,btc.to_numpy())
    y=target_forward_ret(ret)
    return eq,idx,ret,x,y

def eligible_masks(idx,y,start,end):
    s=pd.Timestamp(start,tz="UTC")
    e=pd.Timestamp(end,tz="UTC")
    # The latest eligible t + HORIZON-1 is strictly BEFORE fold start,
    # plus EMBARGO_DAYS extra separation.
    latest=s-pd.Timedelta(days=HORIZON_DAYS+EMBARGO_DAYS)
    tr=(idx<latest)&(idx>=pd.Timestamp("2022-01-01",tz="UTC"))&np.isfinite(y)
    te=(idx>=s)&(idx<e)
    assert idx[np.flatnonzero(tr)[-1]]+pd.Timedelta(days=HORIZON_DAYS-1)<s
    assert np.all(~(tr&te))
    return tr,te

def fitted_scores(spec,x,y,idx,start,end):
    """Fit scaler and imputer exclusively within historical train fold."""
    tr,te=eligible_masks(idx,y,start,end)
    arr=x.to_numpy(float)
    if tr.sum()<200 or te.sum()<50:raise ValueError("Insufficient historical fold")
    pipe=Pipeline([("imputer",SimpleImputer(strategy="median",keep_empty_features=True)),
                   ("scale",RobustScaler(quantile_range=(10,90)))])
    xtr=pipe.fit_transform(arr[tr])
    xte=pipe.transform(arr[te])
    mdl=make_model(spec)
    label=(y[tr]>0).astype(int) if spec["family"] in ("logit","rfclass") else y[tr]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mdl.fit(xtr,label) if spec["family"] not in ("isolation","gmm") else mdl.fit(xtr)
    if spec["family"] in ("logit","rfclass"):
        pred_tr=mdl.predict_proba(xtr)[:,1]
        pred_te=mdl.predict_proba(xte)[:,1]
    elif spec["family"] in ("isolation","gmm"):
        pred_tr=mdl.score_samples(xtr)
        pred_te=mdl.score_samples(xte)
    else:
        pred_tr=mdl.predict(xtr)
        pred_te=mdl.predict(xte)
    if not np.isfinite(pred_te).all() or not np.isfinite(pred_tr).all():
        raise ValueError("non-finite ML prediction")
    # No future label in distribution rank. Distributions from FIT history only.
    sorted_train=np.sort(pred_tr)
    percentile=np.searchsorted(sorted_train,pred_te,side="right")/len(sorted_train)
    return percentile,int(tr.sum()),int(te.sum())

@njit(cache=True)
def overlay(ret,rank,seen,base,map_id,soft,hard,floor,shock,budget):
    n=len(ret)
    e=np.ones(n+1,float)
    k=np.zeros(n,float)
    peak=1.
    for i in range(n):
        dd=max(0.,1-e[i]/peak)
        mul=WARMUP_MULTIPLIER
        if seen[i]:
            q=rank[i]
            if map_id==0:mul=base*(0.15+2.1*q)
            elif map_id==1:mul=base*(0.02 if q<.3 else (0.35 if q<.55 else (1.4 if q<.8 else 2.8)))
            elif map_id==2:mul=base*(0.05 if q<.50 else (1.2 if q<.8 else 3.))
            elif map_id==3:mul=base*(0.05 if q<.70 else 3.6)
            elif map_id==4:mul=base*(.15 if q<.20 else (.65 if q<.60 else 2.))
            elif map_id==5:mul=base*(.35 if q<.25 else (1.0 if q<.65 else 2.5))
            elif map_id==6:mul=base*(1.5 if q>=.65 else 0.)
            elif map_id==7:mul=base*(3.5 if q>=.85 else .05)
        if hard>0 and dd>soft:
            mul*=max(floor,1-(1-floor)*(dd-soft)/(hard-soft))
        if shock>0:
            room=1-(1-budget)/max(1e-12,1-dd)
            mul=min(mul,max(0.,room/shock))
        mul=max(0.,min(MAX_RISK_SCALE,mul))
        k[i]=mul
        e[i+1]=max(1e-12,e[i]*max(1e-12,1+mul*ret[i]))
        if e[i+1]>peak:peak=e[i+1]
    return e[1:],k

def policy_specs():
    return [(base,mapid,j,ctrl) for base in BASE_LEVELS
            for mapid in MAPS
            for j,ctrl in enumerate(RISK_CONTROLS)]

def dev_score(eq,idx):
    a=stats(eq,idx,"2023-01-01","2024-01-01")
    b=stats(eq,idx,"2024-01-01","2025-01-01")
    c=stats(eq,idx,None,"2025-01-01")
    if a["mdd"]>=8.3 or b["mdd"]>=8.3 or c["mdd"]>=8.3:
        return -np.inf
    # Stable worst-fold weighted reward, no full-history oracle.
    return .70*min(a["cagr"],b["cagr"])+.30*(.5*a["cagr"]+.5*b["cagr"])

def scout():
    OUT.mkdir(parents=True,exist_ok=True)
    eq,idx,r,x,y=prepare()
    specs=model_specs()
    all_policies=policy_specs()
    best=[]
    diagnostics={"specifications":len(specs),"folds":VAL_FOLDS,
                 "policies_per_model":len(all_policies),"trained_fits":0,
                 "failures":{},"eligible_candidate_pairs":0,
                 "features":x.columns.tolist(),"labels":"forward five-day base account net return"}
    for i,spec in enumerate(specs):
        pct=np.full(len(idx),.5,float)
        seen=np.zeros(len(idx),bool)
        fold_counts=[]
        valid=True
        for start,end in VAL_FOLDS:
            try:
                p,ntrain,ntest=fitted_scores(spec,x,y,idx,start,end)
                test=(idx>=pd.Timestamp(start,tz="UTC"))&(idx<pd.Timestamp(end,tz="UTC"))
                pct[test]=p;seen[test]=True
                fold_counts.append({"train":ntrain,"test":ntest})
                diagnostics["trained_fits"]+=1
            except Exception as e:
                err=str(e)[:150]
                diagnostics["failures"][err]=diagnostics["failures"].get(err,0)+1
                valid=False;break
        if not valid:continue
        selected_for_model=[]
        for base,mapid,ci,ctrl in all_policies:
            e,k=overlay(r,pct,seen,base,mapid,*ctrl)
            score=dev_score(e,idx)
            if np.isfinite(score):
                diagnostics["eligible_candidate_pairs"]+=1
                selected_for_model.append((score,base,mapid,ci))
        if selected_for_model:
            sc,base,mi,ci=max(selected_for_model,key=lambda z:z[0])
            best.append({"spec":spec,"dev_score":float(sc),
                         "policy":{"base":base,"map":mi,"control_id":ci},
                         "fold_counts":fold_counts})
        if (i+1)%100==0:
            print("PROGRESS",i+1,"/",len(specs),
                  "fits",diagnostics["trained_fits"],
                  "feasible_ml",len(best),"eligible_pairs",diagnostics["eligible_candidate_pairs"],flush=True)
    if not best:
        result={"status":"NO_MODEL_MEETS_PRE2025_MDD_BUFFER",
                "diagnostics":diagnostics,"selected":None}
        (OUT/"ai150_result.json").write_text(json.dumps(result,indent=2))
        print("AI150_RESULT",json.dumps(result),flush=True)
        return result
    best.sort(key=lambda s:s["dev_score"],reverse=True)
    chosen=best[0]
    # HOLDOUT GATE: select one candidate by development data only, and
    # refit exactly that candidate on all preceding years in 2025/26.
    p=np.full(len(idx),.5,float)
    seen=np.zeros(len(idx),bool)
    holdout_fit=[]
    for start,end in VAL_FOLDS+FUTURE_FOLDS:
        v,ntr,nte=fitted_scores(chosen["spec"],x,y,idx,start,end)
        test=(idx>=pd.Timestamp(start,tz="UTC"))&(idx<pd.Timestamp(end,tz="UTC"))
        p[test]=v;seen[test]=True
        holdout_fit.append({"test":start+".."+end,"train_rows":ntr,"test_rows":nte})
    policy=chosen["policy"]
    e,k=overlay(r,p,seen,policy["base"],policy["map"],
                *RISK_CONTROLS[policy["control_id"]])
    full=stats(e,idx)
    test=stats(e,idx,"2025-01-01")
    # Show F-style DAILY sensitivity only; this is NOT actual F.
    from .mdd10_frontier import f_proxy_base
    f=f_proxy_base(r)
    fr=np.diff(np.r_[1.,f])/np.r_[1.,f[:-1]]
    ef,kf=overlay(fr,p,seen,policy["base"],policy["map"],
                  *RISK_CONTROLS[policy["control_id"]])
    ffull=stats(ef,idx);ftest=stats(ef,idx,"2025-01-01")
    output={
      "status":"PASSED_DAILY_PROXY_150_10" if full["cagr"]>=150 and full["mdd"]<10
                     and test["mdd"]<10 else "TARGET_NOT_PROVEN",
      "full_goal":{"CAGR_pct_at_least":150,"daily_close_MDD_pct_below":10},
      "definition":"AI daily-risk overlay on original three-bot protected daily returns; no new order replay",
      "source":"2021-10-05 to 2026-10-04 full shared-account protected-rule daily equity, BTC official Binance archive",
      "selection_cutoff":"2025-01-01; 2025-26 never used in parameter selection by this script",
      "research_holdout_caveat":"Previous experiments inspected 2025-26; this is NOT pristine project-level holdout.",
      "diagnostics":diagnostics,
      "winning_spec_pre2025":chosen,
      "refit_fold_count":holdout_fit,
      "no_F_selected_model":{"full_5y":full,"posthoc_2025_26":test,
         "mean_multiplier":float(k.mean()),"risk_max":float(k.max()),
         "meets_both_full":bool(full["cagr"]>=150 and full["mdd"]<10),
         "meets_both_late":bool(test["cagr"]>=150 and test["mdd"]<10)},
      "F_style_proxy_not_actual_F":{"full_5y":ffull,"posthoc_2025_26":ftest,
         "meets_both_full":bool(ffull["cagr"]>=150 and ffull["mdd"]<10)},
      "fifty_best_dev_candidates":best[:50],
      "unmodelled":[
        "Exact 35-symbol 1min execution, entry/exit changes and position MTM under counterfactual sizing",
        "Native funding and entry/cut fees; original fees remain in baseline returns only",
        "Claude real F risk manager and live position reduction; F-style scenario is not F",
        "Intraday drawdown, gaps, liquidation, margin cap and trading latency",
        "Selection multiplicity: over 1000 ML configurations and thousands of overlays searched.",
        "Reference account return features require an always-on unfiltered SHADOW account."
      ],
      "operational_decision":"NEVER_DEPLOY from daily overlay alone",
    }
    pd.DataFrame({"date":idx.astype(str),"base_reference":eq/10000.,
        "no_F_ai_model":e,"f_style_ai_proxy":ef,"pred_percentile":p,
        "has_model":seen.astype(int),"risk_noF":k,"risk_Fstyle":kf}).to_csv(
        OUT/"winner_daily_paths.csv",index=False)
    (OUT/"ai150_result.json").write_text(json.dumps(output,indent=2,ensure_ascii=False))
    plot(idx,eq/10000.,e,ef)
    print("AI150_RESULT",json.dumps({k:output[k] for k in (
       "status","diagnostics","winning_spec_pre2025",
       "no_F_selected_model","F_style_proxy_not_actual_F")}),flush=True)
    return output

def plot(idx,reference,selected,proxy):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(2,1,figsize=(15,11),sharex=True)
    for name,vec in (("original 3 bots (not risk controlled)",reference),
                     ("AI selected NO-F daily overlay",selected),
                     ("AI + daily F-style PROXY (not F)",proxy)):
        axs[0].plot(idx,vec,label=name,lw=1.2)
        axs[1].plot(idx,100*(vec/np.maximum.accumulate(np.r_[1.,vec])[1:]-1),
                    label=name,lw=1.2)
    axs[0].set_yscale("log");axs[0].legend(fontsize=9)
    axs[0].set_ylabel("Account multiple, daily close (log)")
    axs[0].set_title("1010 AI configs × 128 risk wrappers × 2023/24 folds; NOT exact execution")
    axs[1].axhline(-10,color="red",linestyle="--",lw=1)
    axs[1].set_ylabel("Max daily-close drawdown (%)")
    axs[1].legend(fontsize=9);fig.tight_layout()
    fig.savefig(OUT/"ai150_equity_dd.png",dpi=150)
    plt.close(fig)

if __name__=="__main__":
    scout()
