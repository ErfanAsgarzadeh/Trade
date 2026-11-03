"""Export the F risk-overlay AI model (dd_ai2 'r20' GBM: next-20-day return of the three-bot account) for the live server.
Trained once on ALL days (2021-10 .. end of data) with the deployed + augmented reference accounts, exactly the dd_ai2.py
recipe. Written as plain JSON trees (no scikit-learn needed on the server) + feature medians + training-score quantiles
(for the percentile). The numpy predictor is checked against scikit-learn before writing.
Output: lbank_project/models/risk_ai_r20.json
"""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'lbank_project'))
from high_cagr.ideas import dd_ai as A1, dd_ai2 as A2, dd_lab as DL, ml_data as MD
from sklearn.ensemble import HistGradientBoostingRegressor
OUT=ROOT/'lbank_project/models/risk_ai_r20.json'
def main():
    aug=[l for l in MD.all_legs() if l['aug']]
    Xd,_=A1.features(DL.DEP);Xa,_=A1.features(aug);Td=A2.targets(DL.DEP);Ta=A2.targets(aug);days=np.arange(len(Xd));tr=days>=60
    X=pd.concat([Xd[tr],Xa[tr]]);med=X.median();A=X.fillna(med).to_numpy();y=np.r_[Td['r20'][tr],Ta['r20'][tr]];ok=np.isfinite(y)
    m=HistGradientBoostingRegressor(max_depth=3,max_iter=250,learning_rate=.03,min_samples_leaf=60,random_state=0).fit(A[ok],y[ok])
    trees=[]
    for pr in m._predictors:
        n=pr[0].nodes;trees.append(dict(f=n['feature_idx'].tolist(),t=n['num_threshold'].tolist(),l=n['left'].tolist(),r=n['right'].tolist(),leaf=n['is_leaf'].astype(int).tolist(),v=n['value'].tolist()))
    base=float(np.ravel(m._baseline_prediction)[0])
    import risk_overlay as RO
    model=dict(features=list(X.columns),medians=[float(v) for v in med],baseline=base,trees=trees)
    Ap=Xd.fillna(med).to_numpy();ref=m.predict(Ap);mine=np.array([RO.predict(model,row) for row in Xd.to_dict('records')])
    assert np.allclose(ref,mine,atol=1e-9),np.abs(ref-mine).max()
    q=np.quantile(m.predict(Ap[tr]),np.linspace(0,1,1001))
    model.update(quantiles=q.tolist(),trained_days=int(tr.sum()),trained_until=str((pd.Timestamp('2021-10-05')+pd.Timedelta(days=len(Xd)-1)).date()),
                 target='reference-account return over the next 20 days',recipe='high_cagr/ideas/dd_ai2.py r20 (stage 9 F setup)')
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(model));print('written',OUT,OUT.stat().st_size//1024,'KB, trees',len(trees),'max diff',float(np.abs(ref-mine).max()))
if __name__=='__main__':main()
