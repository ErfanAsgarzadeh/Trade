"""1,280+ causal ML/risk policies to seek CAGR>150% with daily MDD<10%.

INPUT:
- current three-bot protected 2021-10-05..2026-10-04 equity (daily_final.npy)
- SHA256-verified archived BTC 1-minute history, resampled to daily.
The base trading strategy entries/stops are unchanged.

EVIDENCE:
This is a **daily equity overlay simulator**, NOT a 35-coin, minute-level
execution replay or real Claude F. Overlay applies model-generated daily risk
scalar to original reference account returns. It cannot reconstruct changed
fills, partial closes, fees, funding, margin, intraday MDD or original F cuts.
It is useful for REJECTING weak risk/signal ideas, not for deployable PnL
claims. Do NOT transfer selected config to running PAPER/LIVE.

TRAINING:
Features on decision date t are lagged to end of day t-1. Targets are
forward 7d or 14d returns/drawdown. At each January fold, train with labels
whose entire horizon ends strictly before the January boundary, purge 21d.
Imputer and StandardScaler are fitted only on X_train inside each fold.
Models are independently refitted at 2023, 2024, 2025 and 2026, so live
sequential predictions have no future information.

Protocol:
A fixed grid of 40 x 32 = 1280 ML+decision configurations.
Predictions 2023 and 2024 are used for model selection. The 2025-26
predictions are evaluated once in the final report; prior research saw
2025-26 base strategy results so whole-strategy OOS isn't pristine.
Apply temporal split gate (2023&2024 MDD<8.5% plus 2024 CAGR) to avoid
cherry-picking full-five-year period.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import itertools
import json
import warnings
import numpy as np
import pandas as pd
from numba import njit
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor, ExtraTreesRegressor, RandomForestClassifier
from sklearn.linear_model import Ridge, LogisticRegression
from .mdd10_frontier import load_ref,stats,OUT as ROOT_OUT,TEST
from .btc_market import load_btc_4h

OUT=ROOT_OUT/"ml_150_10"
SEED=20261103
HORIZONS=(7,14)
FOLDS=("2023-01-01","2024-01-01","2025-01-01","2026-01-01")
END="2026-10-05"
LIMIT_DD=10.
PRESELECTION_DD=8.5
FEATURES=[
 "sys_ret1","sys_ret3","sys_ret7","sys_ret14","sys_ret30",
 "sys_vol7","sys_vol20","sys_vol60","sys_downside20",
 "sys_dd","sys_dd30","sys_positive20",
 "btc_ret1","btc_ret3","btc_ret7","btc_ret14","btc_ret30",
 "btc_vol7","btc_vol20","btc_ma20","btc_ma50","btc_ma100",
 "btc_rsi14","btc_range14","sys_btc_corr30","sys_btc_beta30"
]

def get_data():
    _,idx,r=load_ref()
    bars=load_btc_4h()
    btc=bars.close.resample("1D").last().reindex(idx)
    if btc.isna().any():raise ValueError(f"BTC missing {int(btc.isna().sum())} UTC days")
    return idx,r,btc

def build_features(index,r,btc):
    """Feature value at date t uses only daily closes through t-1."""
    b=btc.astype(float)
    s=pd.Series(r,index=index)
    cum=(1+s).cumprod()
    br=b.pct_change()
    f=pd.DataFrame(index=index)
    f["sys_ret1"]=s
    for n in (3,7,14,30):
        f[f"sys_ret{n}"]=cum/cum.shift(n)-1
    for n in (7,20,60):
        f[f"sys_vol{n}"]=s.rolling(n,min_periods=n).std()
    f["sys_downside20"]=np.sqrt(s.clip(upper=0).pow(2).rolling(20,min_periods=20).mean())
    f["sys_dd"]=cum/cum.cummax()-1
    f["sys_dd30"]=cum/cum.rolling(30,min_periods=30).max()-1
    f["sys_positive20"]=s.gt(0).rolling(20,min_periods=20).mean()
    f["btc_ret1"]=br
    for n in (3,7,14,30):
        f[f"btc_ret{n}"]=b.pct_change(n)
    for n in (7,20):
        f[f"btc_vol{n}"]=br.rolling(n,min_periods=n).std()
    for n in (20,50,100):
        f[f"btc_ma{n}"]=b/b.rolling(n,min_periods=n).mean()-1
    dx=b.diff()
    up=dx.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    dn=(-dx.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    f["btc_rsi14"]=100-100/(1+up/dn.replace(0,np.nan))
    f["btc_range14"]=(b-b.rolling(14).min())/(b.rolling(14).max()-b.rolling(14).min()).replace(0,np.nan)
    corr=s.rolling(30).corr(br)
    f["sys_btc_corr30"]=corr
    f["sys_btc_beta30"]=corr*s.rolling(30).std()/br.rolling(30).std().replace(0,np.nan)
    f=f[FEATURES].replace([np.inf,-np.inf],np.nan).shift(1)
    return f

def make_targets(r):
    """Causal target for action on day t, known only after t+H-1."""
    y={}
    a=np.asarray(r,float)
    for h in HORIZONS:
        z=np.full(len(a),np.nan);worst=np.full(len(a),np.nan)
        for i in range(len(a)-h+1):
            path=np.cumprod(1+a[i:i+h])
            z[i]=np.log(max(1e-12,path[-1]))
            worst[i]=min(0.,float(path.min()-1))
        y[(h,"ret")]=z
        y[(h,"drawdown")]=worst
        y[(h,"binary")]=(z>0).astype(float)
        y[(h,"binary")][~np.isfinite(z)]=np.nan
    return y

def model_grid():
    """40 DISTINCT fitted models, 32 risk policy variants each: 1280 arms."""
    grid=[]
    for target,h in itertools.product(("ret","drawdown","binary"),HORIZONS):
        for reg in (.1,2.0):
            if target=="binary":
                grid.append(dict(algorithm="logistic",target=target,h=h,reg=reg))
            else:
                grid.append(dict(algorithm="ridge",target=target,h=h,reg=reg))
        for depth in (2,4):
            grid.append(dict(algorithm="hgb",target=target,h=h,depth=depth))
            grid.append(dict(algorithm="extratrees",target=target,h=h,depth=depth))
    assert len(grid)==36
    # Four additional nonlinear/deeper configurations: total 40.
    for t in ("ret","drawdown"):
        for h in HORIZONS:
            grid.append(dict(algorithm="rf",target=t,h=h,depth=5))
    assert len(grid)==40
    return grid

def make_pipeline(c):
    a=c["algorithm"];d=c.get("depth",3)
    if a=="ridge":mdl=Ridge(alpha=c["reg"],random_state=SEED)
    elif a=="logistic":mdl=LogisticRegression(C=1./c["reg"],max_iter=500,random_state=SEED)
    elif a=="hgb":mdl=HistGradientBoostingRegressor(max_iter=65,max_leaf_nodes=(5 if d==2 else 11),
              learning_rate=.05,min_samples_leaf=25,l2_regularization=7.,random_state=SEED)
    elif a=="extratrees":mdl=ExtraTreesRegressor(n_estimators=75,max_depth=(4 if d==2 else 9),
              min_samples_leaf=15,max_features=.6,n_jobs=1,random_state=SEED)
    elif a=="rf":mdl=RandomForestRegressor(n_estimators=75,max_depth=7,
              min_samples_leaf=20,max_features=.7,n_jobs=1,random_state=SEED)
    else:raise ValueError(a)
    return Pipeline([("imputer",SimpleImputer(strategy="median",keep_empty_features=True)),
                     ("scale",StandardScaler()),("model",mdl)])

def train_predictions(X,targets,index):
    n=len(index)
    arr=X.to_numpy(float)
    result={key:np.full(n,np.nan) for key in range(len(model_grid()))}
    audits=[]
    for d,fold_end in zip(FOLDS,(*FOLDS[1:],END)):
        t0=pd.Timestamp(d,tz="UTC");t1=pd.Timestamp(fold_end,tz="UTC")
        start=np.flatnonzero(index>=t0)[0]
        end=np.flatnonzero(index>=t1)[0] if t1<=index[-1] else n
        te=np.arange(start,end)
        if not len(te):continue
        for j,c in enumerate(model_grid()):
            h=c["h"]
            # Purge by known completion of every label; also fixed 21d embargo.
            eligible=np.flatnonzero((index<t0-pd.Timedelta(days=21))&
                            np.isfinite(targets[(h,c["target"])]))
            eligible=eligible[eligible+h<start]
            if len(eligible)<240:continue
            xtr=arr[eligible];ytr=targets[(h,c["target"])][eligible]
            if c["target"]=="binary" and len(np.unique(ytr))<2:continue
            mdl=make_pipeline(c);mdl.fit(xtr,ytr)
            xte=arr[te]
            pred=(mdl.predict_proba(xte)[:,1] if c["algorithm"]=="logistic"
                  else mdl.predict(xte))
            result[j][te]=np.asarray(pred,float)
        audits.append({"train_cutoff":str(t0.date()),
              "test_until_exclusive":str(t1.date()),"test_count":len(te),
              "strict_label_embargo_days":21,
              "max_train_day":str((index[start-22]).date()),
              "models_fitted":sum(int(np.isfinite(result[k][te]).all()) for k in result)})
        print("WF_FOLD",json.dumps(audits[-1]),flush=True)
    return result,audits

@dataclass(frozen=True)
class Gate:
    floor:float
    boost:float
    q:float
    smooth:int
    dd_hard:float
    release:int

def policy_grid():
    """Fixed 32 wrappers per fitted ML model (model total 40)."""
    out=[]
    for floor in (.0,.20):
        for boost in (1.5,2.5):
            for q in (.3,.6):
                for smooth in (1,7):
                    for release in (0,30):
                        out.append(Gate(floor,boost,q,smooth,.085,release))
    assert len(out)==32
    return out

@njit(cache=True)
def replay_numba(r,scores,floor,boost,q,smooth,dd_hard,release):
    n=len(r);eq=np.ones(n+1);sizes=np.ones(n);peaks=np.ones(n+1)
    current_max=1.
    # score array already ONLINE out-of-sample predicted. Ranking threshold
    # is expanding-history empirical quantile of only EARLIER predictions.
    for i in range(n):
        # Startup: no estimated score, defer to fixed risk 0.32
        if np.isnan(scores[i]) or i<400:
            mult=.32
        else:
            v=0.;count=0
            for j in range(max(0,i-smooth+1),i+1):
                if np.isfinite(scores[j]):v+=scores[j];count+=1
            val=v/count if count>0 else 0.
            lo=0.;hi=0.;samples=0
            # Compute rank without seeing future test data.
            lookback=min(500,i)
            for j in range(i-lookback,i):
                if np.isfinite(scores[j]):
                    samples+=1
                    if scores[j]<=val:lo+=1
                    if scores[j]>=val:hi+=1
            rank=lo/samples if samples>0 else .5
            if rank<q:mult=floor
            elif rank>1-q/2:mult=boost
            else:mult=1.
        # Permanent global-account drawdown brake acts on risk from *yesterday*
        # only; optional rolling-peak release lets risk recover sooner.
        peak=current_max
        if release>0 and i>=release:
            peak=eq[i]
            for z in range(i-release,i):
                peak=max(peak,eq[z])
        dd=max(0.,1-eq[i]/peak)
        if dd>.04:
            mult*=max(.05,1.-(dd-.04)/(.085-.04)*.95)
        if dd>dd_hard:mult=min(mult,.08)
        mult=min(3.,max(0.,mult))
        # Added adverse-gap correction cannot be simulated without OHLC.
        eq[i+1]=max(1e-12,eq[i]*(1+mult*r[i]))
        current_max=max(current_max,eq[i+1])
        peaks[i+1]=current_max
        sizes[i]=mult
    return eq[1:],sizes

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    ix,r,btc=get_data()
    features=build_features(ix,r,btc)
    targets=make_targets(r)
    predictions,audits=train_predictions(features,targets,ix)
    # Original F-style baseline is a separately declared reference, NOT real F.
    from .mdd10_frontier import f_proxy_base
    f=f_proxy_base(r)
    fr=np.diff(np.r_[1.,f])/np.r_[1.,f[:-1]]
    metadata={"method_count":len(model_grid()),"policy_count":len(policy_grid()),
              "configuration_count":len(model_grid())*len(policy_grid()),
              "folds":audits,
              "comparators":["unmodified three bots daily NAV","F-style proxy only, NOT real F"],
              "selection":"2023 and 2024 model validation, OOS 2025-26 never used for tuning in this run",
              "no_true_F":True,"no_real_fills":True,
              "intraday_dd_unavailable":True}
    report={"audit":metadata,"modes":{}}
    tests=(("NoF",r),("Fstyle_NotRealF",fr))
    top_curves={}
    for tag,reference in tests:
        arms=[]
        for j,c in enumerate(model_grid()):
            sig=predictions[j]
            for k,g in enumerate(policy_grid()):
                eq,sizes=replay_numba(reference,sig,g.floor,g.boost,g.q,g.smooth,g.dd_hard,g.release)
                d23=stats(eq,ix,"2023-01-01","2024-01-01")
                d24=stats(eq,ix,"2024-01-01","2025-01-01")
                # Do not score on ANY 2025/2026 return here.
                if d23["mdd"]>=PRESELECTION_DD or d24["mdd"]>=PRESELECTION_DD:
                    v=-np.inf
                else:
                    v=.5*(d23["cagr"]+d24["cagr"])-.3*abs(d24["cagr"]-d23["cagr"])
                arms.append((v,j,k,eq,sizes,d23,d24))
        eligible=[z for z in arms if np.isfinite(z[0])]
        chosen=max(eligible,key=lambda z:z[0]) if eligible else None
        basecurve=np.cumprod(1+reference)
        base_stats=stats(basecurve,ix)
        baseline_2025=stats(basecurve,ix,TEST)
        ranking=[]
        # Preserve 10 selected by pre-2025 criteria only.
        for rank,z in enumerate(sorted(eligible,key=lambda z:z[0],reverse=True)[:10],1):
            score,j,k,eq,sizes,v23,v24=z
            full=stats(eq,ix);test=stats(eq,ix,TEST)
            row={"rank_pre2025":rank,"model":model_grid()[j],"policy":asdict(policy_grid()[k]),
                 "score":score,"development_2023":v23,"validation_2024":v24,
                 "full":full,"post_selected_2025_26":test,
                 "passes_full_CAGR150_MDD10":bool(full["cagr"]>150 and full["mdd"]<10),
                 "passes_2025_26_CAGR150_MDD10":bool(test["cagr"]>150 and test["mdd"]<10),
                 "mean_risk":float(sizes.mean())}
            ranking.append(row)
        result={"baseline_full":base_stats,"baseline_2025_26":baseline_2025,
                "eligible_pre2025":len(eligible),"total_searched":len(arms),
                "top10":ranking,
                "selected":ranking[0] if ranking else None}
        report["modes"][tag]=result
        if chosen:
            top_curves[tag]=chosen[3]
        print("AI_1280_MODE",tag,json.dumps({
            "total":len(arms),"eligible":len(eligible),
            "winner":result["selected"],
            "baseline":base_stats},default=float),flush=True)
    (OUT/"results.json").write_text(json.dumps(report,indent=2,default=float))
    pd.DataFrame({"date":ix.astype(str),**top_curves}).to_csv(OUT/"selected_daily_equity.csv",index=False)
    pd.DataFrame([{"mode":m,**row} for m,s in report["modes"].items()
                   for row in s["top10"]]).to_json(OUT/"top10_each_mode.json",orient="records",indent=2)
    print("REPORT",json.dumps({"modes":{m:{
        "eligible":r["eligible_pre2025"],
        "winner_full":r["selected"]["full"] if r["selected"] else None,
        "winner_holdout":r["selected"]["post_selected_2025_26"] if r["selected"] else None
    } for m,r in report["modes"].items()}},default=float),flush=True)
    return report

if __name__=="__main__":run()
