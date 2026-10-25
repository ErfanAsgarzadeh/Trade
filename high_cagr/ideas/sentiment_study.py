"""Do sentiment / positioning criteria improve the trade scores? Pre-declared before any 2025-26 number of them was looked at.
New criteria (sentiment_lib.py, 15): taker buy share (24h, z-score), open interest change (24h, 7d, with price), global and
top-trader long/short ratios (level, z-score, smart-vs-crowd), taker long/short volume ratio, Fear & Greed (level, 7d change,
extremeness), stablecoin supply growth (30d), market-wide open interest change (7d). Signed with the trade side.
Same split/replay/scenarios/accept rule as before (TRAIN 2021-10..2023-12, 2024 information/gate, TEST 2025-01..2026-10).
A) entry score: feature sets S (sentiment only), O14 (first model), O14+S, O48 (criteria study), O48+S;
   models logistic C=0.3 (win, big), ridge alpha=100 (R), gradient boosting (big). Gate and 7 scenarios as criteria_study.
B) in-trade score: the live_monitor state model (logistic C=0.1) with and without the sentiment criteria;
   reactions TIGHTEN-30%, EXIT-10%, HALF-10% and risk scaling cut30 / add70 / both30_70 (live_risk_study), with vs without.
"""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import win_prob_model as W, five_year_report as FY, criteria_lib as C, sentiment_lib as S, criteria_study as CS, live_monitor_study as LM, live_risk_study as LR
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold,GroupKFold
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/sentiment'
def pct_of(oof,p):s=np.sort(oof);return np.searchsorted(s,p,side='right')/len(s)
def judge(r,b):return r['calmar']>b['calmar'] and r['dd']>=b['dd']-2
def main():
    OUT.mkdir(parents=True,exist_ok=True);L,roots,R,X48,Rr=CS.build();em=np.array([l['em'] for l in R])
    XS=pd.DataFrame([S.at(l['coin'],l['em']//240-1,l['side']) for l in R])[S.SENT].astype(float).replace([np.inf,-np.inf],np.nan)
    X14=W.features(R).astype(float)
    tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START;Rc=np.clip(Rr,-1.5,8.);idx=np.where(tr)[0]
    tg={'win':(Rr>0).astype(int),'big':(Rr>=3).astype(int),'R':Rc}
    print('coverage of sentiment (non-NaN share) train/2024/test:',{k:[round(float(XS[k][m].notna().mean()),2) for m in (tr,gap,te)] for k in ('tbr6','oi_chg6','ls_global','fng','stable_g30')},flush=True)
    res={'single':{},'entry':{},'scen':{},'monitor':{}}
    ic=lambda a,b:float(spearmanr(a,b,nan_policy='omit')[0])
    for f in S.SENT:
        s=XS[f].to_numpy();res['single'][f]={t:dict(train=ic(s[tr],y[tr]),y2024=ic(s[gap],y[gap]),test=ic(s[te],y[te])) for t,y in tg.items()}
        r=res['single'][f]['R'];print(f'single {f:15s} IC R train {r["train"]:+.3f} 2024 {r["y2024"]:+.3f} test {r["test"]:+.3f}',flush=True)
    sets={'S':XS,'O14':X14,'O14+S':pd.concat([X14,XS],axis=1),'O48':X48,'O48+S':pd.concat([X48,XS],axis=1)}
    mods={'logit':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)),'ridge':lambda:make_pipeline(StandardScaler(),Ridge(alpha=100.)),
          'gbm':lambda:HistGradientBoostingClassifier(max_depth=3,max_iter=200,learning_rate=.05,min_samples_leaf=40,random_state=0)}
    runs=[('logit','win'),('logit','big'),('ridge','R'),('gbm','big')];pcts={}
    for sn,Xs in sets.items():
        A=Xs.fillna(Xs[tr].median()).to_numpy()
        for m,t in runs:
            y=tg[t];reg=t=='R';oof=np.zeros(len(R))
            pr=lambda mm,Z:mm.predict(Z) if reg else mm.predict_proba(Z)[:,1]
            for a,b in KFold(5,shuffle=True,random_state=0).split(idx):oof[idx[b]]=pr(mods[m]().fit(A[idx[a]],y[idx[a]]),A[idx[b]])
            p=pr(mods[m]().fit(A[tr],y[tr]),A);p[tr]=oof[tr];key=f'{sn}|{m}|{t}'
            mt=(lambda z:ic(z,Rc)) if reg else None
            met=dict(train=ic(p[tr],Rc[tr]) if reg else float(roc_auc_score(y[tr],p[tr])),y2024=ic(p[gap],Rc[gap]) if reg else float(roc_auc_score(y[gap],p[gap])),
                     test=ic(p[te],Rc[te]) if reg else float(roc_auc_score(y[te],p[te])))
            res['entry'][key]=met;pcts[key]=pct_of(oof[tr],p)
            print(f'entry {key:18s} train {met["train"]:.3f} 2024 {met["y2024"]:.3f} test {met["test"]:.3f}',flush=True)
    for key,pct in pcts.items():
        t=key.split('|')[2];thr=CS.GATE_IC if t=='R' else CS.GATE_AUC;m=res['entry'][key]
        if not (m['train']>=thr and m['y2024']>=thr):continue
        rp={L[i]['root']:pct[j] for j,i in enumerate(roots)};pl=np.array([rp[l['root']] for l in L]);out={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            out[per]={sc:{k:v for k,v in W.run_period(L,mu,a,b).items() if k!='daily'} for sc,mu in W.scenarios(pl).items()}
        res['scen'][key]=out;bt=out['test']['base'];b4=out['y2024']['base']
        pt=[s for s,x in out['test'].items() if s!='base' and judge(x,bt)];p4=[s for s,x in out['y2024'].items() if s!='base' and judge(x,b4)]
        print(f'scen {key:18s} passed TEST {len(pt)}/7 2024 {len(p4)}/7 best test Calmar {max(x["calmar"] for s,x in out["test"].items() if s!="base"):.1f} (base {bt["calmar"]:.1f})',flush=True)
    # B) in-trade
    Xm,M=LM.build(L);sts={j:LM.states(l) for j,l in enumerate(L)}
    XSm=pd.DataFrame([S.at(L[j]['coin'],b,L[j]['side']) for j,b in zip(M.leg,M.b)])[S.SENT].astype(float).replace([np.inf,-np.inf],np.nan)
    emm=M.em.to_numpy();trm=emm<W.TRAIN_END;gm=(emm>=W.TRAIN_END)&(emm<W.TEST_START);tem=emm>=W.TEST_START;y=(M.future>0).astype(int).to_numpy();grp=M.leg.to_numpy();ix=np.where(trm)[0]
    base_t=LM.replay(L,W.TEST_START);base_g=LM.replay(L,W.TRAIN_END,W.TEST_START)
    for nm,Xs in {'without':Xm,'with_sentiment':pd.concat([Xm,XSm],axis=1)}.items():
        A=Xs.fillna(Xs[trm].median()).to_numpy();mk=lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=3000));oof=np.zeros(len(M))
        for a,b in GroupKFold(5).split(ix,groups=grp[ix]):oof[ix[b]]=mk().fit(A[ix[a]],y[ix[a]]).predict_proba(A[ix[b]])[:,1]
        p=mk().fit(A[trm],y[trm]).predict_proba(A)[:,1];p[trm]=oof[trm];pct=pct_of(oof[trm],p)
        out=dict(auc=dict(train=float(roc_auc_score(y[trm],oof[trm])),y2024=float(roc_auc_score(y[gm],p[gm])),test=float(roc_auc_score(y[tem],p[tem]))),reactions={})
        print('state model',nm,out['auc'],flush=True)
        for kind,q in (('TIGHTEN',.3),('EXIT',.1),('HALF',.1)):
            tg_=LM.first_trigger(M,Xm,(pct<q)&(M.k.to_numpy()>=2));trig={j:dict(m=r.m,close=LM.px(L[j]['coin'])[r.m,3],stop=None,rn=None) for j,r in tg_.items()}
            Lm=LM.apply_reaction(L,trig,kind);out['reactions'][f'{kind}-{q}']={'test':LM.replay(Lm,W.TEST_START),'y2024':LM.replay(Lm,W.TRAIN_END,W.TEST_START)}
        pbl={};k=0
        for j in range(len(L)):n=len(sts[j]);pbl[j]=pct[k:k+n];k+=n
        for name,kw in {'cut30':dict(lo=.3,hi=2,cut=.5,mult=0,use_add=False),'add70':dict(lo=-1,hi=.7,cut=0,mult=.5,use_cut=False),'both30_70':dict(lo=.3,hi=.7,cut=.5,mult=.5)}.items():
            Lm,_,_=LR.build_legs(L,sts,pbl,bots=('main','c3','pa'),**kw);out['reactions'][name]={'test':LM.replay(Lm,W.TEST_START),'y2024':LM.replay(Lm,W.TRAIN_END,W.TEST_START)}
        for k2,v in out['reactions'].items():
            print(f"  {nm:15s} {k2:12s} TEST final {v['test']['final']:>9,.0f} DD {v['test']['dd']:6.1f} Calmar {v['test']['calmar']:5.2f} {'PASS' if judge(v['test'],base_t) else '    '} | 2024 DD {v['y2024']['dd']:6.1f} Calmar {v['y2024']['calmar']:5.2f} {'PASS' if judge(v['y2024'],base_g) else ''}",flush=True)
        res['monitor'][nm]=out
    res['base']=dict(test=base_t,y2024=base_g);(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
