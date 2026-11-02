"""Bayesian hierarchical per-bot/side/coin opportunity sizing; fixed training years.

Works with source cached 35-symbol trade ledger and DOES NOT use F,
minute-level replay, latest Mojsavar locked exit labels, or shadow risk.
This is a low-cost model discovery screen, not a deployment claim.

Only 2021-2023 fully EXITED positions are training labels. Select 2024.
Run 2025-26 once only on the selected candidate. No hindsight diagnostics
are used as predictors.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from .oem_ledger_screen import load,OUT,START,TEST,DAYS,SEED
RISK_LIMIT=(.6,1.4)
PARAMS={
    "side_shrink20":dict(group=["bot","side"],prior=20,gain=.55),
    "side_shrink60":dict(group=["bot","side"],prior=60,gain=.55),
    "coin_shrink40":dict(group=["bot","coin"],prior=40,gain=.45),
    "coin_shrink100":dict(group=["bot","coin"],prior=100,gain=.45),
    "coin_side_shrink100":dict(group=["bot","coin","side"],prior=100,gain=.5),
    "regime_atr_shrink60":dict(group=["bot","side","atr_state"],prior=60,gain=.5)
}

def fit(x,config):
    train=x[x.exit_day<START].copy()
    assert train.entry_day.lt(START).all()
    train["R_target"]=train["R"].clip(-3,8)
    train["atr_state"]=np.where(train.f_atr_rank<=.5,"LOW","HIGH")
    bs=train.groupby("bot").R_target.agg(["mean","count"])
    sub=train.groupby(config["group"]).R_target.agg(["mean","count"])
    return {"bot_mean":bs["mean"].to_dict(),"sub":sub}

def apply(x,config,mdl):
    d=x.copy()
    d["atr_state"]=np.where(d.f_atr_rank<=.5,"LOW","HIGH")
    p=np.zeros(len(d))
    b=d.bot.to_numpy()
    n=d.side.to_numpy()
    for i,r in enumerate(d.itertuples()):
        bg=mdl["bot_mean"][r.bot]
        k=tuple(getattr(r,z) for z in config["group"])
        if len(k)==1:k=k[0]
        if k in mdl["sub"].index:
            z=mdl["sub"].loc[k];mu=(z["count"]*z["mean"]+config["prior"]*bg)/(z["count"]+config["prior"])
        else:mu=bg
        p[i]=mu-bg
    # Posterior signal only; w is always positive and bounded.
    un=np.clip(1+config["gain"]*np.tanh(p/.75),*RISK_LIMIT)
    # normalize by PRIOR train bot-specific trade frequencies: constant across evaluation.
    tr=d.exit_day<START
    out=un.copy()
    for bot in ("main","c3","pa"):
        m=(b==bot)
        v=float(un[m & tr].mean())
        out[m]=un[m]/max(1e-9,v)
    return np.clip(out,.55,1.45)

def measure(x,mult,start,end):
    mask=(x.entry_day>=start)&(x.entry_day<end)
    r=x.loc[mask,"R"].to_numpy(float)
    w=mult[mask.to_numpy()]
    p=r*w
    cum=np.r_[0,np.cumsum(p)]
    return {"n":int(mask.sum()),"original_total_R":float(r.sum()),"weighted_total_R":float(p.sum()),
            "delta_R":float((p-r).sum()),"mean_multiplier":float(w.mean()),
            "r_closed_only_dd":float((cum-np.maximum.accumulate(cum)).min()),
            "r_std":float(np.std(p))}

def report():
    OUT.mkdir(parents=True,exist_ok=True)
    x,removed=load()
    base_train=np.ones(len(x))
    v0=measure(x,base_train,START,TEST)
    frozen={}
    winners=[]
    for name,cfg in PARAMS.items():
        mdl=fit(x,cfg);mult=apply(x,cfg,mdl)
        val=measure(x,mult,START,TEST)
        pass_=val["delta_R"]>0 and val["mean_multiplier"]<=1.05 and val["r_std"]<=1.10*v0["r_std"]
        frozen[name]={"validation":val,"eligible":bool(pass_)}
        print("VALIDATION",name,"deltaR",round(val["delta_R"],2),"Rstd",round(val["r_std"],3),"eligible",pass_,flush=True)
        if pass_:winners.append((val["delta_R"],name))
    winner=max(winners)[1] if winners else None
    out={"source":"35-symbol winrate cached legs, Shahin late gate applied, old C3 exits remain",
         "newest_Mojsavar_profit_lock_included":False,"F_included":False,
         "source_rows":len(x),"main_late_roots_removed":removed,
         "candidate_count":len(PARAMS),"candidates":frozen,"selected":winner,
         "validation_baseline":v0,
         "test_baseline":measure(x,np.ones(len(x)),TEST,DAYS),
         "test_selected":None,"proven_better_than_F":False,
         "limitation":"R-weighted screening only: no shared account, no dynamic F, no 1m mark-to-market, no current C3 partial fills."}
    if winner:
        w=apply(x,PARAMS[winner],fit(x,PARAMS[winner]))
        out["test_selected"]=measure(x,w,TEST,DAYS)
    (OUT/"bayesian_side_screen.json").write_text(json.dumps(out,indent=2))
    print("LOCKED RESULT",json.dumps({k:out[k] for k in ("selected","test_baseline","test_selected","proven_better_than_F")}),flush=True)
    return out
if __name__=="__main__":report()
