"""Drawdown study, AI regime model v2. Pre-declared before running.
Changes vs dd_ai.py (same features, same folds / purging, same model family):
  * twice the training data: a second reference account made of the AUGMENTED legs (the same three bots simulated on the other
    coins, ml_data.all_legs) gives a second sample per day (market features shared, system / open-position features from
    that account; its targets from that account). Prediction uses the deployed account's features only.
  * risk targets: next-10-day forward drawdown dd10 = min_k<=10 equity[d+k]/equity[d]-1, plus next-10 and next-20-day return.
  * score 'combo' = rank-average of the three GBM predictions (higher = safer / better).
Diagnostics: correlation of each score with the deployed account's next-10-day return and forward drawdown, per period.
"""
import sys,json,pickle,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_ai as A1, dd_lab as DL, ml_data as MD
from sklearn.ensemble import HistGradientBoostingRegressor
D=E.DAYS
def targets(legs):
    ref=E.replay(legs)['daily'];rr=np.r_[0,ref[1:]/ref[:-1]-1];s=pd.Series(rr)
    r10=s.rolling(10).sum().shift(-10).to_numpy();r20=s.rolling(20).sum().shift(-20).to_numpy()
    dd=np.full(D,np.nan)
    for d in range(D-10):dd[d]=min(0.,(ref[d+1:d+11]/ref[d]-1).min())
    return dict(r10=r10,r20=r20,dd10=dd)
def main():
    aug=[l for l in MD.all_legs() if l['aug']]
    Xd,_=A1.features(DL.DEP);Xa,_=A1.features(aug);Td=targets(DL.DEP);Ta=targets(aug);days=np.arange(D);res={};diag={}
    for fn,(a,b) in DL.PER.items():
        a0=a//1440;b0=(b//1440) if b else D;te=(days>=a0)&(days<b0)
        tr=(days+20<a0) if fn!='2022' else ((days>b0+30)|(days+20<a0-30));tr&=days>=60
        X=pd.concat([Xd[tr],Xa[tr]]);med=X.median();A=X.fillna(med).to_numpy();Ap=Xd.fillna(med).to_numpy();o={}
        for k in ('r10','r20','dd10'):
            y=np.r_[Td[k][tr],Ta[k][tr]];ok=np.isfinite(y)
            m=HistGradientBoostingRegressor(max_depth=3,max_iter=250,learning_rate=.03,min_samples_leaf=60,random_state=0).fit(A[ok],y[ok])
            ptr=m.predict(Ap[tr]);p=m.predict(Ap);s_=np.sort(ptr);o[k]=np.searchsorted(s_,p,side='right')/len(s_)
        cmb=o['r10']+o['r20']+o['dd10'];s_=np.sort(cmb[tr]);o['combo']=np.searchsorted(s_,cmb,side='right')/len(s_)
        res[fn]=dict(days=days[te],**{k:v[te] for k,v in o.items()})
        diag[fn]={}
        for k in ('r10','r20','dd10','combo'):
            for t in ('r10','dd10'):
                y=Td[t][te];m_=np.isfinite(y);diag[fn][f'{k}->{t}']=float(np.corrcoef(o[k][te][m_],y[m_])[0,1])
        print(fn,'train days',int(tr.sum()),{k:round(v,3) for k,v in diag[fn].items()},flush=True)
    (ROOT/'high_cagr/prepared/dd_ai2.pkl').write_bytes(pickle.dumps(res));(DL.OUT/'ai2_diag.json').write_text(json.dumps(diag,indent=1))
if __name__=='__main__':main()
