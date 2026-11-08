"""Bot 4, round 2: price-action features + 3x training universe. Pre-declared before any result was seen.
DATA: pa4h_lib (4h klines / funding / metrics for the 35 traded coins + up to 69 training-only coins).
CANDIDATES: PB = pullback to EMA20 in trend (close > EMA50 > EMA200, low <= EMA20 < close; short mirror) - as bot 4;
  PA = a with-trend price-action trigger on the closed bar (pin bar, engulfing, key reversal, SFP or EMA20 rejection, in the
  direction of EMA50 vs EMA200 with the close on the right side of EMA50). Same exits / costs as h4_ai_bot (2 ATR stop, 3 ATR
  trail on closes, 60-bar time stop, 0.06% fee per side, 2 bps slippage, funding).
VARIANTS (dev 2023, 2024; model = gradient boosting depth 4, 300 trees, lr 0.03, min leaf 50; target trade >= 2 R):
  A  PB, technical + sentiment, trained on the 35 coins          (bot 4 as is, rebuilt on this data)
  B  PB, + price action, trained on the 35 coins
  C  PB, technical + sentiment, trained on all coins
  D  PB, + price action, trained on all coins
  E  PB + PA triggers, + price action, trained on all coins
  policies top30 and top30+size; evaluated ONLY on the 35 traded coins; risk 0.5% alone, x0.3 next to the three bots.
LEARNING CURVE: fold 2024, train fractions 25/50/75/100% of the 35-coin pool and of the all-coin pool (variant D features),
  AUC on the 2024 test candidates of the 35 coins.
After dev, the best variant is compared with A on 2025-26 (NOT an independent test: bot 4 already used that year once).
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pa4h_lib as P, h4_ai_bot as H4, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, criteria_lib as CL
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/pa_bot4';FEE=.0006;TB.DEFAULT['h4']=.005
TRIG=['pin','engulf','keyrev','sfp','emarej']

def candidates(coins):
    legs=[]
    for s in coins:
        C=P.coin(s);o,h,l,c,a,e20,e50,e200=C['o'],C['h'],C['l'],C['c'],C['a'],C['e20'],C['e50'],C['e200']
        upt=(c>e50)&(e50>e200);dnt=(c<e50)&(e50<e200)
        pb=np.where(upt&(l<=e20)&(c>e20),1,np.where(dnt&(h>=e20)&(c<e20),-1,0))
        pa=np.zeros(len(c),int)
        for k in TRIG:pa=np.where(pa!=0,pa,np.where((C['P'][k]==1)&(c>e50)&(e50>e200),1,np.where((C['P'][k]==-1)&(c<e50)&(e50<e200),-1,0)))
        for rule,sig in (('PB',pb),('PA',pa)):
            s_=sig.astype(np.int64);s_[:300]=0;T=H4.engine(o,h,l,c,a,s_,np.zeros(len(c),np.int64),.004,60);fc=np.concatenate([[0.],np.cumsum(C['fund'])])
            for i,r in enumerate(T):
                t,x,sd,e,xp,sf=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5];unit=sd*(xp-e)-(e+xp)*FEE-sd*e*(fc[x+1]-fc[t+1])
                legs.append(dict(bot='h4',coin=s,side=sd,em=(t+1)*240,xm=min(x*240+239,FY.DAYS*1440-1),entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,
                                 root=('h4',rule,s,i),is_add=False,t=t,rule=rule,q=float(sd*(c[t]-e20[t])/a[t]),atrc=float(a[t]/c[t])))
    return legs

def feats(legs):
    rows=[]
    for l in legs:r=P.at(l['coin'],l['t'],l['side']);r['q']=l['q'];r['atrc']=l['atrc'];r['side']=l['side'];r['is_pa']=float(l['rule']=='PA');rows.append(r)
    return pd.DataFrame(rows).astype(float).replace([np.inf,-np.inf],np.nan)

def gbm():return HistGradientBoostingClassifier(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=50,random_state=0)
def pct_of(ref,p):s=np.sort(ref);return np.searchsorted(s,p,side='right')/len(s)
def monthly(d,a_day):
    s=pd.Series(d,index=pd.date_range(pd.Timestamp('2021-10-05')+pd.Timedelta(days=a_day),periods=len(d)));m=s.resample('ME').last();return (m/m.shift(1).fillna(10000.)-1)*100

VAR={'A':('PB','TS',False),'B':('PB','TSP',False),'C':('PB','TS',True),'D':('PB','TSP',True),'E':('ALL','TSP',True)}
def cols(fs,X):
    base=P.TECH+P.SENT+['q','atrc','side'];return [c for c in (base+(P.PAF+['is_pa'] if fs=='TSP' else [])) if c in X.columns]

def run(folds,variants,tag):
    t0=time.time();U=P.universe();L=candidates(U);print(f'[{tag}] universe {len(U)} coins, candidates {len(L)} built {time.time()-t0:.0f}s',flush=True)
    X=feats(L);print(f'[{tag}] features {X.shape} {time.time()-t0:.0f}s',flush=True)
    R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>=2).astype(int);em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L])
    traded=np.array([l['coin'] in CL.COINS for l in L]);rule=np.array([l['rule'] for l in L]);dep=FY.ledgers('soft');res={}
    for fn,(a,b) in folds.items():
        base=WF.replay(dep,a,b);out={'bots':base};tr_all=xm<a;te=(em>=a)&((em<b) if b else True)&traded
        print(f'[{tag}] fold {fn}: three bots {base["final"]:,.0f} / {base["dd"]:.1f} / {base["calmar"]:.2f}',flush=True)
        for v in variants:
            rules,fs,allc=VAR[v];keep=(rule=='PB') if rules=='PB' else np.ones(len(L),bool);tr=tr_all&keep&(np.ones(len(L),bool) if allc else traded)
            cs=cols(fs,X);A=X[cs].fillna(X.loc[tr,cs].median()).to_numpy();m=gbm().fit(A[tr],y[tr]);p=m.predict_proba(A)[:,1];pc=pct_of(p[tr&traded] if traded[tr].any() else p[tr],p)
            tt=te&keep;auc=float(roc_auc_score(y[tt],p[tt]))
            for pol in ('top30','top30+size'):
                idx=np.where(tt&(pc>=.7))[0];legs=[dict(L[i],risk_scale=(.5+pc[i]) if pol=='top30+size' else 1.) for i in idx]
                if not legs:continue
                r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=monthly(d,a//1440)
                both=WF.replay(dep+[dict(x,risk_scale=x['risk_scale']*.3) for x in legs],a,b)
                k=f'{v}|{pol}';out[k]=dict(auc=auc,n_train=int(tr.sum()),alone=r,with_bots=both,monthly=mo.round(2).tolist(),pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()),
                                          ok_alone=bool(r['final']>10000),ok_both=bool(WF.judge(both,base)))
                print(f'  {k:14s} AUC {auc:.3f} train {tr.sum():6d} | alone {r["final"]:>9,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} | months+ {out[k]["pos"]:3.0f}% mean {out[k]["mean"]:+5.1f}% worst {out[k]["worst"]:+5.1f}% | 3 bots + bot4(x0.3) {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}{" BOTH-OK" if out[k]["ok_both"] else ""}',flush=True)
        res[fn]=out
    if tag=='dev':
        a,b=WF.FOLDS['2024'];te=(em>=a)&(em<b)&traded&(rule=='PB');cs=cols('TSP',X);lc={}
        for pool,mask in (('35 coins',(xm<a)&traded&(rule=='PB')),('all coins',(xm<a)&(rule=='PB'))):
            idx=np.where(mask)[0];A=X[cs].fillna(X.loc[mask,cs].median()).to_numpy();row={}
            for f_ in (.25,.5,.75,1.):
                sub=np.sort(np.random.RandomState(0).choice(idx,int(len(idx)*f_),replace=False));m=gbm().fit(A[sub],y[sub]);row[f_]=dict(n=len(sub),auc=float(roc_auc_score(y[te],m.predict_proba(A[te])[:,1])))
            lc[pool]=row;print(f'[learning curve 2024] {pool:9s} '+' | '.join(f'{int(k*100)}%: n {v_["n"]:6d} AUC {v_["auc"]:.3f}' for k,v_ in row.items()),flush=True)
        res['learning_curve']=lc
    (OUT/f'result_{tag}.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s',flush=True)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>2 and sys.argv[1]=='compare':run({'2025-26':WF.FOLDS['2025-26']},sys.argv[2].split(','),'compare')
    else:run({k:WF.FOLDS[k] for k in ('2023','2024')},list(VAR),'dev')
