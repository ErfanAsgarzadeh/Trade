"""CDRA: Conformal Distributional Risk Allocation, daily screening experiment.

SOURCE: frozen protected-rule THREE-BOT daily equity (winrate/daily_final.npy),
from 2021-10-05 to 2026-10-04; daily BTC features from verified one-minute
Binance monthly archives restored by restore_data.py.

Conventional F results CANNOT be exactly reproduced because 35-symbol
one-minute paths / counterfactual fills and F's open cuts are not present.
The explicit comparator is a F-STYLE DAILY PROXY: volatility target (1% daily
over 20 days) and account drawdown brake (8%-14%, floor 0.2) at a base scale
of 1.41. It is NOT Claude's actual F (which also models market AI, bot streak,
margin caps, order gating, and cutting of open positions).
Do NOT deploy outputs as an LBank risk control.

Causality: all features used for day d rely on data through day d-1.
The label is the worst compounded return over the NEXT 20 calendar days.
Training labels end before validation/calibration; validation 2024 only
selects risk map, locked test 2025-26 is evaluated once if eligible.
"""
from __future__ import annotations
import json
import math
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from .btc_market import load_btc_4h

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"ai_research"/"output"
SEED=721112
START=pd.Timestamp("2021-10-05",tz="UTC")
CAL_START=pd.Timestamp("2023-08-01",tz="UTC")
VAL_START=pd.Timestamp("2024-01-01",tz="UTC")
TEST_START=pd.Timestamp("2025-01-01",tz="UTC")
TRAIN_END=pd.Timestamp("2023-06-30",tz="UTC")
CAL_END=pd.Timestamp("2023-12-11",tz="UTC")
H=20
# The sole candidate family, declared before examining validation/test.
CANDIDATES={
  "cdra_soft":dict(gain=.32,lo=.75,hi=1.15),
  "cdra_medium":dict(gain=.65,lo=.60,hi=1.20),
  "cdra_strict":dict(gain=1.00,lo=.45,hi=1.20),
}
FEATURES=[
 "ref_r3","ref_r7","ref_r20","ref_vol10","ref_vol20","ref_vol60",
 "ref_dd","btc_r3","btc_r7","btc_r21","btc_r60",
 "btc_v20","btc_v60","btc_ma50","btc_ma200",
]

def data():
    path=ROOT/"high_cagr/output/ideas/winrate/daily_final.npy"
    daily=np.load(path)
    if daily.ndim!=1 or not (1800<=len(daily)<=1850):
        raise ValueError("Incorrect protected-rule daily equity length")
    if not np.isfinite(daily).all() or (daily<=0).any():
        raise ValueError("Invalid protected daily equity")
    ix=pd.date_range(START,periods=len(daily),freq="D")
    rets=np.diff(np.r_[10000.,daily])/np.r_[10000.,daily[:-1]]
    if np.any(1+rets<=0):raise ValueError("Inconsistent daily account equity")
    btc=load_btc_4h().close.resample("1D").last().reindex(ix)
    if btc.isna().any():raise ValueError(f"Missing historical BTC daily data: {btc.isna().sum()}")
    return ix,rets,btc

def features(index,returns,btc):
    equity=pd.Series(np.cumprod(1+returns),index=index)
    r=pd.Series(returns,index=index)
    br=btc.pct_change()
    d=pd.DataFrame(index=index)
    for n in (3,7,20):
        d[f"ref_r{n}"]=(equity/equity.shift(n)-1).shift(1)
    for n in (10,20,60):
        d[f"ref_vol{n}"]=r.rolling(n,min_periods=n).std().shift(1)
    d["ref_dd"]=(equity/equity.cummax()-1).shift(1)
    for n in (3,7,21,60):
        d[f"btc_r{n}"]=btc.pct_change(n).shift(1)
    for n in (20,60):
        d[f"btc_v{n}"]=br.rolling(n,min_periods=n).std().shift(1)
    for n in (50,200):
        d[f"btc_ma{n}"]=(btc/btc.rolling(n,min_periods=n).mean()-1).shift(1)
    assert d.columns.tolist()==FEATURES
    return d.replace([np.inf,-np.inf],np.nan)

def future_tail(returns,h=H):
    """Target worst account path after signal, 20-day interval all included."""
    y=np.full(len(returns),np.nan)
    for d in range(len(returns)-h+1):
        y[d]=min(0.,float(np.cumprod(1+returns[d:d+h]).min()-1))
    return y

