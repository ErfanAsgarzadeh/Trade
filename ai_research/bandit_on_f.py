"""Causal ONLINE EXPERT MIXTURE (OEM) versus Claude's F on latest three bots.

No future outcomes enter scoring, no trade/paper service imports or changes.
F controls, causal walk-forward F predictor and all existing protected exit
logic are preserved. OEM reallocates RISK BETWEEN the three F-enabled bots
from their prior completed trade outcomes. We compare a *small frozen family*
on calendar 2024, lock one, and judge 2025-26 only once.

WARNING: Off-policy bot returns are from reference ledgers. Even when a trade
would be skipped by F, the offline reference stream records its outcome.
A live implementation needs a shadow-reference log; never feed the actual F
cut/partial position R into a differently defined training label.
"""
import json
import math
import numpy as np
from pathlib import Path
from collections import deque
from datetime import date

OUT=Path(__file__).resolve().parent/"output"
BOTS=("main","c3","pa")
START=(date(2024,1,1)-date(2021,10,5)).days
TEST=(date(2025,1,1)-date(2021,10,5)).days
DAYS=(date(2026,10,5)-date(2021,10,5)).days
DEVS={"2024":(START,TEST),"2025_26":(TEST,DAYS)}
# Parameter candidates frozen BEFORE evaluating the 2025+ data.
# clip: avoid unbounded reinforcement and preserve diversification.
CANDIDATES={
  "oem_30":dict(days=30, prior=12.,gain=.40,limit=.40),
  "oem_90":dict(days=90, prior=24.,gain=.55,limit=.45),
  "oem_180":dict(days=180, prior=40.,gain=.55,limit=.40),
  "oem_90_low":dict(days=90, prior=30.,gain=.30,limit=.25),
}
PENALTY=.001

def reward(leg):
    # Normalized per unit of entry risk incl cost buffer: independent of
    # changing notional, F sizing, or overall account equity.
    denom=leg["entry"]*(leg["stop_frac"]+0.0016)
    return float(np.clip(leg["unit"]/denom,-3,8))

def weights(legs,candidate,days=DAYS):
    """Day d is computed only with trades exited on a day <d.

    Handle exit cohorts at the same timestamp together; any subsequent
    modifications to later prices/outcomes cannot alter previous weights.
    EW shrinkage to a neutral prior; output risk multipliers capped and
    normalized to mean 1, preventing a disguised increase in total risk.
    """
    params=candidate
    events=sorted((l["xm"],l["bot"],reward(l)) for l in legs)
    k=0
    history={b:deque() for b in BOTS}
    arr={b:np.ones(days,dtype=float) for b in BOTS}
    for d in range(days):
        cut=d*1440
        while k<len(events) and events[k][0]<cut:
            t,b,r=events[k]
            history[b].append((t,r))
            k+=1
        signals={}
        for b in BOTS:
            h=history[b]
            while h and h[0][0] < cut-params["days"]*1440:
                h.popleft()
            x=np.array([r for _,r in h],float)
            if len(x)<5:
                signals[b]=0.
            else:
                # Predictive quality is shrunk when little recent evidence.
                eff=len(x)/(len(x)+params["prior"])
                mean=np.clip(x.mean(),-2.,3.)
                se=np.sqrt((x.var()+2.)/(len(x)+params["prior"]))
                signals[b]=float(eff*np.tanh(mean/max(.25,se*1.5)))
        # Relative allocation among bots rather than multiplying global risk.
        mean_s=sum(signals.values())/len(signals)
        raw={b:np.clip(math.exp(params["gain"]*(signals[b]-mean_s)),1-params["limit"],1+params["limit"]) for b in BOTS}
        avg=sum(raw.values())/len(raw)
        for b in BOTS:arr[b][d]=raw[b]/avg
    return arr

def measure(legs,controls,start,end):
    from high_cagr.ideas.frisk import dd_engine as E
    rr=E.period(legs,np.ones(len(legs)),start*1440,end*1440 if end is not None else None,controls)
    daily=rr.pop("daily")
    return rr,daily

