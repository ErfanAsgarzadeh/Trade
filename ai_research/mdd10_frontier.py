"""Research: maximise expected growth while targeting <10% *DAILY CLOSE* MDD.

Source: SHA-pinned/latest protected three-bot 5y daily mark-to-market equity
(high_cagr/output/ideas/winrate/daily_final.npy, 2021-10-05..2026-10-04).

TWO LEVELS OF EVIDENCE:
1. Daily-equity risk-overlay COUNTERFACTUAL proxy: reference strategy
   account daily returns are multiplied by a risk control known at the
   start of each day. This DOES NOT recompute execution, path-dependent
   open positions, margin, fees, funding, TP/SL or real F position cuts.
2. Exact execution requires protected leg 1m price paths for all 35 coins
   and F daily decisions; not available in repo. Never call this a real
   end-to-end account backtest.

Risk manager decisions use only *previous closed days*. A time-decaying
risk budget constrains drawdown under a hypothetical base-account shock.
No guarantee about intraday DD, gap moves or unlimited losses.

Candidate family is fixed before inspecting 2025-26; 2022-23 are
development, 2024 is selection, 2025-26 is genuinely locked risk-layer OOS.
No candidate is tuned after seeing 2025-26.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import json
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"ai_research/output/mdd_under10"
SEED=10000.
START="2021-10-05"
VAL="2024-01-01"
TEST="2025-01-01"
END="2026-10-05"

@dataclass(frozen=True)
class Policy:
    family:str
    base:float
    soft:float
    hard:float
    floor:float
    vt:float
    shock:float
    shock_budget:float
    # Derived only from prior daily returns. Not a guaranteed stop price.

def candidates():
    x=[]
    # fixed fractions are included as non-ML comparators
    for base in (.16,.20,.24,.28,.32,.36,.40,.45,.50,.55,.65,.75,1.):
        x.append(Policy("constant",base,0.,0.,0.,0.,0.,0.))
    # convex equity DD brake and EW vol targets
    for base in (.4,.6,.8,1.):
        for soft,hard in ((.025,.07),(.04,.08),(.05,.09)):
            for floor in (.0,.08):
                for vt in (0.,.007,.010):
                    x.append(Policy("dd_brake",base,soft,hard,floor,vt,0.,0.))
    # shock-limited loss budget; daily-close cap target <10
    for base in (.5,.7,.9,1.1):
        for budget in (.075,.08,.085,.09):
            for shock in (.08,.12,.16,.22,.30):
                for vt in (0.,.008,.012):
                    x.append(Policy("stress_budget",base,0.,0.,0.,vt,shock,budget))
    # hybrid (dd brake + fixed shock loss budget)
    for base in (.6,.85,1.1):
        for soft,hard in ((.025,.075),(.04,.085),(.05,.09)):
            for budget in (.075,.085,.09):
                for shock in (.10,.18,.25):
                    for vt in (0.,.008):
                        x.append(Policy("hybrid",base,soft,hard,.02,vt,shock,budget))
    # Research-only deterministic default fallbacks, independent of 2024.
    assert len(x)>200
    return x

@njit(cache=True)
def run_loop(ret,base,soft,hard,floor,vol_target,shock,budget):
    n=len(ret)
    e=np.ones(n+1,np.float64)
    risk=np.zeros(n,np.float64)
    peak=1.
    for i in range(n):
        dd=max(0.,1.-e[i]/peak)
        k=base
        if hard>0:
            if dd>soft:
                frac=(dd-soft)/(hard-soft)
                k*=max(floor,1.-(1.-floor)*frac)
        if vol_target>0 and i>=25:
            # Realised volatility ONLY from 20 days ending yesterday.
            mean=0.
            for j in range(i-20,i):mean+=ret[j]
            mean/=20
            s=0.
            for j in range(i-20,i):s+=(ret[j]-mean)**2
            s=(s/20)**.5
            if s>1e-9:k*=min(1.5,max(.20,vol_target/s))
        if shock>0:
            # Keep next day k*shock below the drawdown budget.
            room=1.-(1.-budget)/max(1e-12,1.-dd)
            if room>0:k=min(k,room/shock)
            else:k=0.0
        k=max(0.,min(1.6,k))
        risk[i]=k
        daily=1.+k*ret[i]
        e[i+1]=e[i]*max(1e-10,daily)
        if e[i+1]>peak:peak=e[i+1]
    return e[1:],risk

def simulate(r,p):
    return run_loop(np.asarray(r,float),p.base,p.soft,p.hard,p.floor,p.vt,p.shock,p.shock_budget)

def stats(curve,idx,start=None,end=None):
    mask=np.ones(len(idx),bool)
    if start is not None:mask&=idx>=pd.Timestamp(start,tz="UTC")
    if end is not None:mask&=idx<pd.Timestamp(end,tz="UTC")
    ids=np.flatnonzero(mask)
    if not len(ids):raise ValueError("Empty evaluation period")
    a,b=int(ids[0]),int(ids[-1])+1
    base=curve[a-1] if a else 1.
    d=np.r_[base,curve[a:b]]
    high=np.maximum.accumulate(d)
    dd=float(100*np.max(1.-d/high))
    years=(b-a)/365.25
    cagr=float(100*((max(d[-1]/d[0],1e-20))**(1./years)-1.))
    rr=np.diff(d)/d[:-1]
    vol=float(np.std(rr)*np.sqrt(365.25))
    return {"cagr":cagr,"mdd":dd,"calmar":cagr/dd if dd>1e-8 else None,
            "equity_multiple":float(d[-1]/d[0]),
            "daily_vol_annualized":vol,"n_days":b-a}

def score_before_2025(eq,idx):
    v=stats(eq,idx,VAL,TEST)
    pre=stats(eq,idx,None,TEST)
    # Pre-declared hard margin of safety: train+validation MDD <8.3%
    # and validation year DD <8.3%; constrain volatility as a check.
    if v["mdd"]>8.3 or pre["mdd"]>8.3:
        return float("-inf")
    return (0.75*v["cagr"]+0.25*pre["cagr"]-
            0.25*abs(v["cagr"]-pre["cagr"]))

def load_ref():
    path=ROOT/"high_cagr/output/ideas/winrate/daily_final.npy"
    q=np.load(path)
    idx=pd.date_range(START,periods=len(q),freq="D",tz="UTC")
    if idx[-1].date().isoformat()!="2026-10-04" or np.any(q<=0) or not np.isfinite(q).all():
        raise ValueError("Invalid latest protected 5y 3-bot equity series")
    r=np.r_[q[0]/SEED-1.,q[1:]/q[:-1]-1.]
    if np.any(r<=-1):raise ValueError("Bankruptcy in reference daily returns")
    return q,idx,r

def f_proxy_base(r):
    # Frozen previously specified reference F-style DAY-ONLY approximation,
    # no market AI, bot streak, shared margin or open-position reductions.
    from ai_research.cdra_daily import sim_proxy
    return sim_proxy(r,np.ones(len(r)))[0]

def screen_once(reference,idx,r,descriptor):
    base=stats(reference/SEED,idx)
    policies=candidates()
    scored=[]
    all_info=[]
    for p in policies:
        eq,k=simulate(r,p)
        dev=stats(eq,idx,None,VAL)
        val=stats(eq,idx,VAL,TEST)
        pre=stats(eq,idx,None,TEST)
        sc=score_before_2025(eq,idx)
        scored.append(sc)
        all_info.append((eq,k,dev,val,pre))
    eligible=[i for i,v in enumerate(scored) if np.isfinite(v)]
    if not eligible:
        raise AssertionError("Pre-registered safety grid produced no candidate <=8.3% on 2021-24")
    chosen=max(eligible,key=lambda i:(scored[i],-policies[i].base))
    # Predeclared particularly low-risk fallback (no new parameter tuning).
    default_fallback=Policy("safety_fallback_fixed",.20,0.,0.,0.,0.,0.,0.)
    eqfb,kfb=simulate(r,default_fallback)
    # DESCRIPTIVE IN-SAMPLE "oracle" benchmark, NEVER an OOS strategy:
    oracle_idx=None
    oracle_best=-1e40
    for i,(eq,k,dev,val,pre) in enumerate(all_info):
        st=stats(eq,idx)
        if st["mdd"]<10.0 and st["cagr"]>oracle_best:
            oracle_idx=i;oracle_best=st["cagr"]
    winners=[]
    for label,p,eq,k in [
        ("baseline",Policy("unmodified_account",1.,0.,0.,0.,0.,0.,0.),reference/SEED,np.ones(len(r))),
        ("selected_pre2025",policies[chosen],*all_info[chosen][:2]),
        ("fixed20_fallback",default_fallback,eqfb,kfb),
    ]:
        d={"label":label,"parameters":asdict(p),
           "full_2021_2026":stats(eq,idx),
           "dev_2021_2023":stats(eq,idx,None,VAL),
           "validation_2024":stats(eq,idx,VAL,TEST),
           "locked_2025_2026":stats(eq,idx,TEST),
           "mean_scale":float(np.mean(k)),
           "min_scale":float(np.min(k)),
           "safety_pass_full_daily":bool(stats(eq,idx)["mdd"]<10),
           "safety_pass_locked_daily":bool(stats(eq,idx,TEST)["mdd"]<10)}
        winners.append(d)
    if oracle_idx is not None:
        eq,_,_,_,_=all_info[oracle_idx]
        oracle={"label":"FORBIDDEN hindsight oracle, NOT deployable",
                "policy":asdict(policies[oracle_idx]),
                "full_2021_2026":stats(eq,idx)}
    else:oracle=None
    print("RESULT",descriptor,json.dumps({
        "candidates_tested":len(policies),"selection_eligible":len(eligible),
        "selected":winners[1],"fallback":winners[2],
        "in_sample_oracle":oracle},default=float),flush=True)
    return dict(descriptor=descriptor,n_candidates=len(policies),n_pre_eligible=len(eligible),
                selected_index=chosen,results=winners,
                in_sample_oracle_non_deployable=oracle,
                risk_policy_research_only=True),{
                    "baseline":reference/SEED,
                    "selected_pre2025":all_info[chosen][0],
                    "fixed20_fallback":eqfb,
                }

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    q,idx,r=load_ref()
    # Strict no-F reference and risk overlays
    raw,raw_curves=screen_once(q,idx,r,"NO F: protected full-account daily-reference risk overlay")
    # Marked-to-market *daily reference* of F-style PROXY; not actual F replay.
    fcurve=f_proxy_base(r)
    fref=fcurve*SEED
    freturns=np.diff(np.r_[1.,fcurve])/np.r_[1.,fcurve[:-1]]
    prox,proxy_curves=screen_once(fref,idx,freturns,"F-style DAILY proxy input: NOT original F risk manager")
    report={
      "date_range":[idx[0].date().isoformat(),idx[-1].date().isoformat()],
      "selection_cutoff":"2025-01-01 (2025-26 never used to choose)",
      "goals":{"max_full_daily_close_dd_pct":10.0,"pre_holdout_safety_budget":8.3,
               "maximize":"2024 CAGR under pre-2025 DD limits"},
      "mode_without_F":raw,"mode_F_style_proxy_not_F":prox,
      "source":"SHA-protected 2026 rules five-year daily equity winrate/daily_final.npy",
      "real_F_replay_status":"BLOCKED: all 35 original 1min price arrays and F AI transition events not in git",
      "critical_limitations":[
        "These are DAILY-EQUITY OVERLAYS, not re-simulated orders or exact account NAV under altered sizing.",
        "No intraday MDD guarantee. Daily shock guard uses a fixed hypothetical base-return loss, not price-level stop-loss execution.",
        "Open positions, fee/slip on cuts, original cap, new entry eligibility and funding can change materially when risk changes.",
        "Original live F effect cannot be reconstructed from saved scalar results; this F-style proxy is not Claude's F.",
        "Original protected base strategy/universe was selected using parts of 2025-26; risk-layer OOS only.",
        "These studies never deploy to PAPER or LIVE and leave original F untouched."
      ]
    }
    (OUT/"results.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,default=float))
    for name,w in [("noF",raw_curves),("Fstyle",proxy_curves)]:
        pd.DataFrame({"date":idx.astype(str),**w}).to_csv(OUT/(name+"_daily_equity.csv"),index=False)
    plot(idx,raw_curves,proxy_curves)
    md=["# MDD <10% five-year *daily-close proxy* risk study",
        "","> NOT a live-executable full 35-symbol/F replay. Pre-2025 selection, 2025-26 locked risk-layer evaluation.",
        "",
        "| Mode | Policy | Full CAGR (%) | Full MDD (%) | 2024 CAGR (%) | 2024 MDD (%) | Holdout CAGR (%) | Holdout MDD (%) | Full <10% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for group in (raw,prox):
        for z in group["results"]:
            v=z["full_2021_2026"];h=z["locked_2025_2026"];w=z["validation_2024"]
            md.append(f"| {group['descriptor']} | {z['label']} | {v['cagr']:.2f} | {v['mdd']:.2f} | {w['cagr']:.2f} | {w['mdd']:.2f} | {h['cagr']:.2f} | {h['mdd']:.2f} | {'YES' if v['mdd']<10 else 'NO'} |")
    (OUT/"results.md").write_text("\n".join(md)+"\n")
    print("\n".join(md),flush=True)
    return report

def plot(idx,raw,prox):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(2,1,figsize=(15,11),sharex=True)
    for group,paths in (("NoF",raw),("F-style NOT F",prox)):
        for tag,curve in paths.items():
            label=group+" "+tag
            ax[0].plot(idx,curve,lw=1.2,label=label)
            dd=100*(curve/np.maximum.accumulate(np.r_[1.,curve])[1:]-1)
            ax[1].plot(idx,dd,lw=1.15,label=label)
    ax[0].set_yscale("log");ax[0].set_ylabel("Daily equity multiple (log)")
    ax[0].legend(ncol=2,fontsize=8)
    ax[0].set_title("MDD <10 Research: causal daily-equity risk overlays, NOT full account execution")
    ax[1].axhline(-10,color="red",lw=1,linestyle="--",label="10% MDD goal")
    ax[1].set_ylabel("Daily-close drawdown %")
    ax[1].legend(fontsize=8,ncol=2)
    fig.tight_layout();fig.savefig(OUT/"mdd10_equity_drawdown.png",dpi=150);plt.close(fig)

if __name__=="__main__":main()