def sim_proxy(r,mult):
    """F-style vol target + DD brake acting on DAILY returns only.

    Applies risk at day open using only previous daily equity/vol.
    This is intentionally NOT the original F engine.
    """
    n=len(r);q=np.ones(n+1,float);k=np.ones(n,float);high=1.
    for t in range(n):
        eq=q[t];dd=max(0.,1-eq/max(high,eq))
        brake=1. if dd<=.08 else max(.2,1-.8*(dd-.08)/.06)
        if t>=21:
            realized=np.std(q[t-20:t+1][1:]/q[t-20:t+1][:-1]-1)
            vt=float(np.clip(.01/realized,.3,1.5)) if realized>1e-10 else 1.
        else:vt=1.
        k[t]=min(3.,max(0.,1.41*brake*vt*mult[t]))
        rr=r[t]*k[t]
        if 1+rr<=0:rr=-.99 # no bankruptcy artifact beyond -99% per day
        q[t+1]=max(1e-9,eq*(1+rr))
        high=max(high,q[t+1])
    return q[1:],k

def score_metrics(equity,index,start,end=None):
    mask=(index>=start)&((index<end) if end is not None else True)
    d=equity[mask]
    idx=index[mask]
    before=np.flatnonzero(mask)[0]
    initial=equity[before-1] if before else 1.
    vals=d/initial
    curves=np.r_[1.,vals]
    y=(idx[-1]-idx[0]).days/365.25
    years=(len(vals)/365.25)
    cagr=100*(max(vals[-1],1e-9)**(1/years)-1)
    dd=100*(1-curves/np.maximum.accumulate(curves)).max()
    rates=np.diff(curves)/curves[:-1]
    calmar=float(cagr/dd) if dd>1e-8 else None
    return dict(cagr=float(cagr),max_dd=float(dd),calmar=calmar,
                end_multiple=float(vals[-1]),mean_daily_r=float(rates.mean()),
                neg_daily_pct=float(100*(rates<0).mean()))

def fit_tail(x,y,index):
    # Strict 20d label embargo before calibration and validation.
    train=(index<=TRAIN_END)&(index>=START+pd.Timedelta(days=210))&np.isfinite(y)
    cal=(index>=CAL_START)&(index<=CAL_END)&np.isfinite(y)
    assert train.sum()>350 and cal.sum()>100
    assert index[np.flatnonzero(train)[-1]]+pd.Timedelta(days=H)<index[np.flatnonzero(cal)[0]]
    assert index[np.flatnonzero(cal)[-1]]+pd.Timedelta(days=H)<VAL_START
    imp=SimpleImputer(strategy="median")
    a=imp.fit_transform(x.loc[train])
    X=imp.transform(x)
    mdl=HistGradientBoostingRegressor(loss="quantile",quantile=.1,
         max_iter=120,learning_rate=.045,max_leaf_nodes=7,
         min_samples_leaf=32,l2_regularization=15.,random_state=SEED)
    mdl.fit(a,y[train])
    pred=mdl.predict(X)
    resid=y[cal]-pred[cal]
    # Lower one-sided split conformal residual, calibrated on 2023 ONLY.
    correction=float(np.quantile(resid,.1,method="lower"))
    bound=np.minimum(0.,pred+correction)
    observed=float((y[cal]>=bound[cal]).mean())
    return bound,dict(training_rows=int(train.sum()),cal_rows=int(cal.sum()),
                      one_sided_correction=correction,
                      cal_coverage=float(observed),
                      cal_predicted_tail=float(np.mean(bound[cal])))

def risk_gates(bound,index):
    # Calibrate policy risk thresholds on 2023 historical scores; no 2024/2025 tuning.
    cal=(index>=CAL_START)&(index<=CAL_END)
    loss=-bound
    med=float(np.median(loss[cal]))
    iqr=float(np.quantile(loss[cal],.75)-np.quantile(loss[cal],.25))
    scale=max(.01,iqr)
    out={}
    for name,p in CANDIDATES.items():
        g=np.exp(-p["gain"]*(loss-med)/scale)
        g=np.clip(g,p["lo"],p["hi"])
        # Research toggled on at the first validation day, no retroactive signal.
        g[index<VAL_START]=1.
        out[name]=g
    return out,dict(score_med=med,score_iqr=iqr)

