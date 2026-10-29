"""Cache for the drawdown study (dd_lab.py): deployed legs of the three bots, and per fold the LBank-feasible entry filter +
momentum multipliers (E+M, lbank_feasible.entry_mult) and the protect-modified legs. Same models/folds as lbank_feasible.py."""
import sys,pickle,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, ml_xsec as XS, ml_trend_state as TS, live_monitor_study as LM, lbank_feasible as LF
from sklearn.ensemble import HistGradientBoostingClassifier
CACHE=ROOT/'high_cagr/prepared/dd_cache.pkl'
def main():
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n]
    P,_,_,_=XS.build();Pm=P[((P.day-XS.WARM)%XS.REB)==0].pivot(index='day',columns='coin',values='r30').rank(axis=1,pct=True);idx=Pm.index.to_numpy()
    def mom(l):
        k=np.searchsorted(idx,l['em']//1440,side='right')-1
        if k<0:return .5
        v=Pm.iloc[k].get(l['coin'],np.nan);v=.5 if not np.isfinite(v) else v;return v if l['side']>0 else 1-v
    mp=np.array([mom(l) for l in dep])
    S=pd.read_parquet(MD.OUT/'states_trend.parquet');em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg]
    feats=[c for c in [c for c in MD.FEATS if c in S.columns]+TS.NEW if c not in LF.BLOCKED];yb=(S.v_hold>=2).astype(int).to_numpy();Xs=S[feats].astype(np.float32).replace([np.inf,-np.inf],np.nan).to_numpy()
    Pc=lambda j,m:LM.px(L[j]['coin'])[m,3];out=dict(dep=dep,mp=mp,folds={})
    for fn,(a,b) in WF.FOLDS.items():
        ep=LF.entry_mult(L,dep,a)
        tr=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy();tri=np.where(tr)[0];tri=np.sort(np.random.RandomState(0).choice(tri,min(len(tri),600000),replace=False))
        cb=HistGradientBoostingClassifier(max_depth=5,max_iter=400,learning_rate=.05,min_samples_leaf=200,random_state=0).fit(Xs[tri],yb[tri]);b30=np.quantile(cb.predict_proba(Xs[tri])[:,1],.3)
        St=S[te].copy();St['pb']=cb.predict_proba(Xs[te])[:,1];St['kind']='TIGHTEN';Lp=WF.apply(dep,WF.triggers(St,(St.unreal_R>=1)&(St.pb<b30),dep_n,Pc))
        out['folds'][fn]=dict(ep=ep,Lp=Lp);print(fn,'done',flush=True)
    CACHE.write_bytes(pickle.dumps(out))
if __name__=='__main__':main()
