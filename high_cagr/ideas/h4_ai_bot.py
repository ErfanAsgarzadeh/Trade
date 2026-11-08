"""Fourth bot: a directional 4h bot whose entries are chosen by a model that learns from technical AND sentiment data together.
PROTOCOL (fixed before any run): development folds 2023 and 2024 (train = candidates whose trade exited before the fold);
the variant with the best average combined Calmar that passes both dev folds is selected and run ONCE on 2025-01..2026-10.
CANDIDATES (closed 4h bars, 35 coins, one position per coin):
  BRK  close above the highest high of the previous 20 bars (short: below the lowest low)
  PB   uptrend (close > EMA50 > EMA200), the bar's low touched EMA20 and it closed back above EMA20 (short: mirror)
ENTRY next 4h open (+2 bps); stop 2 x ATR14 (>= 0.4%); trail = best close - 3 x ATR after each close (never looser); time
stop at the 60th bar close; 0.06% fee per side, 2 bps slippage per fill, funding.
MODEL INPUTS (at the signal bar): 48 technical criteria (criteria_lib) + 15 sentiment / positioning criteria (sentiment_lib:
taker buy share, open interest, long/short ratios, taker long/short ratio, Fear & Greed, stablecoin supply, market OI) + 30-day
momentum rank + breakout quality + rule id.  Targets: big = trade ends >= 2 R.
MODELS: gbm (gradient boosting, depth 4, 300 trees, lr 0.03, min leaf 50), logit (L2, C 0.3, standardised).
POLICIES: top50 / top30 (trade only the top 50% / 30% of training scores), top30+size (risk x (0.5 + pct)).
Risk 0.5% of equity per trade, shared-account replay (margin cap 80%, 5x isolated).
REPORT: monthly returns of the bot alone (share of positive months, mean, worst), and the three bots + bot 4 on one account.
PASS (dev): bot alone profitable in both dev years AND combined Calmar > three bots with max DD not worse by > 2 pp, both years.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM, pabench as PB, ml_xsec as XS
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/h4_ai_bot';RISK=.005;FEE=.0006
TB.DEFAULT['h4']=RISK
DEV={k:WF.FOLDS[k] for k in ('2023','2024')};FINAL={'2025-26':WF.FOLDS['2025-26']}

@njit(cache=True)
def engine(o,h,l,c,atr,sig,rule,minstop,tmax):
    n=len(c);out=np.zeros((n,8));k=0;t=210
    while t<n-2:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        e=o[t+1]*(1+s*2e-4);dist=max(2*atr[t],minstop*e);stop=e-s*dist;best=e;x=-1;xp=0.
        for k2 in range(t+1,min(t+1+tmax,n)):
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t+1 else e;xr=min(op,stop) if s==1 else max(op,stop);x=k2;xp=xr*(1-s*2e-4);break
            best=max(best,c[k2]) if s==1 else min(best,c[k2]);ns=best-s*3*atr[k2]
            if s*(ns-stop)>0:stop=ns
            if k2-t>=tmax:x=k2;xp=c[k2]*(1-s*2e-4);break
        if x<0:x=n-1;xp=c[n-1]
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;out[k,6]=rule[t];k+=1;t=x+1
    return out[:k]

def candidates():
    legs=[]
    for s in C.COINS:
        B=PB._bars(s);o,h,l,c,a=B['o'],B['h'],B['l'],B['c'],B['atr'];e20,e50,e200=B['e20'],B['e50'],B['e200']
        hi=pd.Series(h).shift(1).rolling(20).max().to_numpy();lo=pd.Series(l).shift(1).rolling(20).min().to_numpy()
        brk=np.where(c>hi,1,np.where(c<lo,-1,0))
        pbl=(c>e50)&(e50>e200)&(l<=e20)&(c>e20);pbs=(c<e50)&(e50<e200)&(h>=e20)&(c<e20);pb=np.where(pbl,1,np.where(pbs,-1,0))
        sig=np.where(brk!=0,brk,pb).astype(np.int64);rule=np.where(brk!=0,0,np.where(pb!=0,1,-1)).astype(np.int64)
        T=engine(o,h,l,c,a,sig,rule,.004,60);fc=LM.fc(s);nm=len(fc)-2
        for i,r in enumerate(T):
            t,x,sd,e,xp,sf,ru=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5],int(r[6]);em=(t+1)*240;xm=min(x*240+239,nm)
            unit=sd*(xp-e)-(e+xp)*FEE-sd*e*(fc[xm+1]-fc[em])
            lvl=hi[t] if sd>0 else lo[t]
            legs.append(dict(bot='h4',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('h4',s,i),is_add=False,t=t,rule=ru,
                             q=float(sd*(c[t]-(lvl if ru==0 else e20[t]))/a[t]),atrc=float(a[t]/c[t])))
    return legs

def features(legs):
    xs,_,_,_=XS.build();mom=xs.pivot(index='day',columns='coin',values='r30');rows=[]
    for l in legs:
        r=C.at(l['coin'],l['t'],l['side'],l['stop_frac'],'h4');r.pop('bot_c3');r.pop('bot_pa');r.update(SL.at(l['coin'],l['t'],l['side']))
        d=l['em']//1440-1;m=mom.loc[d,l['coin']] if d in mom.index else np.nan;r['mom30']=(m if l['side']>0 else 1-m) if np.isfinite(m) else np.nan
        r['rule']=l['rule'];r['q']=l['q'];r['atrc']=l['atrc'];r['side']=l['side'];rows.append(r)
    return pd.DataFrame(rows).astype(float).replace([np.inf,-np.inf],np.nan)

def monthly(daily,a_day):
    s=pd.Series(daily,index=pd.date_range(pd.Timestamp('2021-10-05')+pd.Timedelta(days=a_day),periods=len(daily)));m=s.resample('ME').last();ret=(m/m.shift(1).fillna(10000.)-1)*100
    return ret
def pct_of(ref,p):s=np.sort(ref);return np.searchsorted(s,p,side='right')/len(s)

def evaluate(folds,variants,tag):
    t0=time.time();H4=candidates();R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in H4]);y=(R>=2).astype(int)
    em=np.array([l['em'] for l in H4]);xm=np.array([l['xm'] for l in H4]);rule=np.array([l['rule'] for l in H4])
    print(f'[{tag}] candidates {len(H4)} (BRK {int((rule==0).sum())}, PB {int((rule==1).sum())}) mean R {R.mean():+.3f} win {(R>0).mean():.3f} big {y.mean():.3f}',flush=True)
    X=features(H4);L=FY.ledgers('soft');res={}
    for fn,(a,b) in folds.items():
        tr=xm<a;te=(em>=a)&((em<b) if b else True);base=WF.replay(L,a,b);out={'bots':base}
        Xf=X.fillna(X[tr].median()).to_numpy();sc={}
        sc['gbm']=HistGradientBoostingClassifier(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=50,random_state=0).fit(Xf[tr],y[tr]).predict_proba(Xf)[:,1]
        sc['logit']=make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)).fit(Xf[tr],y[tr]).predict_proba(Xf)[:,1]
        print(f'[{tag}] fold {fn}: train {tr.sum()} test {te.sum()} | AUC gbm {roc_auc_score(y[te],sc["gbm"][te]):.3f} logit {roc_auc_score(y[te],sc["logit"][te]):.3f} | three bots {base["final"]:,.0f} / {base["dd"]:.1f} / {base["calmar"]:.2f}',flush=True)
        for v in variants:
            rules,mname,pol=v.split('|')[:3];keep_rule=(rule==0) if rules=='BRK' else ((rule==1) if rules=='PB' else np.ones(len(H4),bool))
            p=pct_of(sc[mname][tr&keep_rule],sc[mname]);q=.5 if pol=='top50' else .7
            idx=np.where(te&keep_rule&(p>=q))[0];legs=[dict(H4[i],risk_scale=(.5+p[i]) if pol=='top30+size' else 1.) for i in idx]
            if not legs:continue
            r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=monthly(d,a//1440)
            rk=float(v.split('|')[3]) if v.count('|')==3 else 1.;legs=[dict(x,risk_scale=x['risk_scale']*rk) for x in legs]
            both=WF.replay(L+legs,a,b);ok=bool(r['final']>10000 and WF.judge(both,base))
            out[v]=dict(alone=r,with_bots=both,passed=ok,monthly=mo.round(2).tolist(),pos_months=float((mo>0).mean()*100),mean_month=float(mo.mean()),worst_month=float(mo.min()))
            print(f'  {v:22s} alone {r["final"]:>9,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} | months + {out[v]["pos_months"]:4.0f}% mean {out[v]["mean_month"]:+5.1f}% worst {out[v]["worst_month"]:+5.1f}% | 3 bots + bot4 {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f} {"PASS" if ok else ""}',flush=True)
        res[fn]=out
    (OUT/f'result_{tag}.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
VARIANTS=[f'{r}|{m}|{p}' for r in ('BRK','PB','ALL') for m in ('gbm','logit') for p in ('top50','top30','top30+size')]
# dev round 2 (added after round 1, still development only): bot-4 risk in the shared account x1 / x0.5 / x0.3 (0.5% / 0.25% / 0.15%)
VARIANTS2=[f'{v}|{k}' for v in ('PB|gbm|top30','PB|gbm|top30+size','BRK|gbm|top30+size','ALL|gbm|top30') for k in (1.,.5,.3)]
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>2 and sys.argv[1]=='final':evaluate(FINAL,[sys.argv[2]],'final')
    elif len(sys.argv)>1 and sys.argv[1]=='dev2':evaluate(DEV,VARIANTS2,'dev2')
    else:evaluate(DEV,VARIANTS,'dev')