def boot_ci(reference,new,index,start=TEST_START):
    m=index>=start
    rd=np.diff(np.r_[1.,reference])/np.r_[1.,reference[:-1]]
    nd=np.diff(np.r_[1.,new])/np.r_[1.,new[:-1]]
    dif=np.log1p(nd[m])-np.log1p(rd[m])
    years=index[m].strftime("%Y-%m")
    ms=pd.Series(dif).groupby(years).sum().to_numpy()
    rng=np.random.default_rng(SEED)
    bs=ms[rng.integers(0,len(ms),size=(2500,len(ms)))].sum(axis=1)
    return {"months":len(ms),"mean_test_log_return_difference":float(dif.sum()),
            "boot95_log_return_difference":[float(a) for a in np.quantile(bs,[.025,.975])],
            "probability_positive":float((bs>0).mean())}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    index,ret,btc=data()
    x=features(index,ret,btc)
    y=future_tail(ret)
    bound,cal=fit_tail(x,y,index)
    candidates,risk_cal=risk_gates(bound,index)
    f_eq,f_k=sim_proxy(ret,np.ones(len(ret)))
    validation_ref=score_metrics(f_eq,index,VAL_START,TEST_START)
    val={}
    eligible=[]
    for name,g in candidates.items():
        eq,k=sim_proxy(ret,g)
        v=score_metrics(eq,index,VAL_START,TEST_START)
        ok=(v["cagr"]>validation_ref["cagr"] and
            v["max_dd"]<=validation_ref["max_dd"]+.5 and
            v["calmar"] is not None and validation_ref["calmar"] is not None and
            v["calmar"]>=validation_ref["calmar"]+.05)
        val[name]={"metrics":v,"eligible":bool(ok),
                   "avg_g":float(g[(index>=VAL_START)&(index<TEST_START)].mean())}
        print("VALID",name,v,"eligible",ok,flush=True)
        if ok:eligible.append((v["calmar"],name))
    winner=max(eligible)[1] if eligible else None
    test_ref=score_metrics(f_eq,index,TEST_START)
    out={"study":"CDRA quantile+conformal conditional 20-day max adverse return",
         "comparator":"F-STYLE DAILY PROXY, not original Claude F; no market AI, bot losing-streak, margin or open position cuts",
         "source":"winrate/daily_final.npy, verified BTCUSDT 1-minute zip closes",
         "date":{"start":str(index[0].date()),"end":str(index[-1].date()),
                 "train_until":str(TRAIN_END.date()),"cal_until":str(CAL_END.date()),
                 "validation":"2024","holdout":"2025-01 to 2026-10-04"},
         "calibration":cal|risk_cal,"settings":CANDIDATES,
         "validation_baseline":validation_ref,
         "validation_candidates":val,
         "selected":winner,
         "test_baseline":test_ref,
         "test_selected":None,
         "beats_original_F":False,"beats_daily_proxy":False,
         "limitations":[
             "Daily account-return overlay does not implement same-coin entries, fees on F open cuts, F regime score, bot streak and 80% shared margin.",
             "F-style baseline is NOT original F. Do not compare its CAGR or DD to published real F backtest numbers.",
             "Protected rule base data were already selected with knowledge of part of the holdout; not an untouched whole-strategy OOS.",
             "Quantile coverage under overlapping 20-day labels is not finite-sample iid validity; cluster coverage separately assessed.",
             "Model learns from off-policy shadow reference returns, requiring a live shadow recorder to preserve training definition.",
             "Risk budget and no-change PAPER/LIVE safety guaranteed; no deployment."],
         }
    if winner:
        eq,k=sim_proxy(ret,candidates[winner])
        met=score_metrics(eq,index,TEST_START)
        out["test_selected"]=met
        out["beats_daily_proxy"]=bool(met["cagr"]>test_ref["cagr"] and
                     met["max_dd"]<=test_ref["max_dd"]+.5 and
                     met["calmar"] is not None and test_ref["calmar"] is not None and
                     met["calmar"]>test_ref["calmar"])
        out["test_bootstrap"]=boot_ci(f_eq,eq,index)
        out["oos_conformal_coverage"]=float(np.mean(y[(index>=TEST_START)&np.isfinite(y)]>=bound[(index>=TEST_START)&np.isfinite(y)]))
        out["selected_avg_risk_multiplier"]=float(candidates[winner][index>=TEST_START].mean())
        pd.DataFrame({"day":index.astype(str),"reference_daily_return":ret,
                      "conformal_p10_lower_20day":bound,
                      "cdra_multiplier":candidates[winner],
                      "f_proxy_equity":f_eq,"cdra_proxy_equity":eq}).to_csv(OUT/"cdra_daily_decisions.csv",index=False)
        print("TEST daily proxy F",test_ref,"CDRA",met,"beats",out["beats_daily_proxy"],flush=True)
    else:
        print("No CDRA candidates cleared 2024; test F proxy reference only",test_ref,flush=True)
    path=OUT/"cdra_daily_result.json";path.write_text(json.dumps(out,indent=2,ensure_ascii=False))
    print("CDRA_RESULT",json.dumps({k:out[k] for k in ("selected","test_baseline","test_selected","beats_daily_proxy","beats_original_F")}),flush=True)
if __name__=="__main__":
    main()