def report():
    OUT.mkdir(parents=True,exist_ok=True)
    required = [OUT.parents[1]/"high_cagr/prepared_stage2/ATOMUSDT/prices.npy",
                OUT.parents[1]/"high_cagr/prepared/BTCUSDT/prices.npy"]
    missing=[str(x) for x in required if not x.exists()]
    if missing:
        result={"status":"BLOCKED: full price arrays for 35 historical symbols missing",
                "missing":missing,"research_only":True,
                "note":"Cannot verify OEM > F on latest protected 2679 trades using only archived ledgers. Do not substitute prior 2991-trade results."}
        (OUT/"oem_vs_F.json").write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
        return result
    from high_cagr.ideas.frisk import evaluate as F
    from high_cagr.ideas.frisk import dd_engine as E
    print("Latest protected ledger: reconstruct C3 lock + Shahin gate",flush=True)
    legs=F.new_legs()
    by_bot={b:sum(l["bot"]==b for l in legs) for b in BOTS}
    print("Protected leg counts",len(legs),by_bot,flush=True)
    assert len(legs)>2500 and all(by_bot.values())
    print("Causal F regime walk-forward: score uses no post-evaluation-year training for 2024+",flush=True)
    X,y=F.features(legs)
    p,diag=F.wf_score(X,y)
    g=F.gmap(p)
    base=dict(F.CTRL,g=g)
    result=dict(
       method="ONLINE EXPERT MIXTURE / risk reallocation on top of F",
       baseline="latest PR17 protected 3-bot legs, F AI walk-forward",
       source="high_cagr/ideas/frisk/evaluate.py",
       source_branch="claude/keen-noether-mbvppe",
       source_sha="623d3b1a4c57ce515444613471d2d87560db5cf1",
       config={"F":dict(F.CTRL,g="causal annual F regime score"),
               "candidate_family":CANDIDATES},
       setup={"selection":"2024 only","test":"2025-01-01 through 2026-10-04",
              "no_new_orders":True,
              "fixed_risk_scale":1.41,
              "margin_cap":0.80},
       F_walk_forward_training_diagnostics=diag,
       validation={},selected=None,test={},limitations=[
       "F's 2022 score is hindsight-trained, but selection/test start 2024.",
       "Published F model contains in-sample leakage; we compare with its causal annual walk-forward version.",
       "Replay uses frozen protected strategy leg timelines, not real LBank fills or live margin/precision.",
       "Global F previously tuned on 2022-24, and trading universes saw 2025-26; this is AI layer OOS, not untouched strategy OOS.",
       "OEM uses outcomes of reference/shadow bots (off-policy) even where F suppresses a trade; live deployment would require independent shadow ledgers.",
       "Validation uses 2024; no retuning after seeing 2025+ allowed.",
       "Metrics and F backtest do not independently verify the server's current F enabled status.",
    ])
    r0,base_val=measure(legs,base,START,TEST)
    result["validation"]["F"]={k:v for k,v in r0.items() if k!="years"}|{"years":r0["years"]}
    print("2024 F",r0["cagr"],r0["dd"],r0["calmar"],flush=True)
    eligible=[]
    for name,kw in CANDIDATES.items():
        gb=weights(legs,kw)
        rr,_=measure(legs,dict(base,gb=gb),START,TEST)
        # Bound max drawdown, insist on 2024 calmar uplift and positive CAGR.
        ok=(rr["dd"]>=r0["dd"]-1.0 and rr["calmar"]>=r0["calmar"]+.05 and rr["cagr"]>0)
        result["validation"][name]={**{k:v for k,v in rr.items() if k!="years"},
                                    "years":rr["years"],"passes_gate":bool(ok)}
        print("2024",name,"CAGR",round(rr["cagr"],2),"DD",round(rr["dd"],2),
             "Calmar",round(rr["calmar"],3),"gate",ok,flush=True)
        if ok: eligible.append((name,rr["calmar"]-r0["calmar"]))
    if eligible:
        winner=max(eligible,key=lambda z:z[1])[0]
    else:
        winner=None
    result["selected"]=winner
    # The first real test period request now uses selected F+OEM candidate only.
    # F is evaluated as an unchanged reference for direct risk-adjusted comparison.
    ref,ref_daily=measure(legs,base,TEST,None)
    result["test"]["F"]={k:v for k,v in ref.items() if k!="years"}|{"years":ref["years"]}
    np.save(OUT/"f_test_daily.npy",ref_daily)
    if winner:
        mod=dict(base,gb=weights(legs,CANDIDATES[winner]))
        new,new_daily=measure(legs,mod,TEST,None)
        result["test"][winner]={k:v for k,v in new.items() if k!="years"}|{"years":new["years"]}
        np.save(OUT/"oem_test_daily.npy",new_daily)
        better=(new["dd"]>=ref["dd"]-1.0 and new["calmar"]>ref["calmar"] and new["cagr"]>ref["cagr"])
        result["beat_F_on_locked_test"]=bool(better)
        print("TEST F",round(ref["cagr"],2),round(ref["dd"],2),round(ref["calmar"],3),flush=True)
        print("TEST OEM",winner,round(new["cagr"],2),round(new["dd"],2),round(new["calmar"],3),
              "BEATS_F",better,flush=True)
    else:
        result["beat_F_on_locked_test"]=False
        print("No 2024-eligible OEM; preserve F unchanged. TEST F",ref["cagr"],ref["dd"],flush=True)
    (OUT/"oem_vs_F.json").write_text(json.dumps(result,indent=2,default=float))
    return result

if __name__=="__main__":report()
