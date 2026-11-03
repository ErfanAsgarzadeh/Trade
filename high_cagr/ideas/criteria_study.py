"""Broad criteria study for the trade score, pre-declared before any 2025-26 number of these criteria was looked at.
Same data/split/replay/scenarios/accept rule as win_prob_model.py: TRAIN 2021-10..2023-12 (fit, thresholds, signs), 2024 = validation
gate, TEST 2025-01..2026-10 judged once. 48 causal criteria from criteria_lib.py.
A) Single criteria: each feature alone (sign frozen from its TRAIN Spearman with R). Reported: IC train / 2024 / test.
   Chance control: with 48 features x 3 targets, ~5% pass a 5% significance filter by luck; we count how many keep the
   same sign in 2024 AND test and compare with the number expected by chance.
B) Composite z-score: top-K train criteria (K=5, 10) by |train Spearman with clipped R|, signs frozen, equal weights
   (percentile-ranked on TRAIN) - no fitted weights.
C) Learned models on all 48 criteria (5-fold out-of-fold on TRAIN): logistic L2 (C .05/.3/1), logistic L1, ridge, gradient
   boosting, random forest, extra trees, kNN analog (k=50, 'what happened in the 50 most similar past situations'),
   Gaussian naive Bayes, LDA; targets win / big (R>=3) / clipped R where meaningful. D) one logistic per family.
Gate: a score is replayed only if TRAIN-OOF and 2024 AUC (Spearman for R targets) are both >= 0.53 (0.03); then the 8 scenarios
of win_prob_model.scenarios() run on TEST and the accept rule (Calmar > base AND DD not worse than base+2pp) is applied.
"""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import win_prob_model as W, five_year_report as FY, criteria_lib as C
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor,RandomForestClassifier,RandomForestRegressor,ExtraTreesClassifier
from sklearn.neighbors import KNeighborsClassifier,KNeighborsRegressor
from sklearn.naive_bayes import GaussianNB
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/criteria';GATE_AUC=.53;GATE_IC=.03

def build():
    L=FY.ledgers('soft');roots=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in roots];rows=[]
    for l in R:rows.append(C.at(l['coin'],l['em']//240-1,l['side'],l['stop_frac'],l['bot']))
    X=pd.DataFrame(rows)[C.ALL].astype(float).replace([np.inf,-np.inf],np.nan)
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R])
    return L,roots,R,X,Rr
def pct_of(oof,p):s=np.sort(oof);return np.searchsorted(s,p,side='right')/len(s)
def mk(name):
    return {'logit_C.05':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.05,max_iter=3000)),'logit_C.3':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)),
     'logit_C1':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=1.,max_iter=3000)),'logit_L1':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.1,penalty='l1',solver='liblinear')),
     'ridge_100':lambda:make_pipeline(StandardScaler(),Ridge(alpha=100.)),'ridge_1000':lambda:make_pipeline(StandardScaler(),Ridge(alpha=1000.)),
     'gbm':lambda:HistGradientBoostingClassifier(max_depth=3,max_iter=200,learning_rate=.05,min_samples_leaf=40,random_state=0),
     'gbm_R':lambda:HistGradientBoostingRegressor(max_depth=3,max_iter=150,learning_rate=.05,min_samples_leaf=40,random_state=0),
     'rf':lambda:RandomForestClassifier(300,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=-1),'rf_R':lambda:RandomForestRegressor(300,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=-1),
     'extra':lambda:ExtraTreesClassifier(300,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=-1),
     'knn50':lambda:make_pipeline(StandardScaler(),KNeighborsClassifier(50)),'knn50_R':lambda:make_pipeline(StandardScaler(),KNeighborsRegressor(50)),
     'nb':lambda:make_pipeline(StandardScaler(),GaussianNB()),'lda':lambda:make_pipeline(StandardScaler(),LinearDiscriminantAnalysis())}[name]()
