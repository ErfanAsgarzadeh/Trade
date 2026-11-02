"""Leak-free 7-configuration 5-year research screen on pre-existing trade legs.

STRICT LIMITS: cached winrate/legs.pkl was generated BEFORE latest Mojsavar
+1R profit lock / 50% at +2R. Exactly reproducing current three-bot portfolio
needs 35-symbol 1m tapes + protected exits. Actual F needs 35-symbol indicators,
market regime risk AI and dynamic cuts. This file offers explicit F-STYLE ENTRY
PROXY only, NEVER "F enabled". Costs already in source leg unit: 0.0006 taker
EACH SIDE plus 0.0002 slip EACH SIDE; the supplied 0.0005 fee cannot be exactly
re-priced without the source exit prices and funding increments.

An actual exact F/0.0005 per-side production comparison MUST fail closed, not
substitute these screening numbers. Features at signal events came from last
completed 4h bars, as documented in winrate/ledger.py. Never use future MFE
or MAE as predictor. Label is historical realised R>0 (NOT triple barrier),
and label availability is max exit minute of each root, purged before fold start.
Tests are EXPANDING chronological at 12-month boundaries (2023-2026).
Model fitting happens only on fully exited pre-fold events, and imputer,
scalers and calibration each fit exclusively to the fold train/development.
Warm-up before 2023 uses baseline rules across all arms.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import math
import warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import IsolationForest,RandomForestClassifier
from sklearn.mixture import GaussianMixture
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from scipy.special import logsumexp
from hmmlearn.hmm import GaussianHMM
from xgboost import XGBClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"ai_research/output/seven_methods"
SOURCE=ROOT/"high_cagr/output/ideas/winrate/legs.pkl"
ORIGIN=pd.Timestamp("2021-10-05",tz="UTC")
STOP=pd.Timestamp("2026-10-05",tz="UTC")
FIRST_TEST=pd.Timestamp("2023-01-01",tz="UTC")
EMBARGO_MINUTES=20*240  # 20 closed 4h candles
SEED=20261102
COLS=["f_atrp","f_atr_rank","f_adx","f_rsi_s","f_d_e20","f_d_e50",
      "f_slope50","f_slope200","f_ret6","f_ret24","f_ret60",
      "f_range_atr","f_body","f_vol_rel","f_don20","f_room60",
      "f_htf","f_btc_e200","f_btc_e50","f_btc_ret6","f_btc_ret42",
      "f_btc_atr_rank","f_fund8h","f_fund3d","f_stop_frac"]
REGIME=["f_btc_ret6","f_atrp"]
CLUSTER=["f_ret6","f_atrp","f_d_e50","f_slope50","f_htf"]
ANOM=["f_atrp","f_range_atr","f_body","f_vol_rel","f_atr_rank"]
NAMES=["Baseline (Raw)","M1 XGBoost meta-label","M2 HMM regime",
       "M3 GMM clustering","M4 Isolation Forest",
       "M5 Calibrated RF Half-Kelly","M6 HMM + XGBoost + Kelly"]

def load():
    df=pd.read_pickle(SOURCE)
    expected=set(COLS+["em","xm","root","bot","side","coin","unit",
                       "entry","stop_frac","risk_scale","R","is_add"])
    if not expected.issubset(df):raise ValueError(f"Source columns missing: {expected-set(df)}")
    if df.root.isna().any() or (df.entry<=0).any() or (df.stop_frac<=0).any():
        raise ValueError("Invalid source ledger")
    if not np.isfinite(df[["em","xm","entry","stop_frac","unit","risk_scale"]]).all().all():
        raise ValueError("Invalid numeric source")
    if (df.xm<df.em).any():raise ValueError("Exit before entry")
    df=df.sort_values(["em","xm"],kind="stable").reset_index(drop=True)
    # Source is unprotected C3. Apply latest Shahin late-entry filter to root
    # only, using a contemporaneous feature and a config-shipped threshold.
    drop=set(df.loc[(df.bot=="main")&(~df.is_add)&(df.f_ret60>0.1521),"root"])
    df=df.loc[~df.root.isin(drop)].copy()
    df["entry_date"]=ORIGIN+pd.to_timedelta(df.em,unit="m")
    df["exit_date"]=ORIGIN+pd.to_timedelta(df.xm,unit="m")
    roots=[]
    for key,g in df.groupby("root",sort=False):
        root=g.loc[~g.is_add]
        if len(root)!=1:raise ValueError(f"Invalid root for child entries: {key}")
        q=root.iloc[0].copy()
        q["root_exit_min"]=int(g.xm.max())
        q["realized_r"]=float(np.sum(g.R*g.risk_scale)/max(1e-10,g.risk_scale.sum()))
        q["label"]=int(q["realized_r"]>0)
        roots.append(q)
    t=pd.DataFrame(roots).sort_values(["em","root"],kind="stable").reset_index(drop=True)
    if len(t)<1800:raise ValueError("Insufficient training opportunities")
    return df,t,{"n_legs":len(df),"n_roots":len(t),"late_rejected_roots":len(drop)}

def fold_boundaries():
    return list(pd.date_range(FIRST_TEST,STOP,freq="YS",tz="UTC",inclusive="left"))+[STOP]

def masks(t,lo,hi):
    lo_m=(lo-ORIGIN).total_seconds()/60.
    hi_m=(hi-ORIGIN).total_seconds()/60.
    # Always purge by EXIT availability, even for labels from original strategy.
    tr=((t.em<lo_m)&(t.root_exit_min<lo_m-EMBARGO_MINUTES)).to_numpy()
    te=((t.em>=lo_m)&(t.em<hi_m)).to_numpy()
    # Calibration trained on the later historical 25%, after an exit-based
    # embargo and with the earlier base model never trained on it.
    return tr,te

def scaler(x,mask,cols):
    arr=x[cols].astype(float).replace([np.inf,-np.inf],np.nan).to_numpy()
    pipe=Pipeline([("imputer",SimpleImputer(strategy="median")),
                   ("scale",RobustScaler(quantile_range=(10,90)))])
    a=pipe.fit_transform(arr[mask])
    return a,pipe.transform(arr),pipe

def pure_imputed(x,mask,cols):
    a=x[cols].astype(float).replace([np.inf,-np.inf],np.nan).to_numpy()
    p=SimpleImputer(strategy="median").fit(a[mask])
    return p.transform(a)

def hmm_filter(model,arr):
    """Forward filter posterior P(z_t | x_0..x_t), never Viterbi/smoothed posterior.

    Native hmmlearn predict/predict_proba on test sequences would leak future
    observations through backward smoothing; this is intentionally avoided.
    """
    ll=model._compute_log_likelihood(arr)
    logtrans=np.log(np.clip(model.transmat_,1e-300,1))
    alpha=np.log(np.clip(model.startprob_,1e-300,1))+ll[0]
    alpha-=logsumexp(alpha)
    post=[np.exp(alpha)]
    for i in range(1,len(arr)):
        alpha=logsumexp(alpha[:,None]+logtrans,axis=0)+ll[i]
        alpha-=logsumexp(alpha)
        post.append(np.exp(alpha))
    return np.array(post)

def _gain_ratio(y,ret):
    wins=ret[(y==1)&np.isfinite(ret)]
    losses=ret[(y==0)&np.isfinite(ret)]
    if len(wins)<10 or len(losses)<10:
        return 1.
    return float(np.clip(np.mean(wins)/max(1e-9,-np.mean(losses)),.30,6.))

def _clf_input(t,tr,te,cols=COLS):
    aa,allx,_=scaler(t,tr,cols)
    return aa,allx[tr],allx[te],allx

def _models(t,tr,te):
    """One fold produces six strictly OOS decisions. All calibration is past only."""
    n=len(t)
    y=t.label.to_numpy(int)
    R=t.realized_r.to_numpy(float)
    tr_idx=np.flatnonzero(tr)
    te_idx=np.flatnonzero(te)
    if len(tr_idx)<120 or len(te_idx)==0:
        return {name:(np.ones(len(te_idx),bool),np.ones(len(te_idx))) for name in NAMES[1:]}
    _,xtr,xte,xall=_clf_input(t,tr,te)
    # Fully chronological, exit-purged *inner* training-calibration split.
    # Cal rows are last 25% of outer eligible TRAIN data by ENTRY.
    split=t.iloc[tr_idx[max(0,int(len(tr_idx)*.75))]].em
    f_idx=tr_idx[(t.em.to_numpy()[tr_idx]<split-EMBARGO_MINUTES)&
                 (t.root_exit_min.to_numpy()[tr_idx]<split-EMBARGO_MINUTES)]
    c_idx=tr_idx[t.em.to_numpy()[tr_idx]>=split]
    if len(f_idx)<80 or len(c_idx)<30 or len(np.unique(y[f_idx]))<2 or len(np.unique(y[c_idx]))<2:
        f_idx=tr_idx;c_idx=np.array([],dtype=int) # RF defaults neutral, XGB model still available
    # XGBoost on native profitable trade labels: not TP/SL barrier label.
    xgb=XGBClassifier(n_estimators=65,max_depth=3,learning_rate=.05,
                      subsample=.9,colsample_bytree=.9,min_child_weight=15,
                      reg_lambda=15.,objective="binary:logistic",
                      random_state=SEED,n_jobs=1,eval_metric="logloss",
                      tree_method="hist")
    xgb.fit(xall[f_idx],y[f_idx])
    p_xgb=xgb.predict_proba(xte)[:,1]
    outputs={NAMES[1]:(p_xgb>=.55,np.ones(len(te_idx)))}

    # HMM: only event-time observations, BTC directional return converted back
    # to raw return and scale-invariant volatility; filter states causally.
    d=t.copy()
    d["f_btc_ret6"]=t.f_btc_ret6*t.side # original feature signed by position side
    htrain,hall,_=scaler(d,tr,REGIME)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hmm=GaussianHMM(n_components=3,covariance_type="diag",n_iter=12,implementation="scaling",
                        min_covar=1e-3,random_state=SEED)
        hmm.fit(htrain)
    # State identity assigned from filtered posterior of TRAIN only.
    hist=hmm_filter(hmm,htrain).argmax(1)
    test_hmm=hmm_filter(hmm,hall[np.r_[tr_idx,te_idx]]).argmax(1)[-len(te_idx):]
    policy={}
    for state in range(3):
        r=R[tr_idx][hist==state]
        policy[state]=(len(r)<15 or float(r.mean())>0)
    good=np.array([policy[z] for z in test_hmm])
    outputs[NAMES[2]]=(good,np.ones(len(te_idx)))

    # GMM clusters selected strictly with train labels (not future test returns).
    gtrain,gall,_=scaler(t,tr,CLUSTER)
    gmm=GaussianMixture(n_components=5,covariance_type="diag",n_init=1,max_iter=65,
                        reg_covar=.015,random_state=SEED).fit(gtrain)
    a=gmm.predict(gtrain);b=gmm.predict(gall[te_idx])
    mean={s:float(R[tr_idx][a==s].mean()) if (a==s).sum()>=12 else np.nan
          for s in range(5)}
    valid=[s for s in mean if np.isfinite(mean[s])]
    keep=set(s for s in valid if mean[s]>0)
    # If all states unprofitable, block all (no hindsight escape).
    outputs[NAMES[3]]=(np.isin(b,list(keep)),np.ones(len(te_idx)))

    ai,_,_=scaler(t,tr,ANOM)
    all_anom=pure_imputed(t,tr,ANOM)
    # Strictly need same transform for train and test (including scaling).
    _,all_anom_scaled,_=scaler(t,tr,ANOM)
    iso=IsolationForest(contamination=.04,n_estimators=90,
                        max_samples=min(256,len(ai)),random_state=SEED,n_jobs=1)
    iso.fit(ai)
    outputs[NAMES[4]]=(iso.predict(all_anom_scaled[te_idx])==1,np.ones(len(te_idx)))

    # Half-Kelly: RF pre-fit on PAST part; calibrator strictly on *later
    # non-overlapping historical calibration rows*, with scikit FrozenEstimator.
    rf=RandomForestClassifier(n_estimators=95,max_depth=6,min_samples_leaf=16,
                              max_features=.7,class_weight="balanced",
                              n_jobs=1,random_state=SEED)
    rf.fit(xall[f_idx],y[f_idx])
    if len(c_idx)>=30:
        cal=CalibratedClassifierCV(FrozenEstimator(rf),method="sigmoid")
        cal.fit(xall[c_idx],y[c_idx])
        p=cal.predict_proba(xte)[:,1]
        p_cal_train=cal.predict_proba(xall[c_idx])[:,1]
    else:
        p=rf.predict_proba(xte)[:,1]
        p_cal_train=rf.predict_proba(xall[f_idx])[:,1]
    b_ratio=_gain_ratio(y[tr_idx],R[tr_idx])
    # Half-Kelly fraction in *risked capital units*, not direct notional.
    f=lambda q:np.maximum(0.,.5*(q*b_ratio-(1-q))/b_ratio)
    ref=max(.01,float(np.nanmedian(f(p_cal_train))))
    size=np.clip(f(p)/ref,.25,2.)
    outputs[NAMES[5]]=(np.ones(len(te_idx),bool),size)

    # Hybrid HMM state added to an XGB classifier, retrained on past only;
    # HMM feature inferred by forward filtering, not smoother.
    # HMM state posterior generated for fold observations; calibration
    # model sees train-only states from the same fitted HMM.
    trainstate=hmm_filter(hmm,htrain).argmax(1)
    hxtr=np.c_[xall[f_idx],np.eye(3)[trainstate[np.searchsorted(tr_idx,f_idx)]]]
    hxtest=np.c_[xte,np.eye(3)[test_hmm]]
    hyb=XGBClassifier(n_estimators=110,max_depth=3,learning_rate=.04,
                      min_child_weight=15,reg_lambda=15.,
                      random_state=SEED,n_jobs=1,eval_metric="logloss",tree_method="hist")
    hyb.fit(hxtr,y[f_idx])
    hp=hyb.predict_proba(hxtest)[:,1]
    # HMM gating with supervised predicted probs, Kelly size from fitted RF.
    outputs[NAMES[6]]=(good & (hp>=.55),size)
    return outputs

def generate_decisions(t):
    """Produce exactly one OOS prediction per root/fold; no lookahead."""
    n=len(t)
    action={name:np.ones(n,dtype=bool) for name in NAMES}
    weights={name:np.ones(n,dtype=float) for name in NAMES}
    record=[]
    edges=fold_boundaries()
    for lo,hi in zip(edges[:-1],edges[1:]):
        train,test=masks(t,lo,hi)
        ntr=int(train.sum());nte=int(test.sum())
        if nte==0:continue
        assert np.all(t.loc[train,"root_exit_min"]+EMBARGO_MINUTES<
                      (lo-ORIGIN).total_seconds()/60),lo
        print("START_MODEL_FOLD",str(lo.date()),"train",ntr,"test",nte,flush=True)
        outputs=_models(t,train,test)
        ids=np.flatnonzero(test)
        for name,(a,k) in outputs.items():
            action[name][ids]=a
            weights[name][ids]=k
        record.append(dict(train_end=str(lo.date()),test_end=str(hi.date()),
                           fully_exited_purged_train=ntr,test_events=nte,
                           embargo_4h_bars=20))
        print("FOLD",record[-1],flush=True)
    return action,weights,record

def daily_realized_replay(legs,root_keep,root_mult,mode="off"):
    """Portfolio SCREEN: 5x leverage/80% margin cap, exits credit PnL only.

    Historical exit unit already includes funding+fee+slippage from *source*
    (0.0006 and 0.0002 per side). NO extra double-deducted commissions.
    Daily in-trade MTM and F open position reductions cannot be reconstructed.
    """
    d=legs
    n=len(d)
    ev=sorted([(int(r.em),1,i) for i,r in d.iterrows()]+
              [(int(r.xm),0,i) for i,r in d.iterrows()],
              key=lambda z:(z[0],z[1],z[2]))
    E=10000.
    L=5.;cap=.8
    risk={"main":.01,"c3":.004,"pa":.004}
    start_min=int(d.em.min())
    days=(STOP-ORIGIN).days
    close_daily=np.zeros(days)
    root_skipped=set()
    orders={}
    closed=[]
    fees=.0012;slip=.0004  # source 0.0006 fee + 0.0002 slip EACH side
    hwm=E
    history=[]
    def mult(day):
        if mode=="off":return 1.
        if not history:return 1.
        past=np.array([v for di,v in history if di<day],float)
        if len(past)<1:return 1.
        dd=max(0.,1-E/max(hwm,E))
        brake=1. if dd<=.08 else max(.2,1-.8*(dd-.08)/.06)
        vt=1.
        if len(past)>=21:
            s=np.std(past[-20:])
            if s>1e-9:vt=float(np.clip(.01/s,.3,1.5))
        return 1.41*brake*vt
    k=0
    for day in range(days):
        end=(day+1)*1440
        while k<len(ev) and ev[k][0]<end:
            minute,typ,i=ev[k];r=d.loc[i]
            root=str(r.root)
            if typ==0:
                if i in orders:
                    q,notional=orders.pop(i)
                    pnl=float(q*r.unit)
                    E+=pnl;closed.append((day,root,pnl,notional))
            else:
                if root in root_skipped or not root_keep.get(root,True):
                    root_skipped.add(root);continue
                if r.is_add and root not in root_mult:continue
                if E<=0:root_skipped.add(root);continue
                # Previous completed UTC days only, even for minute entries.
                m=mult(day)
                k_mult=max(0.,min(2.,float(root_mult.get(root,1.))))
                nominal=(risk[r.bot]*float(r.risk_scale)*E*m*k_mult/
                         (float(r.stop_frac)+fees+slip))
                occupied=sum(v[1]/L for v in orders.values())
                free=max(0.,cap*E-occupied)*L/(1+cap*L*fees)
                val=min(nominal,free)
                if val<20.:root_skipped.add(root);continue
                orders[i]=(val/float(r.entry),val)
            k+=1
        prev=close_daily[day-1] if day else 10000.
        close_daily[day]=max(E,1e-8)
        history.append((day,close_daily[day]/max(1e-8,prev)-1))
        hwm=max(hwm,E)
    return close_daily,pd.DataFrame(closed,columns=["day","root","pnl","notional"])

def metrics(daily,closed):
    q=np.r_[10000.,daily]
    daily_r=q[1:]/q[:-1]-1
    n=len(daily)
    positive=closed.loc[closed.pnl>0,"pnl"].sum()
    negative=-closed.loc[closed.pnl<0,"pnl"].sum()
    maxdd=float(np.max(1-q/np.maximum.accumulate(q))*100)
    cagr=float(((max(q[-1],1e-8)/10000.)**(365.25/n)-1)*100)
    sd=float(daily_r.std())
    neg=float(np.mean(np.minimum(daily_r,0)**2))**.5
    return {
      "Total Trades":int(len(closed)),
      "Win Rate (%)":float(100*(closed.pnl>0).mean()) if len(closed) else 0.,
      "Profit Factor":float(positive/negative) if negative>1e-10 else None,
      "CAGR (%)":cagr,
      "Max Drawdown (%)":maxdd,
      "Sharpe Ratio":float(np.sqrt(365.25)*daily_r.mean()/sd) if sd>1e-12 else None,
      "Sortino Ratio":float(np.sqrt(365.25)*daily_r.mean()/neg) if neg>1e-12 else None,
      "Calmar Ratio":float(cagr/maxdd) if maxdd>1e-10 else None,
    }

def benchmark():
    OUT.mkdir(parents=True,exist_ok=True)
    legs,t,audit=load()
    allow,scale,folds=generate_decisions(t)
    index=pd.date_range(ORIGIN,periods=(STOP-ORIGIN).days,freq="D")
    rows=[];curves={}
    for name in NAMES:
        accept={str(r.root):bool(v) for r,v in zip(t.itertuples(),allow[name])}
        sizes={str(r.root):float(v) for r,v in zip(t.itertuples(),scale[name])}
        for mode in ("off","proxy"):
            daily,closed=daily_realized_replay(legs,accept,sizes,mode=mode)
            res=metrics(daily,closed)
            res["Configuration Name"]=name+(" | No F" if mode=="off" else " | F-style proxy (NOT F)")
            rows.append(res)
            curves[res["Configuration Name"]]=daily
            print("SCREEN",res,flush=True)
    order=["Configuration Name","Total Trades","Win Rate (%)","Profit Factor",
           "CAGR (%)","Max Drawdown (%)","Sharpe Ratio","Sortino Ratio","Calmar Ratio"]
    table=pd.DataFrame(rows)[order].sort_values("Calmar Ratio",ascending=False,na_position="last")
    table.to_csv(OUT/"benchmark_screen.csv",index=False)
    (OUT/"benchmark_screen.md").write_text(table.round(3).to_markdown(index=False))
    pd.DataFrame(curves,index=index).to_csv(OUT/"equity_screen.csv",index_label="date")
    (OUT/"folds.json").write_text(json.dumps(folds,indent=2))
    limitations=[
       "This is a preliminary 35-symbol cached trade-ledger screen, NOT a full executable 1m multi-asset 5-year backtest.",
       "Mojsavar profit-lock/50% partial at 2R not included in cached leg outcomes; latest real reference has 2679 trades, this ledger differs.",
       "Unobserved rejected signals cannot free slots for fresh signals, even though freed margin is reallocated to surviving signals.",
       "Native positive-R outcome substitutes for actual native TP/SL/triple barrier labels; exact barrier labels unavailable.",
       "OHLCV feature extractor supports complete requested matrix, but source cached legs cannot supply BB, wicks, Kijun, Tenkan, cloud, volume ROC to past historical events.",
       "Source ledger original fee is 0.0006/side and slippage 0.0002/side, more expensive than requested 0.0005/side. Exact repricing needs missing execution-price/funding paths.",
       "Daily equity here is REALIZED-ONLY (no open-position MTM). DD, Sharpe, Sortino, Calmar and CAGR are screening proxies, NOT account-level executable estimates.",
       "F-style proxy includes realized-equity drawdown brake and vol targeting at entry, no F AI regime, bot streak or position cuts; it is categorically NOT Claude's F.",
       "Strict F mode is blocked until exact 1-minute data for 35 symbols, F score history and current protected leg ledger are supplied.",
       "HMM/GMM states are at irregular entry-event times, not a continuously updated 4h market-regime series.",
       "Historical strategy selection looked at 2025-26 previously; AI models are expanding walk-forward but strategy OOS is not pristine."
    ]
    report={"status":"RESEARCH_ONLY_SCREEN","full_exact_f_comparison":False,
            "requested_fee_per_side":.0005,"source_fee_per_side":.0006,
            "slippage_each_side":.0002,
            "source":audit,"folds":folds,"rows":rows,"limitations":limitations}
    (OUT/"audit.json").write_text(json.dumps(report,indent=2))
    plot(index,curves)
    print("MARKDOWN SCREEN TABLE\n",table.round(2).to_markdown(index=False),flush=True)
    print("UNAVAILABLE: exact F on/off; this 14-row table has F-style proxy only",flush=True)
    return table

def plot(index,curves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(2,1,figsize=(16,12),sharex=True)
    for name,eq in curves.items():
        series=np.asarray(eq,float)
        ax[0].plot(index,series,label=name,linewidth=1)
        dd=(series/np.maximum.accumulate(np.r_[10000.,series])[1:]-1)*100
        ax[1].plot(index,dd,linewidth=.9)
    ax[0].set_yscale("log")
    ax[0].set_title("RESEARCH SCREEN ONLY: 7 AI configs x no-F/F-style proxy (NOT exact F)")
    ax[0].set_ylabel("Realized-only equity ($, log)")
    ax[0].legend(ncol=2,fontsize=7,loc="upper left")
    ax[1].set_title("Realized-only drawdown; open positions NOT marked to market")
    ax[1].set_ylabel("DD (%)");ax[1].grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(OUT/"seven_equity_drawdown_screen.png",dpi=145)
    plt.close(fig)

if __name__=="__main__":
    benchmark()
