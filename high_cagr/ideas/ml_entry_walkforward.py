"""Walk-forward check of the entry score (big-winner probability, logistic C=0.3) with and without sentiment, trained on
deployed + augmented roots (ml_data.all_legs). Folds and pass rule as ml_walkforward.py (purged: a training leg must have exited
before the test window). Scenarios: skip20 (no entry in the bottom 20% of training scores), size_lin (risk x 0.5..1.5),
size_strong (risk x 0.25..1.75). Pre-declared; nothing tuned after seeing results."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, sentiment_lib as SL, five_year_report as FY
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
def main():
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n];ri=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in ri]
    X14=W.features(R).astype(float);XS=pd.DataFrame([SL.at(l['coin'],l['em']//240-1,l['side']) for l in R])[SL.SENT].astype(float)
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R]);y=(Rr>=3).astype(int)
    em=np.array([l['em'] for l in R]);xm=np.array([l['xm'] for l in R]);isdep=np.array([i<dep_n for i in ri]);res={}
    for fn,(a,b) in WF.FOLDS.items():
        tr=xm<a;te=(em>=a)&((em<b) if b else True)&isdep;base=WF.replay(dep,a,b);res[fn]={'base':base}
        print(f'fold {fn}: train roots {tr.sum()} (aug {int((tr&~isdep).sum())}) test roots {te.sum()} | base final {base["final"]:,.0f} DD {base["dd"]:.1f} Calmar {base["calmar"]:.2f}',flush=True)
        for nm,X in {'O14':X14,'O14+S':pd.concat([X14,XS],axis=1)}.items():
            Xf=X.replace([np.inf,-np.inf],np.nan);Xf=Xf.fillna(Xf[tr].median()).to_numpy()
            m=make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)).fit(Xf[tr],y[tr]);p=m.predict_proba(Xf)[:,1]
            auc=float(roc_auc_score(y[te],p[te]));srt=np.sort(p[tr]);pct=np.searchsorted(srt,p,side='right')/len(srt)
            rp={R[k]['root']:pct[k] for k in range(len(R))};pl=np.array([rp.get(l['root'],.5) for l in dep]);out={'auc':auc}
            for sc,mu in {'skip20':(pl>=.2).astype(float),'size_lin':.5+pl,'size_strong':.25+1.5*pl}.items():
                r=W.run_period(dep,mu,a,b);r.pop('daily');r['pass']=WF.judge(r,base);out[sc]=r
                print(f'  {nm:6s} AUC {auc:.3f} {sc:11s} final {r["final"]:>9,.0f} DD {r["dd"]:6.1f} Calmar {r["calmar"]:5.2f} {"PASS" if r["pass"] else ""}',flush=True)
            res[fn][nm]=out
    (MD.OUT/'entry_walkforward.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
