"""Actual trade-ledger screen of causal OEM; not a shared-account/F replay.

Consumes cached 5-year winrate/legs.pkl with all 35 bots' coin symbols and
current Ghoghnous soft strategy. Shahin late-entry is applied from signal time.
Mojsavar protected EXITS are NOT present in the cached ledger and CANNOT be
reconstructed without minute paths; therefore the result is only a screen.

2024 model selection and 2025+ locked evaluation. All costs are already in
source R. The numerical outcome is summed R with reweighted risk, not CAGR/DD.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from .bandit_on_f import weights,CANDIDATES,BOTS,START,TEST,DAYS
from .bandit_on_f import OUT

ROOT=OUT.parents[1]
LEDGER=ROOT/"high_cagr/output/ideas/winrate/legs.pkl"
SEED=72021

def load():
    df=pd.read_pickle(LEDGER)
    cols={"em","xm","bot","coin","R","f_ret60","root","is_add","entry","stop_frac","unit"}
    assert cols.issubset(df.columns),sorted(cols-set(df.columns))
    x=df.copy()
    x=x[x.em>=0].copy()
    # Exact formula of published Shahin gate, but net exit labels from
    # cached shipped engine; not recalculated after C3 partial fills.
    rejected=set(x.loc[(x.bot=="main")&(~x.is_add)&(x.f_ret60>0.1521),"root"])
    x=x[~x.root.isin(rejected)].copy()
    # Preserve only closed trades within test period for actual return labels.
    assert (x.xm>=x.em).all()
    assert x.bot.isin(BOTS).all()
    x["exit_day"]=(x.xm//1440).astype(int)
    x["entry_day"]=(x.em//1440).astype(int)
    return x.sort_values(["em","xm"],kind="stable").reset_index(drop=True),len(rejected)

def r_curve(x,vals):
    order=np.argsort(x.xm.to_numpy(),kind="stable")
    v=np.array(vals)[order]
    return np.cumsum(v)

def measure(x,risk_weights,start,end):
    m=(x.entry_day>=start)&(x.entry_day<end)
    v=x.loc[m,"R"].to_numpy(float)
    mul=np.array([risk_weights[b][d] for b,d in zip(x.loc[m,"bot"],x.loc[m,"entry_day"])])
    f=v*mul
    # surrogate max adverse cumulative closed-trade R, NOT account DD %
    c=np.r_[0.,np.cumsum(f)]
    draw=(c-np.maximum.accumulate(c)).min()
    y=x.loc[m].copy()
    y["gain"]=f-v
    y["exit_month"]=(pd.Timestamp("2021-10-05")+pd.to_timedelta(y.exit_day,unit="D")).dt.strftime("%Y-%m")
    monthly=y.groupby("exit_month").gain.sum().to_numpy()
    return {
        "n":int(m.sum()),
        "baseline_total_R":float(v.sum()),
        "weighted_total_R":float(f.sum()),
        "delta_R":float((f-v).sum()),
        "mean_risk_multiplier":float(mul.mean()) if len(mul) else None,
        "r_weighted_win":float((f>0).mean()*100) if len(f) else None,
        "closed_trade_surrogate_max_dd_R":float(draw),
        "month_wins":int((monthly>0).sum()),
        "months":int(len(monthly)),
        "monthly_delta_R":monthly.tolist(),
    }

def report():
    OUT.mkdir(parents=True,exist_ok=True)
    x,removed=load()
    L=[dict(bot=r.bot,xm=int(r.xm),em=int(r.em),entry=float(r.entry),
            stop_frac=float(r.stop_frac),unit=float(r.unit)) for r in x.itertuples()]
    neutral={b:np.ones(DAYS) for b in BOTS}
    v0=measure(x,neutral,START,TEST)
    choices={}
    good=[]
    for name,kw in CANDIDATES.items():
        policy=weights(L,kw)
        v=measure(x,policy,START,TEST)
        # Cannot select by TEST. Hard 2024 screen gate.
        eligible=v["delta_R"]>0.0 and v["weighted_total_R"]>v0["weighted_total_R"] and v["mean_risk_multiplier"]<=1.05
        choices[name]={"validation":{k:q for k,q in v.items() if k!="monthly_delta_R"},
                       "selected_by_2024":bool(eligible)}
        if eligible:good.append((name,v["delta_R"]))
    chosen=max(good,key=lambda z:z[1])[0] if good else None
    testbase=measure(x,neutral,TEST,DAYS)
    out={"method":"causal online expert allocation, risk-weighted trade R screening",
         "ledger":"high_cagr/output/ideas/winrate/legs.pkl",
         "has_latest_c3_protected_exits":False,
         "has_F_replay":False,
         "full_latest_2679_trade_account_comparison":False,
         "modified_shahin_late_entries":removed,
         "screened_trade_rows":len(x),
         "train":["2021-10-05","2023-12-31"],
         "selection":["2024-01-01","2024-12-31"],
         "test":["2025-01-01","2026-10-04"],
         "validation_baseline":{k:v for k,v in v0.items() if k!="monthly_delta_R"},
         "candidates":choices,"selected":chosen,
         "test_baseline":{k:v for k,v in testbase.items() if k!="monthly_delta_R"},
         "test_selected":None,
         "claim_superior_to_F":False,
         "limits":[
           "Latest Mojsavar +1R lock and half at +2R absent from cached trade labels.",
           "F risk manager and its open cuts not replayed; cannot claim beat F.",
           "Summed per-trade R is a preliminary screen only; portfolio compounding, real margin constraints and mark-to-market not modeled.",
           "Source R already contains trading costs/funding from the source research engine.",
           "The historical strategy and 35-coin universe were researched using the overall time window; only this new allocator is time-split."
         ]}
    if chosen is not None:
        w=weights(L,CANDIDATES[chosen]);t=measure(x,w,TEST,DAYS)
        out["test_selected"]={k:v for k,v in t.items() if k!="monthly_delta_R"}
        vals=np.asarray(t["monthly_delta_R"]);rng=np.random.default_rng(SEED)
        boot=vals[rng.integers(0,len(vals),size=(2500,len(vals)))].sum(axis=1)
        out["test_selected"]["bootstrap_95_delta_R"]=[float(a) for a in np.quantile(boot,[.025,.975])]
        out["test_selected"]["probability_benefit"]=float((boot>0).mean())
        out["test_selected"]["positive_screen"]=bool(t["delta_R"]>0 and (boot>0).mean()>=0.95)
    (OUT/"oem_ledger_screen.json").write_text(json.dumps(out,indent=2))
    print("SCREEN",json.dumps({k:out[k] for k in ("screened_trade_rows","modified_shahin_late_entries","selected","validation_baseline","test_baseline","test_selected","claim_superior_to_F")},indent=2),flush=True)
    return out
if __name__=="__main__":report()
