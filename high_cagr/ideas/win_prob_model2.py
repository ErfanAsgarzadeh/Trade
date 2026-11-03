"""Second pre-declared test: score = expected trade size in R, and the probability of a BIG winner (R >= 3).
Everything else is exactly win_prob_model.py (same features, split, scenarios, replay engine and accept rule):
TRAIN 2021-10..2023-12 (fit + thresholds), 2024 information only, TEST 2025-01..2026-10 judge only.
R = net P&L per unit / (entry x (stop fraction + 0.12% fee + 0.04% slippage allowance)), i.e. result in risk units.
Models (fixed now): A) logistic on y = R >= 3 (C=0.3); B) ridge regression on R clipped to [-1.5, 8] (alpha=100);
C) gradient boosting regressor on the same clipped R (comparison only). Accept rule unchanged.
"""
import sys,json
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import win_prob_model as W, five_year_report as FY
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/win_prob2';BIG=3.
def models():
    return {'big_logit':make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=2000)),
            'ridge_R':make_pipeline(StandardScaler(),Ridge(alpha=100.)),
            'gbm_R':HistGradientBoostingRegressor(max_depth=3,max_iter=150,learning_rate=.05,min_samples_leaf=40,random_state=0)}
def pred(name,m,X):return m.predict_proba(X)[:,1] if name=='big_logit' else m.predict(X)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    L=FY.ledgers('soft');roots=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in roots]
    X=W.features(R);em=np.array([l['em'] for l in R])
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R]);Rc=np.clip(Rr,-1.5,8.);yb=(Rr>=BIG).astype(int)
    tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START
    med=X[tr].median();Xf=W.fill(X,med).to_numpy()
    print('big share train/2024/test',yb[tr].mean().round(3),yb[gap].mean().round(3),yb[te].mean().round(3),'| mean R',Rr[tr].mean().round(3),Rr[gap].mean().round(3),Rr[te].mean().round(3),flush=True)
    res={'big_share':dict(train=float(yb[tr].mean()),gap=float(yb[gap].mean()),test=float(yb[te].mean())),'meanR':dict(train=float(Rr[tr].mean()),gap=float(Rr[gap].mean()),test=float(Rr[te].mean())),'models':{},'scen':{}}
    scores={}
    for name in models():
        tgt=yb if name=='big_logit' else Rc;Xt=Xf[tr];oof=np.zeros(tr.sum())
        for a,b in KFold(5).split(Xt):oof[b]=pred(name,models()[name].fit(Xt[a],tgt[tr][a]),Xt[b])
        m=models()[name].fit(Xt,tgt[tr]);p=pred(name,m,Xf);p[tr]=oof
        srt=np.sort(oof);pct=np.searchsorted(srt,p,side='right')/len(srt);scores[name]=pct
        q=np.digitize(pct,[.2,.4,.6,.8])
        bk=[dict(q=k,n=int((te&(q==k)).sum()),meanR=float(Rr[te&(q==k)].mean()),big=float(yb[te&(q==k)].mean())) for k in range(5)]
        info=dict(spearman_train_oof=float(spearmanr(oof,Rr[tr])[0]),spearman_2024=float(spearmanr(p[gap],Rr[gap])[0]),spearman_test=float(spearmanr(p[te],Rr[te])[0]),
                  auc_big_train=float(roc_auc_score(yb[tr],oof)),auc_big_2024=float(roc_auc_score(yb[gap],p[gap])),auc_big_test=float(roc_auc_score(yb[te],p[te])),test_buckets=bk)
        res['models'][name]=info
        print(name,{k:round(v,3) for k,v in info.items() if k!='test_buckets'},flush=True)
        print('  TEST by TRAIN-score quintile  n/meanR/bigShare:',[(b['n'],round(b['meanR'],2),round(b['big'],3)) for b in bk],flush=True)
    for name,pct_roots in scores.items():
        rp={L[i]['root']:pct_roots[k] for k,i in enumerate(roots)};pct=np.array([rp[l['root']] for l in L]);res['scen'][name]={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            out={}
            for sc,mult in W.scenarios(pct).items():
                r=W.run_period(L,mult,a,b)
                if per=='test':np.save(OUT/f'daily_{name}_{sc}.npy',r['daily'])
                r.pop('daily');out[sc]=r
                print(name,per,f'{sc:12s}',f"final {r['final']:>12,.0f} CAGR {r['cagr']:6.1f}% DD {r['dd']:6.1f}% Calmar {r['calmar']:5.2f} trades {r['trades']:4d} win {r['win']:4.1f}% PF {r['pf']:.2f}",flush=True)
            res['scen'][name][per]=out
    pd.DataFrame(dict(bot=[l['bot'] for l in R],coin=[l['coin'] for l in R],em=em,R=Rr,big=yb,**{f'pct_{k}':v for k,v in scores.items()})).to_csv(OUT/'scored_trades.csv',index=False)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
