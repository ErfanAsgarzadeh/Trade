"""Walk-forward evaluation of in-trade decision models on the large state set (ml_data.py). Pre-declared before running.
FOLDS (expanding window, purged: a training leg must have EXITED before the test year starts; all legs incl. augmented):
  2023 (train = legs closed before 2023-01-01), 2024 (closed before 2024-01-01), 2025-26 (closed before 2025-01-01).
Judged on the DEPLOYED legs entered in each test window, replayed on a fresh $10,000 account (same engine/costs).
MODELS: lin = ridge (alpha 100) on standardised features; gbm = gradient boosting regressor (depth 4, 300 trees, lr 0.05,
min leaf 200). Each predicts v_hold and v_tight (R, clipped to [-3, 10]); exit = 0.
POLICIES (one action per position, first time it triggers, from hour 4 of the trade):
  decide  : act when max(v_tight_hat, 0) - v_hold_hat > 0.10 R; the action is TIGHTEN if v_tight_hat >= 0 else EXIT
  tighten30: old-style threshold - TIGHTEN when v_hold_hat is in the bottom 30% of training predictions
Pass = Calmar above the current bots AND max DD not worse by more than 2 pp, in EVERY fold.
"""
import sys,json,warnings,time
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, live_monitor_study as LM, win_prob_model as W, five_year_report as FY
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=MD.OUT;START=pd.Timestamp('2021-10-05')
def mn(d):return int((pd.Timestamp(d)-START).total_seconds()//60)
FOLDS={'2023':(mn('2023-01-01'),mn('2024-01-01')),'2024':(mn('2024-01-01'),mn('2025-01-01')),'2025-26':(mn('2025-01-01'),None)}
MODELS={'lin':lambda:make_pipeline(StandardScaler(),Ridge(alpha=100.)),
        'gbm':lambda:HistGradientBoostingRegressor(max_depth=4,max_iter=300,learning_rate=.05,min_samples_leaf=200,random_state=0)}
def judge(r,b):return r['calmar']>b['calmar'] and r['dd']>=b['dd']-2
def replay(legs,a,b):
    r=W.run_period(legs,[1.]*len(legs),a,b);r.pop('daily');return r
def triggers(S,act,dep_n,P):
    """first acting state per deployed leg -> trig dict for LM.apply_reaction, plus kind per leg"""
    sub=S[act&(S.leg<dep_n)].sort_values(['leg','m']).drop_duplicates('leg')
    return {int(r.leg):dict(m=int(r.m),close=float(P(int(r.leg),int(r.m))),stop=None,rn=None,kind=r.kind) for r in sub.itertuples()}
def apply(L,trig):
    ex={j:t for j,t in trig.items() if t['kind']=='EXIT'};ti={j:t for j,t in trig.items() if t['kind']=='TIGHTEN'}
    L1=LM.apply_reaction(L,ex,'EXIT');return LM.apply_reaction(L1,ti,'TIGHTEN')   # disjoint legs, indices unchanged for EXIT/TIGHTEN
def main(feats=None,tag=''):
    t0=time.time();L=MD.all_legs();dep=[l for l in L if not l['aug']];dep_n=len(dep)
    S=pd.read_parquet(OUT/'states.parquet');feats=feats or [f for f in MD.FEATS if f in S.columns]
    em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg]
    S=S[S.hours>=4].reset_index(drop=True);print('states',len(S),'features',len(feats),flush=True)
    yh=S.v_hold.clip(-3,10).to_numpy();yt=S.v_tight.clip(-3,10).to_numpy()
    P=lambda j,m:LM.px(L[j]['coin'])[m,3]
    res={}
    for fn,(a,b) in FOLDS.items():
        tr=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy()
        X=S[feats].astype(np.float32).replace([np.inf,-np.inf],np.nan);med=X[tr].median();Xtr=X[tr].fillna(med).to_numpy();Xte=X[te].fillna(med).to_numpy()
        base=replay(dep,a,b);out=dict(base=base,n_train=int(tr.sum()),n_test=int(te.sum()),models={})
        print(f'fold {fn}: train states {tr.sum()} test states {te.sum()} | base final {base["final"]:,.0f} DD {base["dd"]:.1f} Calmar {base["calmar"]:.2f}',flush=True)
        for mname,mk in MODELS.items():
            mh=mk().fit(Xtr,yh[tr]);mt=mk().fit(Xtr,yt[tr]);ph=mh.predict(Xte);pt=mt.predict(Xte);ph_tr=mh.predict(Xtr)
            auc=float(roc_auc_score(yh[te]>0,ph));ich=float(spearmanr(ph,yh[te])[0]);ict=float(spearmanr(pt-ph,yt[te]-yh[te])[0])
            St=S[te].copy();St['ph']=ph;St['pt']=pt;rs_={}
            gain=np.maximum(pt,0)-ph;St['kind']=np.where(pt>=0,'TIGHTEN','EXIT')
            for pol,act in {'decide':gain>.10,'tighten30':ph<np.quantile(ph_tr,.3)}.items():
                if pol=='tighten30':St['kind']='TIGHTEN'
                trig=triggers(St,act,dep_n,P);r=replay(apply(dep,trig),a,b);r['acted']=len(trig);r['pass']=judge(r,base);rs_[pol]=r
                print(f'  {mname:4s} {pol:9s} AUC(hold>0) {auc:.3f} IC hold {ich:+.3f} IC tight-hold {ict:+.3f} | final {r["final"]:>9,.0f} DD {r["dd"]:6.1f} Calmar {r["calmar"]:5.2f} acted {len(trig):4d} {"PASS" if r["pass"] else ""}',flush=True)
            out['models'][mname]=dict(auc_hold=auc,ic_hold=ich,ic_tight_minus_hold=ict,policies=rs_)
        res[fn]=out
    (OUT/f'walkforward{tag}.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