def pred(m,X,reg):return m.predict(X) if reg else m.predict_proba(X)[:,1]
def main():
    OUT.mkdir(parents=True,exist_ok=True);L,roots,R,X,Rr=build();em=np.array([l['em'] for l in R])
    tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START;Rc=np.clip(Rr,-1.5,8.)
    tg={'win':(Rr>0).astype(int),'big':(Rr>=3).astype(int),'R':Rc};Xf=X.fillna(X[tr].median());idx=np.where(tr)[0]
    print('n',tr.sum(),gap.sum(),te.sum(),flush=True);res={'single':[],'composite':{},'models':{},'scen':{}}
    scores={}   # name -> (pct array over roots, target, kind)
    # A) single criteria
    ic=lambda a,b:float(spearmanr(a,b)[0]) if len(set(a))>1 else 0.
    for f in C.ALL:
        row=dict(feature=f,family=C.FAMILY[f])
        s=Xf[f].to_numpy();sign=1. if ic(s[tr],Rc[tr])>=0 else -1.;row['sign']=sign
        for t,y in tg.items():
            row[t]=dict(train=ic(sign*s[tr],y[tr]),y2024=ic(sign*s[gap],y[gap]),test=ic(sign*s[te],y[te]))
        res['single'].append(row)
        if abs(row['R']['train'])>=GATE_IC:scores[f'single:{f}']=(pct_of(sign*s[tr],sign*s),'R','single')
    sg=pd.DataFrame([{**{'feature':r['feature'],'family':r['family']},**{f'{t}_{p}':r[t][p] for t in tg for p in ('train','y2024','test')}} for r in res['single']])
    for t in tg:
        keep=sg[(sg[f'{t}_train'].abs()>=GATE_IC)&(np.sign(sg[f'{t}_y2024'])==np.sign(sg[f'{t}_train']))&(sg[f'{t}_y2024'].abs()>=.02)]
        ok=keep[(np.sign(keep[f'{t}_test'])==np.sign(keep[f'{t}_train']))&(keep[f'{t}_test'].abs()>=.02)]
        res['composite'][f'single_consistency_{t}']=dict(passed_train_and_2024=int(len(keep)),also_ok_on_test=int(len(ok)),features=ok.feature.tolist(),
            mean_test_ic_of_passed=float(ok[f'{t}_test'].mean()) if len(ok) else None)
        print('single',t,'pass train+2024:',len(keep),'also test:',len(ok),ok.feature.tolist(),flush=True)
    # B) composites
    ics=sg.set_index('feature')['R_train'];order=ics.abs().sort_values(ascending=False).index.tolist()
    P=Xf.copy()
    for f in C.ALL:
        s=Xf[f].to_numpy();P[f]=pct_of(np.sort(s[tr]),s)   # percentile on TRAIN
    for K in (5,10):
        top=order[:K];z=np.mean([np.sign(ics[f])*(P[f].to_numpy()-.5) for f in top],axis=0);scores[f'composite_top{K}']=(pct_of(z[tr],z),'R','composite');res['composite'][f'top{K}']=top
    # C) models
    runs=[(m,t) for m in ('logit_C.05','logit_C.3','logit_C1','logit_L1','gbm','rf','extra','knn50','nb','lda') for t in ('win','big')]+[(m,'R') for m in ('ridge_100','ridge_1000','gbm_R','rf_R','knn50_R')]
    fam={}
    for f in C.ALL:fam.setdefault(C.FAMILY[f],[]).append(f)
    def fit_score(m,t,cols):
        reg=t=='R';y=tg[t];A=Xf[cols].to_numpy();oof=np.zeros(len(R))
        for a,b in KFold(5,shuffle=True,random_state=0).split(idx):oof[idx[b]]=pred(mk(m).fit(A[idx[a]],y[idx[a]]),A[idx[b]],reg)
        p=pred(mk(m).fit(A[tr],y[tr]),A,reg);p[tr]=oof[tr];return pct_of(oof[tr],p)
    for m,t in runs:scores[f'{m}|{t}']=(fit_score(m,t,C.ALL),t,'model');print('fit',m,t,flush=True)
    for fn,cols in fam.items():
        for t in ('big','win'):scores[f'family:{fn}|{t}']=(fit_score('logit_C.3',t,cols),t,'family')
    # metrics
    def met(p,t):
        if t=='R':return dict(train=ic(p[tr],Rc[tr]),y2024=ic(p[gap],Rc[gap]),test=ic(p[te],Rc[te]))
        y=tg[t];return dict(train=float(roc_auc_score(y[tr],p[tr])),y2024=float(roc_auc_score(y[gap],p[gap])),test=float(roc_auc_score(y[te],p[te])))
    sel=[]
    for k,(p,t,kind) in scores.items():
        mm=met(p,t);res['models'][k]=dict(target=t,kind=kind,**mm);thr=GATE_IC if t=='R' else GATE_AUC
        # train metric for models is out-of-fold; for single/composite it is in-sample by construction (frozen sign)
        if mm['train']>=thr and mm['y2024']>=thr:sel.append((k,(mm['train']+mm['y2024'])/2))
    sel=[k for k,_ in sorted(sel,key=lambda z:-z[1])];print('passed the gate (replayed):',len(sel),flush=True)
    for k in sel:
        p=scores[k][0];rp={L[i]['root']:p[j] for j,i in enumerate(roots)};pct=np.array([rp[l['root']] for l in L]);res['scen'][k]={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            out={}
            for sc,mult in W.scenarios(pct).items():
                r=W.run_period(L,mult,a,b);r.pop('daily');out[sc]=r
            res['scen'][k][per]=out
        b0=res['scen'][k]['test']['base'];o=res['scen'][k]['test'];ok=[s for s,x in o.items() if s!='base' and x['calmar']>b0['calmar'] and x['dd']>=b0['dd']-2]
        o4=res['scen'][k]['y2024'];b4=o4['base'];ok4=[s for s,x in o4.items() if s!='base' and x['calmar']>b4['calmar'] and x['dd']>=b4['dd']-2]
        res['models'][k].update(passed_test=ok,passed_2024=ok4,best_test_calmar=float(max(x['calmar'] for s,x in o.items() if s!='base')),base_calmar=float(b0['calmar']))
        print(f"{k:34s} gate {res['models'][k]['train']:.3f}/{res['models'][k]['y2024']:.3f} test {res['models'][k]['test']:.3f} | scen passed TEST {len(ok)} 2024 {len(ok4)} | best test Calmar {res['models'][k]['best_test_calmar']:.1f} (base {b0['calmar']:.1f})",flush=True)
    pd.DataFrame(dict(bot=[l['bot'] for l in R],coin=[l['coin'] for l in R],em=em,R=Rr,**{k.replace('|','_').replace(':','_'):v[0] for k,v in scores.items()})).to_csv(OUT/'scores.csv',index=False)
    sg.to_csv(OUT/'single_criteria.csv',index=False);(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
