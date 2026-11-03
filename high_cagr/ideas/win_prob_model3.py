"""Third pre-declared test: per-coin models (each coin is scored by a model trained on THAT coin's own past trades).
Same split, replay engine, scenarios and accept rule as win_prob_model.py / win_prob_model2.py:
TRAIN 2021-10..2023-12 (fit + percentiles), 2024 information only, TEST 2025-01..2026-10 judge only.
Targets (the three earlier ones): win (net P&L > 0), big (R >= 3), R (clipped to [-1.5, 8]).
Variants (fixed now):
  global   the earlier pooled model (logistic C=0.3 for win/big, ridge alpha=100 for R, all 14 features)
  coin     one model per coin, only 5 features (trend200, stop, rangepos, ret20, slope50), logistic C=0.05 / ridge alpha=300;
           a coin with fewer than 20 train trades (or one class only) falls back to its global score
  rate     no features: the coin's own shrunk historical mean of the target, (sum + 20*global mean)/(n + 20)
  blend    average of the global percentile and the coin percentile
Train scores are out-of-fold (5 folds inside each coin) so percentiles are not inflated. A coin is one bot's coin only
(the three bots trade disjoint coin sets), so coin == bot x coin.
"""
import sys,json
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import win_prob_model as W, five_year_report as FY
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/win_prob3'
SMALL=['trend200','stop','rangepos','ret20','slope50'];MINN=20;K=20.
def mk(target,small):
    if target=='R':return make_pipeline(StandardScaler(),Ridge(alpha=300. if small else 100.))
    return make_pipeline(StandardScaler(),LogisticRegression(C=.05 if small else .3,max_iter=2000))
def pr(target,m,X):return m.predict(X) if target=='R' else m.predict_proba(X)[:,1]
def pct_of(oof,p):
    s=np.sort(oof);return np.searchsorted(s,p,side='right')/len(s)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    L=FY.ledgers('soft');roots=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in roots]
    X=W.features(R);em=np.array([l['em'] for l in R]);coin=np.array([l['coin'] for l in R])
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R])
    tg={'win':np.array([l['unit']>0 for l in R],float),'big':(Rr>=3).astype(float),'R':np.clip(Rr,-1.5,8.)}
    tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START
    Xf=W.fill(X,X[tr].median());Xa=Xf.to_numpy();Xs=Xf[SMALL].to_numpy();idx_tr=np.where(tr)[0]
    res={'info':{},'scen':{}};allscores={}
    for t,y in tg.items():
        yb=(Rr>=3).astype(int) if t=='R' else y.astype(int)   # AUC reference label
        # global
        oof=np.zeros(len(R));pg=np.zeros(len(R))
        for a,b in KFold(5).split(idx_tr):oof[idx_tr[b]]=pr(t,mk(t,False).fit(Xa[idx_tr[a]],y[idx_tr[a]]),Xa[idx_tr[b]])
        mg=mk(t,False).fit(Xa[tr],y[tr]);pg=pr(t,mg,Xa);pg[tr]=oof[tr]
        gp=pct_of(oof[tr],pg)
        # per coin
        pc=pg.copy();pr_=np.zeros(len(R));gm=y[tr].mean();used=0
        for c in np.unique(coin):
            ci=np.where(coin==c)[0];ct=ci[tr[ci]];n=len(ct)
            # rate score (shrunk own mean)
            rate=np.zeros(len(R))
            if n>=2:
                oofr=np.zeros(len(ct))
                for a,b in KFold(min(5,n)).split(ct):oofr[b]=(y[ct[a]].sum()+K*gm)/(len(a)+K)
                pr_[ct]=oofr
            pr_[ci[~tr[ci]]]=(y[ct].sum()+K*gm)/(n+K)
            if n>=MINN and len(np.unique(y[ct]>(np.median(y[ct]) if t=='R' else .5)))>1:
                oofc=np.zeros(n)
                for a,b in KFold(5).split(ct):oofc[b]=pr(t,mk(t,True).fit(Xs[ct[a]],y[ct[a]]),Xs[ct[b]])
                m=mk(t,True).fit(Xs[ct],y[ct]);pc[ci]=pr(t,m,Xs[ci]);pc[ct]=oofc;used+=1
            else:pc[ci]=pg[ci]
        cp=pct_of(pc[tr],pc);rp=pct_of(pr_[tr],pr_);bp=.5*gp+.5*cp
        variants={'global':gp,'coin':cp,'rate':rp,'blend':bp}
        res['info'][t]={}
        for v,pct in variants.items():
            q=np.digitize(pct,[.2,.4,.6,.8]);Rt=Rr
            info=dict(spearman_train=float(spearmanr(pct[tr],Rr[tr])[0]),spearman_2024=float(spearmanr(pct[gap],Rr[gap])[0]),spearman_test=float(spearmanr(pct[te],Rr[te])[0]),
                      auc_win_test=float(roc_auc_score(tg['win'][te],pct[te])),auc_big_test=float(roc_auc_score((Rr[te]>=3).astype(int),pct[te])),
                      test_meanR_by_quintile=[float(Rt[te&(q==k)].mean()) for k in range(5)],test_n=[int((te&(q==k)).sum()) for k in range(5)])
            res['info'][t][v]=info;allscores[(t,v)]=pct
            print(t,v,{k:round(x,3) for k,x in info.items() if not isinstance(x,list)},'meanR by quintile',[round(x,2) for x in info['test_meanR_by_quintile']],flush=True)
        print(t,'coins with own model:',used,'of',len(np.unique(coin)),flush=True)
    for (t,v),pct_roots in allscores.items():
        rp={L[i]['root']:pct_roots[k] for k,i in enumerate(roots)};pct=np.array([rp[l['root']] for l in L]);key=f'{t}|{v}';res['scen'][key]={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            out={}
            for sc,mult in W.scenarios(pct).items():
                r=W.run_period(L,mult,a,b)
                if per=='test':np.save(OUT/f'daily_{t}_{v}_{sc}.npy',r['daily'])
                r.pop('daily');out[sc]=r
            res['scen'][key][per]=out
            b0=out['base'];ok=[k for k,x in out.items() if k!='base' and x['calmar']>b0['calmar'] and x['dd']>=b0['dd']-2]
            print(key,per,'passed',len(ok),ok,'| best Calmar',max(((x['calmar'],k) for k,x in out.items() if k!='base'))[1],round(max(x['calmar'] for k,x in out.items() if k!='base'),2),'base',round(b0['calmar'],2),flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
