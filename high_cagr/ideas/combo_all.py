"""All three walk-forward survivors together, pre-declared: entry score skip20 (E) + 30-day momentum sizing (M_size) at entry,
and the in-trade 'protect' policy (trend-state GBM, pooled, old+new features: when unrealised R >= 1 and P(big) is in the bottom
30% of training predictions, the stop moves 0.5 R behind the close). Same folds, replay engine and pass rule."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, sentiment_lib as SL, five_year_report as FY, ml_xsec as XS, ml_trend_state as TS, live_monitor_study as LM
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
def entry_multipliers(L,dep,fn,a):
    ri=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in ri]
    X=pd.concat([W.features(R).astype(float),pd.DataFrame([SL.at(l['coin'],l['em']//240-1,l['side']) for l in R])[SL.SENT].astype(float)],axis=1).replace([np.inf,-np.inf],np.nan)
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R]);y=(Rr>=3).astype(int);xm=np.array([l['xm'] for l in R]);tr=xm<a
    Xf=X.fillna(X[tr].median()).to_numpy();p=make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)).fit(Xf[tr],y[tr]).predict_proba(Xf)[:,1]
    srt=np.sort(p[tr]);pct=np.searchsorted(srt,p,side='right')/len(srt);rp={R[k]['root']:pct[k] for k in range(len(R))};return np.array([rp.get(l['root'],.5) for l in dep])
def main():
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n]
    P,_,_,_=XS.build();P=P[((P.day-XS.WARM)%XS.REB)==0].pivot(index='day',columns='coin',values='r30').rank(axis=1,pct=True);idx=P.index.to_numpy()
    def mom(l):
        k=np.searchsorted(idx,l['em']//1440,side='right')-1
        if k<0:return .5
        v=P.iloc[k].get(l['coin'],np.nan);v=.5 if not np.isfinite(v) else v;return v if l['side']>0 else 1-v
    mp=np.array([mom(l) for l in dep])
    S=pd.read_parquet(MD.OUT/'states_trend.parquet');em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg]
    feats=[c for c in MD.FEATS if c in S.columns]+TS.NEW;yb=(S.v_hold>=2).astype(int).to_numpy();X=S[feats].astype(np.float32).replace([np.inf,-np.inf],np.nan).to_numpy()
    Pc=lambda j,m:LM.px(L[j]['coin'])[m,3];res={}
    for fn,(a,b) in WF.FOLDS.items():
        ep=entry_multipliers(L,dep,fn,a);E=(ep>=.2).astype(float);mult=E*(.5+mp)
        tr=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy()
        tri=np.where(tr)[0];tri=np.sort(np.random.RandomState(0).choice(tri,min(len(tri),600000),replace=False))
        cb=HistGradientBoostingClassifier(max_depth=5,max_iter=400,learning_rate=.05,min_samples_leaf=200,random_state=0).fit(X[tri],yb[tri])
        b30=np.quantile(cb.predict_proba(X[tri])[:,1],.3);St=S[te].copy();St['pb']=cb.predict_proba(X[te])[:,1];St['kind']='TIGHTEN'
        trig=WF.triggers(St,(St.unreal_R>=1)&(St.pb<b30),dep_n,Pc);Lp=WF.apply(dep,trig)
        base=WF.replay(dep,a,b);out={'base':base}
        for nm,(legs,mu) in {'entry_filters':(dep,mult),'protect':(Lp,np.ones(dep_n)),'all_three':(Lp,mult)}.items():
            r=W.run_period(legs,mu,a,b);r.pop('daily');r['pass']=WF.judge(r,base);out[nm]=r
        res[fn]=out
        print(f'fold {fn}: base {base["final"]:>9,.0f} / {base["dd"]:.1f} / {base["calmar"]:.2f} | '+' | '.join(f'{k} {v["final"]:,.0f} / {v["dd"]:.1f} / {v["calmar"]:.2f}{" PASS" if v["pass"] else ""}' for k,v in out.items() if k!='base'),flush=True)
    (MD.OUT/'combo_all.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
