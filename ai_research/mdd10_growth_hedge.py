"""2026-11-03 exploratory CAGR recovery with a causal *BTC hedge*.

Goal: seek >100% full-period CAGR with <10% daily-close MDD, WITHOUT
changing any Shahin/C3/PA entry logic. Source is the SAME protected-rule
reference 5y daily MTM equity as the earlier risk study.

Features BTC price/EMA at the LAST COMPLETED UTC day only. BTC futures
short hedge is approximate: no actual fills/orderbook or historical funding;
we charge 0.0007 each unit of hedge turnover (0.0005 fee+0.0002 slip)
and a pessimistic 0.00015 daily carrying drag per notional unit.
These numbers are not exact actual F and cannot claim a deployable test.

This is an OPTIONAL overlay over the bots, not a BTC entry signal.
Strat selection 2021-24 ONLY; 2025-26 descriptive because the project
previously inspected it. No hard guarantee of intraday 10% DD.
"""
from pathlib import Path
from dataclasses import dataclass,asdict
import json
import numpy as np
import pandas as pd
from numba import njit
from .mdd10_frontier import ROOT,OUT,load_ref,stats,VAL,TEST
from .btc_market import load_btc_4h

SEED=20261103
CARRY=.00015
ROUND_SIDE=.0007
@dataclass(frozen=True)
class Configuration:
    name:str
    beta:float
    soft:float
    hard:float
    floor:float
    hedge:float
    market:str
    voltarget:float
    accel:float
    shock:float
    budget:float

def btc_data(idx):
    bars=load_btc_4h()
    day=bars.close.resample("1D").last().reindex(idx)
    if day.isna().any():
        raise ValueError(f"Incomplete BTC daily prices: {day.isna().sum()}")
    px=day.to_numpy(float)
    ret=np.r_[0.,px[1:]/px[:-1]-1.]
    # Observed day t is NOT available for decision at beginning of t.
    em=day.ewm(span=50,adjust=False,min_periods=50).mean()
    ema100=day.ewm(span=100,adjust=False,min_periods=100).mean()
    sig={
        "bear50":(day<em).shift(1).fillna(False).to_numpy(bool),
        "bear100":(day<ema100).shift(1).fillna(False).to_numpy(bool),
        "bearmom":(day.pct_change(30)<0).shift(1).fillna(False).to_numpy(bool),
        "bear50mom":((day<em)&(day.pct_change(30)<0)).shift(1).fillna(False).to_numpy(bool),
        "always":np.ones(len(day),bool)
    }
    return ret,sig

def grid():
    out=[]
    # Stable simple policy family, not a retrospective "winner"
    for beta in (.65,.85,1.,1.15,1.30):
        for soft,hard,floor in ((.02,.08,.1),(.04,.09,.15),
                                (.05,.10,.25),(.06,.11,.35),
                                (.08,.12,.4),(0.,0.,1.)):
            for hedge in (0.,.25,.5,.75,1.,1.4):
                for market in ("bear50","bear100","bearmom","bear50mom"):
                    if hedge==0 and market!="bear50":continue
                    out.append(Configuration("btc_hedge",beta,soft,hard,floor,hedge,market,0.,1.,0.,0.))
    # Regime-boosted risk and conservative stop-loss budget
    for beta in (.8,1.,1.2):
        for accel in (1.4,1.8,2.2):
            for voltarget in (0.,.01,.015):
                for hedge in (0.,.35,.7):
                    for market in ("bear50","bear100"):
                        for shock,budget in ((0.,0.),(.08,.09),(.12,.09)):
                            out.append(Configuration("boosted_plus_stress",beta,.04,.09,.25,
                                                     hedge,market,voltarget,accel,shock,budget))
    return out

