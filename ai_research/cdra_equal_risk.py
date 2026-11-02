"""Second-stage CDRA daily-proxy risk-match check; 2025-26 remains untouched.

Important: Proposed after inspecting 2024 validation (the first-stage risk-down
signal); exploratory design adjustment, NOT a pristine pre-registration.
Calibration uses ONLY 2024 max drawdown, not 2025-26 prices/returns.
Same exact F-style daily proxy (NOT Claude's genuine F). No live changes.
"""
import json
import numpy as np
from . import cdra_daily as C

OUT=C.OUT
# Discrete grid deterministic, no tuning on 2025+. Cap chosen before looking at
# the 2025 evaluation of any CDRA strategy.
GRID=np.round(np.arange(.80,2.01,.05),2)
TARGET_TOL=.30

def calibrate(r,index,g,target):
    valid=[]
    for alpha in GRID:
        v=np.array(g,copy=True)
        v[index>=C.VAL_START]=np.clip(alpha*v[index>=C.VAL_START],.3,2.)
        eq,_=C.sim_proxy(r,v)
        m=C.score_metrics(eq,index,C.VAL_START,C.TEST_START)
        # risk-matching is not selection by return; only distance from 2024 DD.
        valid.append((abs(m["max_dd"]-target),float(alpha),v,m))
    # Closest drawdown from BELOW; never deliberately exceed matched-DD target.
    valid=[z for z in valid if z[3]["max_dd"]<=target+1e-9]
    if not valid:return None
    return min(valid,key=lambda z:(z[0],z[1]))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    index,r,btc=C.data()
    x=C.features(index,r,btc)
    y=C.future_tail(r)
    bound,cal=C.fit_tail(x,y,index)
    profiles,thr=C.risk_gates(bound,index)
    feq,_=C.sim_proxy(r,np.ones(len(r)))
    vref=C.score_metrics(feq,index,C.VAL_START,C.TEST_START)
    test_ref=C.score_metrics(feq,index,C.TEST_START)
    rows={}
    eligible=[]
    for name,g in profiles.items():
        fit=calibrate(r,index,g,vref["max_dd"])
        if not fit:continue
        distance,alpha,adjusted,val=fit
        ok=(distance<=TARGET_TOL and
            val["cagr"]>vref["cagr"] and
            val["calmar"]>vref["calmar"]+.05)
        rows[name]={"alpha":alpha,"risk_distance_pp":distance,
                    "metrics":val,"eligible":bool(ok)}
        if ok: eligible.append((val["calmar"],name,alpha))
        print("RISK_MATCH_VALID",name,"alpha",alpha,"dd",round(val["max_dd"],3),
              "CAGR",round(val["cagr"],3),"Calmar",round(val["calmar"],3),
              "eligible",ok,flush=True)
    chosen=max(eligible)[1] if eligible else None
    out={"method":"Conformal tail-risk budgeting, 2024 drawdown-matched daily F-style proxy",
         "research_status":"Exploratory second-stage protocol created after 2024 CDRA results; 2025 CDRA holdout still unopened.",
         "comparability":"Daily F-style proxy only; original F NOT replayed; exact 35-symbol 1-minute data missing",
         "alpha_candidates":GRID.tolist(),
         "target_2024_drawdown":vref["max_dd"],"target_tolerance_pp":TARGET_TOL,
         "validation_ref":vref,"calibration":cal|thr,"validation_candidates":rows,
         "selected":chosen,"test_ref":test_ref,"test_selected":None,
         "better_than_F_proxy":False,"better_than_original_F":False,
         "limitations":[
           "A single aggregate equity return stream cannot reproduce F's three-bot dynamic portfolio and partial exits.",
           "Held-out AI model and frozen 2024 risk-matching selection applied without test reoptimisation.",
           "Risk target is established from 2024 data which already influenced research design, risking validation overfitting.",
           "All target profiles use off-policy reference daily account returns as both signals and labels; live execution not represented."
         ]}
    if chosen:
        alpha=rows[chosen]["alpha"]
        v=np.array(profiles[chosen],copy=True)
        v[index>=C.VAL_START]=np.clip(alpha*v[index>=C.VAL_START],.3,2.)
        eq,_=C.sim_proxy(r,v)
        test=C.score_metrics(eq,index,C.TEST_START)
        out["test_selected"]=test
        out["test_bootstrap"]=C.boot_ci(feq,eq,index)
        out["better_than_F_proxy"]=bool(test["cagr"]>test_ref["cagr"] and
                        test["max_dd"]<=test_ref["max_dd"]+.5 and
                        test["calmar"]>test_ref["calmar"])
        out["conformal_holdout_coverage"]=float(
            np.mean(y[(index>=C.TEST_START)&np.isfinite(y)]>=bound[(index>=C.TEST_START)&np.isfinite(y)]))
        pd=C.pd
        pd.DataFrame({"date":index,"f_proxy":feq,"cdra_risk_matched":eq,"risk_modifier":v}).to_csv(OUT/"cdra_equal_risk_daily.csv",index=False)
        print("RISK_MATCH_TEST",json.dumps({"selected":chosen,"baseline":test_ref,"candidate":test,
                      "better_proxy":out["better_than_F_proxy"]}),flush=True)
    else:print("RISK_MATCH: no acceptable 2024 DD-matched CDRA; no 2025 candidate test",flush=True)
    (OUT/"cdra_equal_risk_result.json").write_text(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=="__main__":main()
