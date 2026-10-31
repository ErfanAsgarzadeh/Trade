"""Combination of the two filters that passed every walk-forward fold, pre-declared:
  E = entry score (big-winner logistic on O14 + sentiment, trained on deployed + augmented roots, ml_entry_walkforward.py): skip the
      bottom 20% of training scores
  M = 30-day momentum rank of the coin across the 35 (side-adjusted, latest weekly value, ml_xsec.py): skip20 or size (0.5 + pct)
Variants: E, M_skip, M_size, E+M_skip (skip if either), E+M_size (E skip, then risk x (0.5 + pct)).
Same folds, replay engine and pass rule (Calmar > current bots and DD not worse by > 2 pp in every fold)."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, sentiment_lib as SL, five_year_report as FY, ml_xsec as XS
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
def main():
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n];ri=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in ri]
    X=pd.concat([W.features(R).astype(float),pd.DataFrame([SL.at(l['coin'],l['em']//240-1,l['side']) for l in R])[SL.SENT].astype(float)],axis=1).replace([np.inf,-np.inf],np.nan)
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R]);y=(Rr>=3).astype(int);xm=np.array([l['xm'] for l in R])
    P,_,_,_=XS.build();P=P[((P.day-XS.WARM)%XS.REB)==0].pivot(index='day',columns='coin',values='r30').rank(axis=1,pct=True);idx=P.index.to_numpy()
    def mom(l):
        k=np.searchsorted(idx,l['em']//1440,side='right')-1
        if k<0:return .5
        v=P.iloc[k].get(l['coin'],np.nan);v=.5 if not np.isfinite(v) else v;return v if l['side']>0 else 1-v
    mp=np.array([mom(l) for l in dep]);res={}
    for fn,(a,b) in WF.FOLDS.items():
        tr=xm<a;Xf=X.fillna(X[tr].median()).to_numpy();m=make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)).fit(Xf[tr],y[tr]);p=m.predict_proba(Xf)[:,1]
        srt=np.sort(p[tr]);pct=np.searchsorted(srt,p,side='right')/len(srt);rp={R[k]['root']:pct[k] for k in range(len(R))};ep=np.array([rp.get(l['root'],.5) for l in dep])
        E=(ep>=.2).astype(float);Ms=(mp>=.2).astype(float);Mz=.5+mp
        base=WF.replay(dep,a,b);out={'base':base}
        print(f'fold {fn}: base final {base["final"]:,.0f} DD {base["dd"]:.1f} Calmar {base["calmar"]:.2f}',flush=True)
        for nm,mu in {'E':E,'M_skip':Ms,'M_size':Mz,'E+M_skip':E*Ms,'E+M_size':E*Mz}.items():
            r=W.run_period(dep,mu,a,b);r.pop('daily');r['pass']=WF.judge(r,base);out[nm]=r
            print(f'  {nm:9s} final {r["final"]:>9,.0f} DD {r["dd"]:6.1f} Calmar {r["calmar"]:5.2f} trades {r["trades"]:5d} {"PASS" if r["pass"] else ""}',flush=True)
        res[fn]=out
    (MD.OUT/'combo_filters.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
