"""Causal meta-label research on the existing 2,991-trade historical ledger.

IMPORTANT: This is an offline, fixed-original-notional trade-selection experiment,
NOT a resimulated account and NOT an AI implementation in any trading bot.
No changes to F, risk settings, entry/exit engines, or paper/live services.

Historical strategy selection considered 2025-26, hence even the 2025+ AI-only
test must not be represented as untouched system-level out-of-sample.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor, IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "high_cagr/output/ideas/three_bots/trades.csv"
OUT = ROOT / "ai_research/output"
EPOCH = pd.Timestamp("2021-10-05", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
VALID_END = pd.Timestamp("2025-01-01", tz="UTC")
CATS = ["bot", "coin", "side", "hour_bin", "weekday", "month_bin"]
NUMS = ["history_bot_n", "history_bot_r", "history_side_n", "history_side_r",
        "history_coin_n", "history_coin_r", "history_global_r"]
FIELDS = CATS + NUMS
SEED = 72021

def load_ledger(path=LEDGER):
    d = pd.read_csv(path)
    expected = ["bot", "coin", "side", "entry_min", "exit_min", "notional", "pnl"]
    if d.columns.tolist() != expected:
        raise ValueError("Unexpected ledger schema")
    if not d.bot.isin(["main", "c3", "pa"]).all() or not d.side.isin([-1, 1]).all():
        raise ValueError("Unknown bot or direction")
    if not np.isfinite(d[["entry_min","exit_min","notional","pnl"]]).all().all():
        raise ValueError("Nonfinite source ledger")
    if (d.notional <= 0).any() or (d.entry_min > d.exit_min).any():
        raise ValueError("Invalid timestamp / exposure")
    key = ["bot","coin","side","entry_min","exit_min"]
    if d.duplicated(key).any():
        raise ValueError("Duplicate trade IDs prevent exact mapping")
    d["when"] = EPOCH + pd.to_timedelta(d.entry_min, unit="m")
    d["ret"] = d.pnl / d.notional   # net realized return on original notional
    return d.sort_values(["entry_min","coin","bot","side"],kind="stable").reset_index(drop=True)

def causal_features(d):
    """Only exits strictly before entry can contribute to previous-trade aggregates.

    Rows with the same entry minute are computed before ANY such trade is observed.
    Likewise, historical training labels are never joined from the same/future entry.
    """
    x = d.copy()
    dt = x.when.dt
    x["hour_bin"] = (dt.hour // 4).astype(str)
    x["weekday"] = dt.dayofweek.astype(str)
    x["month_bin"] = ((dt.month - 1) // 3).astype(str)
    x["side"] = x.side.astype(str)
    # Optional prior outcome signal: expiring 180-day window, only positions exited
    # strictly before entry; returns are clipped for robust inputs, NOT for PnL.
    pending = x.sort_values("exit_min").reset_index()
    ptr = 0
    from collections import deque
    history = deque()
    feats = []
    for minute, ids in x.groupby("entry_min", sort=True).groups.items():
        while ptr < len(pending) and pending.loc[ptr,"exit_min"] < minute:
            row = pending.iloc[ptr]
            history.append((int(row.exit_min),str(row.bot),str(row.coin),
                            str(row.side),float(np.clip(row.ret,-.5,.5))))
            ptr += 1
        while history and history[0][0] < minute - 180*1440:
            history.popleft()
        h = list(history)
        for i in ids:
            row=x.loc[i]
            def summary(rows):
                return (len(rows), float(np.mean([z[-1] for z in rows])) if rows else 0.)
            nb,rb=summary([z for z in h if z[1]==row.bot])
            ns,rs=summary([z for z in h if z[1]==row.bot and z[3]==row.side])
            nc,rc=summary([z for z in h if z[2]==row.coin])
            _,rg=summary(h)
            feats.append((i,nb,rb,ns,rs,nc,rc,rg))
    f=pd.DataFrame(feats,columns=["index"]+NUMS).set_index("index")
    for col in NUMS:x[col]=f[col]
    return x

def split_masks(d):
    train=(d.when<TRAIN_END).to_numpy()
    valid=((d.when>=TRAIN_END)&(d.when<VALID_END)).to_numpy()
    test=(d.when>=VALID_END).to_numpy()
    if not all(int(v.sum())>0 for v in (train,valid,test)):
        raise ValueError("Empty train/validation/test split")
    return train,valid,test

def pipeline(est):
    return Pipeline([
        ("prep",ColumnTransformer([
            ("categorical",OneHotEncoder(handle_unknown="ignore"),CATS),
            ("numeric",Pipeline([("imp",SimpleImputer(strategy="median")),("std",StandardScaler())]),NUMS),
        ],sparse_threshold=0.0)),
        ("model",est),
    ])

def metrics(x, mask):
    r=x.ret.to_numpy()[mask]
    p=x.pnl.to_numpy()[mask]
    n=int(mask.sum()); w=r[r>0]; l=r[r<0]
    return dict(n=n, original_notional_pnl=float(p.sum()),
                unit_return_sum=float(r.sum()),
                mean_unit_bps=float(r.mean()*10000) if n else None,
                win_rate=float((r>0).mean()*100) if n else None,
                unit_profit_factor=float(w.sum()/-l.sum()) if len(l) and l.sum()<0 else None)

def model_scores(x, train, valid):
    models={
        "ridge":Ridge(alpha=10.),
        "extra_trees":ExtraTreesRegressor(n_estimators=140,min_samples_leaf=22,max_features=0.7,n_jobs=-1,random_state=SEED),
        "random_forest":RandomForestRegressor(n_estimators=140,max_depth=6,min_samples_leaf=24,n_jobs=-1,random_state=SEED),
        "hist_boost":HistGradientBoostingRegressor(max_iter=90,max_leaf_nodes=8,min_samples_leaf=35,l2_regularization=20.,learning_rate=0.035,random_state=SEED),
        "logistic_win":LogisticRegression(max_iter=400,C=0.15,random_state=SEED),
    }
    out={}
    for name,est in models.items():
        pipe=pipeline(est)
        target=(x.ret>0).astype(int).to_numpy() if name=="logistic_win" else np.clip(x.ret.to_numpy(),-.5,.5)
        pipe.fit(x.loc[train,FIELDS],target[train])
        score=(pipe.predict_proba(x[FIELDS])[:,1] if name=="logistic_win"
               else pipe.predict(x[FIELDS]))
        out[name]=score
    # Declared non-ML alternatives. Only TRAIN outcome data determines side quality.
    qual=x.loc[train].groupby(["bot","side"]).ret.agg(["mean","count"])
    gm=x.loc[train].groupby("bot").ret.mean()
    side=[]
    for r in x.itertuples():
        if (r.bot,r.side) in qual.index:
            q=qual.loc[(r.bot,r.side)]
            side.append((q["mean"]*q["count"]+gm[r.bot]*80)/(q["count"]+80))
        else: side.append(gm.get(r.bot,0.))
    out["empirical_side"]=np.array(side)
    # Unsupervised anomaly score trained on past context, not labels.
    pp=pipeline(IsolationForest(n_estimators=120,max_samples=min(256,int(train.sum())),contamination="auto",random_state=SEED))
    pp.fit(x.loc[train,FIELDS]);out["isolation_normality"]=pp.decision_function(x[FIELDS])
    return out

def choices(x,scores,train,valid):
    base=x.ret.to_numpy()
    summaries=[]
    for name,s in scores.items():
        for keep_frac in (0.55,0.70,0.85):
            # FIXED threshold obtained only from 2021-2023, not holdout.
            threshold=float(np.quantile(s[train],1-keep_frac))
            keep=s>=threshold
            k=int((keep&valid).sum())
            vr=float(k/max(1,int(valid.sum())))
            vsum=float(base[keep&valid].sum())
            bsum=float(base[valid].sum())
            inc=vsum-bsum
            # Valid only if it reduces total net loss from rejected trades
            # across at least two of four calendar quarters.
            q=x.when.dt.quarter.to_numpy()
            quarters=sum(float((-base[(~keep)&valid&(q==i)]).sum())>0 for i in (1,2,3,4))
            ok=(.45<=vr<=.93 and inc>0 and quarters>=2 and k>=100)
            summaries.append(dict(method=name,train_keep=keep_frac,threshold=threshold,
                                  val_retained=vr,val_unit_delta=inc,val_quarters_positive=quarters,
                                  validation_eligible=bool(ok),keep=keep))
    viable=[r for r in summaries if r["validation_eligible"]]
    # Single frozen selection. No model threshold may be reselected after OOS.
    win=max(viable,key=lambda r:(r["val_unit_delta"],r["val_quarters_positive"],r["val_retained"])) if viable else None
    return win,summaries

def month_bootstrap(x,keep,test,rep=1500):
    d=x.loc[test].copy()
    d["keep"]=keep[test]
    d["month"]=d.when.dt.strftime("%Y-%m")
    deltas=np.array([float((-r.loc[~r.keep,"ret"]).sum()) for _,r in d.groupby("month")])
    rng=np.random.default_rng(SEED)
    samples=deltas[rng.integers(0,len(deltas),(rep,len(deltas)))].sum(axis=1)
    return dict(months=int(len(deltas)),delta_sum=float(deltas.sum()),
                bootstrap_ci95=[float(v) for v in np.quantile(samples,[.025,.975])],
                bootstrap_probability_benefit=float((samples>0).mean()),
                beneficial_months=int((deltas>0).sum()))

def audit(x):
    train,valid,test=split_masks(x)
    baselines={period:metrics(x,mask) for period,mask in [("train",train),("validation",valid),("test",test)]}
    scores=model_scores(x,train,valid)
    winner,summaries=choices(x,scores,train,valid)
    rank=sorted([{k:v for k,v in q.items() if k!="keep"} for q in summaries],
                key=lambda z:z["val_unit_delta"],reverse=True)
    out=dict(method="fixed-notional, selected trade opportunity replay only, NOT re-sized shared-equity replay",
             ledger="high_cagr/output/ideas/three_bots/trades.csv",
             bot_count=x.bot.value_counts().to_dict(),total_trades=len(x),
             period={"train":"2021-10-05 .. 2023-12-31",
                     "validation":"2024-01-01 .. 2024-12-31",
                     "ai_test":"2025-01-01 .. 2026-10-04"},
             baselines=baselines,candidates_validation=rank,selected=None,
             limitations=["Counterfactual account MTM, capacity, margin, newly freed slots and compounding not replayed.",
                          "Strategies/universe previously researched using 2025-26; system-level test is not untouched OOS.",
                          "F risk pilot untouched; no deployment; not live LBank performance."])
    if winner:
        k=winner["keep"]
        out["selected"]={key:winner[key] for key in ("method","train_keep","threshold","val_retained","val_unit_delta")}
        out["selected"]["test"]=metrics(x,k&test)
        out["selected"]["validation"]=metrics(x,k&valid)
        out["selected"]["test_delta_unit_return_sum"]=float((-x.ret.to_numpy()[(~k)&test]).sum())
        out["selected"]["test_effect_month_bootstrap"]=month_bootstrap(x,k,test)
        out["selected"]["test_retained_by_bot"]={b:int(((x.bot==b).to_numpy()&k&test).sum()) for b in ("main","c3","pa")}
        out["selected"]["oos_positive_vs_baseline"]=bool(out["selected"]["test_delta_unit_return_sum"]>0)
        pd.DataFrame({"bot":x.bot,"coin":x.coin,"side":x.side,"entry_min":x.entry_min,"exit_min":x.exit_min,
                      "period":np.where(train,"train",np.where(valid,"validation","ai_test")),
                      "selected":k,"score":scores[winner["method"]]}).to_csv(OUT/"all_2991_decisions.csv",index=False)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv",type=Path,default=LEDGER)
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    x=causal_features(load_ledger(args.csv))
    res=audit(x)
    (OUT/"result.json").write_text(json.dumps(res,indent=2,ensure_ascii=False))
    print("TRADE COUNTS",res["total_trades"],res["bot_count"])
    print("BASELINE",res["baselines"])
    print("SELECTED",res["selected"])
    print("NOTE: unit-return not a portfolio CAGR or drawdown")
if __name__=="__main__":main()