@njit(cache=True)
def sim_loop(sys_r,btc_r,bear,beta,soft,hard,floor,hedge,voltarget,accel,shock,budget):
    n=len(sys_r);eq=np.ones(n+1);K=np.zeros(n);H=np.zeros(n);peak=1.;oldh=0.
    for t in range(n):
        dd=max(0.,1-eq[t]/peak)
        k=beta
        if hard>0 and dd>soft:
            k*=max(floor,1.-(1.-floor)*(dd-soft)/(hard-soft))
        if voltarget>0 and t>=25:
            mu=0.
            for j in range(t-20,t):mu+=sys_r[j]
            mu/=20.
            s=0.
            for j in range(t-20,t):s+=(sys_r[j]-mu)**2
            s=(s/20)**.5
            if s>1e-10:k*=min(1.5,max(.3,voltarget/s))
        # Risk re-acceleration follows positive 10d reference returns in bear-
        # reversed positive market only. All inputs before current UTC day.
        if accel>1 and t>=11:
            ret10=1.
            for j in range(t-10,t):ret10*=1.+sys_r[j]
            if ret10>1.01 and not bear[t]:k*=accel
        if shock>0:
            room=1-(1-budget)/max(1e-12,1-dd)
            k=min(k,max(0.,room/shock)) if room>0 else 0.
        k=min(2.,max(0.,k))
        # Hedge short BTC only under predated market signal.
        h=hedge if bear[t] else 0.
        # Market hedge turns over at last closes; charge BOTH entry and exit
        # at rate 0.0005 fee + .0002 slip on 100% turnover.
        turnover=abs(h-oldh)
        pnl=k*sys_r[t]-h*btc_r[t]-ROUND_SIDE*turnover-CARRY*h
        eq[t+1]=max(1e-12,eq[t]*(1+pnl))
        K[t]=k;H[t]=h
        peak=max(peak,eq[t+1])
        oldh=h
    return eq[1:],K,H

def simulate(r,btc_r,bear,p):
    return sim_loop(np.asarray(r,float),np.asarray(btc_r,float),np.asarray(bear,bool),
                    p.beta,p.soft,p.hard,p.floor,p.hedge,p.voltarget,p.accel,p.shock,p.budget)

def rank_dev(eq,idx):
    first=stats(eq,idx,None,VAL);val=stats(eq,idx,VAL,TEST)
    together=stats(eq,idx,None,TEST)
    if together["mdd"]>8.3 or val["mdd"]>8.3:return -np.inf
    return .7*val["cagr"]+.3*first["cagr"]-.15*abs(val["cagr"]-first["cagr"])

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    _,idx,ref=load_ref()
    btc,signals=btc_data(idx)
    from .mdd10_frontier import f_proxy_base
    f=f_proxy_base(ref)
    f_r=np.diff(np.r_[1.,f])/np.r_[1.,f[:-1]]
    out={"intent":"recover CAGR while MDD under10; hedge BTC using strictly past close",
         "BTC_Source":"Verified Binance USD-M 1m archived, resampled to daily closes; BTC futures hedge synthetic",
         "fee_per_hedge_side":.0005,
         "slippage_per_hedge_side":.0002,
         "hedge_carry_assumption_daily":CARRY,
         "selection":"2021-24; 2025-26 descriptive after prior project inspection",
         "not_real_F":True,
         "not_exact_account_replay":True,
         "results":{}}
    for label,baseline in [("NoF",ref),("Fstyle_PROXY",f_r)]:
        scores=[]
        for z in grid():
            eq,k,h=simulate(baseline,btc,signals[z.market],z)
            s=rank_dev(eq,idx)
            if np.isfinite(s):scores.append((s,z,eq,k,h))
        if not scores:
            out["results"][label]={"selected":None,"reason":"No candidate passed 2024 MDD safety gate"}
            continue
        score,z,eq,k,h=max(scores,key=lambda a:a[0])
        full=stats(eq,idx);val=stats(eq,idx,VAL,TEST);post=stats(eq,idx,TEST)
        out["results"][label]={"candidate_count":len(grid()),"eligible":len(scores),
           "selected":asdict(z),"selection_score":score,"full":full,
           "validation":val,"posthoc_2025_26":post,
           "avg_bot_risk_multiplier":float(k.mean()),
           "pct_days_hedged":float((h>0).mean()),
           "hedge_turnover_units":float(np.abs(np.diff(np.r_[0.,h])).sum()),
           "growth_target_pass":bool(full["cagr"]>=100 and full["mdd"]<10),
           "risk_target_pass":bool(full["mdd"]<10)}
        pd.DataFrame({"date":idx,"equity":eq,"bot_risk_k":k,"BTC_short_notional":h}).to_csv(
            OUT/f"growth_hedge_{label}_daily.csv",index=False)
        print("GROWTH_HEDGE",label,json.dumps(out["results"][label]),flush=True)
    (OUT/"growth_hedge_results.json").write_text(json.dumps(out,indent=2))
    return out
if __name__=="__main__":run()
