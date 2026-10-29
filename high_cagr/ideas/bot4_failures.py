"""Bot 4 failure analysis and fixes. Diagnosis uses ONLY trades before 2025 (dev); 2025-26 is reported as a comparison
(not independent: bot 4 already used it). Pre-declared before any result of this script was seen.
FAILURE TYPES (trades with net R <= 0), from the 4h path after entry:
  FAST      stopped within 3 bars                       (bad timing / entry into a reversal)
  NOFOLLOW  max favourable excursion < 0.5 R, not FAST (the move never started)
  GIVEBACK  max favourable excursion >= 1 R, ended <= 0 (the trade worked and was given back)
  STALL     time stop with R <= 0 (no trend)
  OTHER     everything else (MFE 0.5..1 R then stopped)
For each type: count, share of the losses in R, and the entry features that differ most from winners (>= 2 R) - standardised
mean difference on the dev selected trades.
FIXES (dev 2023 / 2024, model and selection as bot 4: PB candidates, gradient boosting on technical + sentiment, top 30%):
  F0  bot 4 as is
  F1  failure-aware score: extra classifiers for FAST and GIVEBACK; score = rank(P(big)) - 0.5 rank(P(FAST)) - 0.5 rank(P(GIVEBACK))
  F2  confirmation: enter only if the next 4h bar closes beyond the signal bar's close in the trade direction (entry one bar later)
  F3  protect: once a 4h close is >= 1.5 R in profit, the stop moves to entry + 0.25 R (never looser)
  F4  F1 + F2 + F3
Reported: annual return, max DD, monthly stats; alone (risk 0.5%) and with the three bots (x0.3).
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import h4_ai_bot as H4, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, criteria_lib as C, live_monitor_study as LM, pabench as PB
from sklearn.ensemble import HistGradientBoostingClassifier
OUT=ROOT/'high_cagr/output/ideas/bot4_failures';FEE=.0006;TB.DEFAULT['h4']=.005

@njit(cache=True)
def engine2(o,h,l,c,atr,sig,minstop,tmax,confirm,be_r):
    n=len(c);out=np.zeros((n,12));k=0;t=210
    while t<n-3:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        t0=t
        if confirm:
            if not (s*(c[t+1]-c[t])>0):t+=1;continue
            t0=t+1
        e=o[t0+1]*(1+s*2e-4);dist=max(2*atr[t],minstop*e);stop=e-s*dist;best=e;x=-1;xp=0.;mfe=0.;mae=0.;why=0;gap=0.
        for k2 in range(t0+1,min(t0+1+tmax,n)):
            fav=(h[k2]-e) if s==1 else (e-l[k2]);adv=(e-l[k2]) if s==1 else (h[k2]-e)
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t0+1 else e;xr=min(op,stop) if s==1 else max(op,stop);gap=abs(xr-stop)/dist;x=k2;xp=xr*(1-s*2e-4);why=1
                mae=max(mae,adv/dist);mfe=max(mfe,min(fav,abs(op-e) if k2>t0+1 else 0.)/dist);break
            mfe=max(mfe,fav/dist);mae=max(mae,adv/dist)
            best=max(best,c[k2]) if s==1 else min(best,c[k2]);ns=best-s*3*atr[k2]
            if s*(ns-stop)>0:stop=ns
            if be_r>0 and s*(c[k2]-e)>=be_r*dist:
                bs=e+s*.25*dist
                if s*(bs-stop)>0:stop=bs
            if k2-t0>=tmax:x=k2;xp=c[k2]*(1-s*2e-4);why=2;break
        if x<0:x=n-1;xp=c[n-1];why=3
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;out[k,6]=t0;out[k,7]=mfe;out[k,8]=mae;out[k,9]=why;out[k,10]=x-t0;out[k,11]=gap;k+=1;t=x+1
    return out[:k]

def candidates(confirm=False,be_r=0.):
    legs=[]
    for s in C.COINS:
        B=PB._bars(s);o,h,l,c,a,e20,e50,e200=B['o'],B['h'],B['l'],B['c'],B['atr'],B['e20'],B['e50'],B['e200']
        sig=np.where((c>e50)&(e50>e200)&(l<=e20)&(c>e20),1,np.where((c<e50)&(e50<e200)&(h>=e20)&(c<e20),-1,0)).astype(np.int64)
        T=engine2(o,h,l,c,a,sig,.004,60,confirm,be_r);fc=LM.fc(s);nm=len(fc)-2
        for i,r in enumerate(T):
            t,x,sd,e,xp,sf,t0=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5],int(r[6]);em=(t0+1)*240;xm=min(x*240+239,nm)
            unit=sd*(xp-e)-(e+xp)*FEE-sd*e*(fc[xm+1]-fc[em])
            legs.append(dict(bot='h4',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('h4',s,i,confirm,be_r),is_add=False,t=t,rule=1,
                             q=float(sd*(c[t]-e20[t])/a[t]),atrc=float(a[t]/c[t]),mfe=float(r[7]),mae=float(r[8]),why=int(r[9]),bars=int(r[10]),gap=float(r[11])))
    return legs

def ftype(l,R):
    if R>0:return 'WIN'
    if l['why']==1 and l['bars']<=3:return 'FAST'
    if l['mfe']<.5:return 'NOFOLLOW'
    if l['mfe']>=1:return 'GIVEBACK'
    if l['why']==2:return 'STALL'
    return 'OTHER'

def gbm():return HistGradientBoostingClassifier(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=50,random_state=0)
def pct_of(ref,p):s=np.sort(ref);return np.searchsorted(s,p,side='right')/len(s)
def monthly(d,a_day):
    s=pd.Series(d,index=pd.date_range(pd.Timestamp('2021-10-05')+pd.Timedelta(days=a_day),periods=len(d)));m=s.resample('ME').last();return (m/m.shift(1).fillna(10000.)-1)*100

def scored(legs,X,fold,score_kind):
    a,b=fold;R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in legs]);em=np.array([l['em'] for l in legs]);xm=np.array([l['xm'] for l in legs]);tr=xm<a;te=(em>=a)&((em<b) if b else True)
    A=X.fillna(X[tr].median()).to_numpy();big=(R>=2).astype(int);p=gbm().fit(A[tr],big[tr]).predict_proba(A)[:,1];sc=pct_of(p[tr],p)
    if score_kind=='F1':
        ft=np.array([ftype(l,r) for l,r in zip(legs,R)])
        for typ in ('FAST','GIVEBACK'):
            y=(ft==typ).astype(int);q=gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];sc=sc-.5*pct_of(q[tr],q)
        sc=pct_of(sc[tr],sc)
    return sc,te,R

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();res={'diagnosis':{},'fixes':{}}
    base=candidates();Xb=H4.features(base);dev=WF.FOLDS['2023'][0],WF.FOLDS['2024'][1]
    # ---- diagnosis on selected dev trades (2023 and 2024 folds, each scored by a model trained before it)
    rows=[]
    for fn in ('2023','2024'):
        sc,te,R=scored(base,Xb,WF.FOLDS[fn],'F0');sel=np.where(te&(sc>=.7))[0]
        for i in sel:rows.append(dict(i=i,R=R[i],type=ftype(base[i],R[i]),fold=fn))
    D=pd.DataFrame(rows);tot_loss=-D.R[D.R<=0].sum()
    print(f'diagnosis: {len(D)} selected dev trades, win rate {(D.R>0).mean()*100:.1f}%, total R {D.R.sum():+.1f}, losses {-tot_loss:.1f} R',flush=True)
    Xs=Xb.iloc[D.i.values].reset_index(drop=True);win=(D.R>=2).values;mu=Xs[win].mean();sd=Xs.std()+1e-9
    for typ in ('FAST','NOFOLLOW','GIVEBACK','STALL','OTHER'):
        m=(D.type==typ).values
        if m.sum()==0:continue
        smd=((Xs[m].mean()-mu)/sd).dropna().sort_values(key=abs,ascending=False).head(6)
        res['diagnosis'][typ]=dict(n=int(m.sum()),share_of_trades=float(m.mean()*100),share_of_loss=float(-D.R[m].sum()/tot_loss*100),mean_R=float(D.R[m].mean()),top_differences=smd.round(3).to_dict())
        print(f'  {typ:9s} n {m.sum():4d} ({m.mean()*100:4.1f}% of trades) {-D.R[m].sum()/tot_loss*100:5.1f}% of the lost R, mean R {D.R[m].mean():+.2f} | vs winners: '+', '.join(f'{k} {v:+.2f}' for k,v in smd.items()),flush=True)
    w=(D.type=='WIN').values;res['diagnosis']['WIN']=dict(n=int(w.sum()),mean_R=float(D.R[w].mean()))
    gb=D[D.type=='GIVEBACK'];res['diagnosis']['giveback_mfe_median']=float(np.median([base[i]['mfe'] for i in gb.i])) if len(gb) else None
    print('  winners',w.sum(),'mean R',round(D.R[w].mean(),2),'| GIVEBACK median MFE',res['diagnosis']['giveback_mfe_median'],flush=True)
    # ---- fixes
    sets={'F0':(False,0.,'F0'),'F1':(False,0.,'F1'),'F2':(True,0.,'F0'),'F3':(False,1.5,'F0'),'F4':(True,1.5,'F1')};cache={}
    dep=FY.ledgers('soft')
    for fn,fold in WF.FOLDS.items():
        a,b=fold;bots=WF.replay(dep,a,b);res['fixes'][fn]={'bots':bots};print(f'fold {fn}{" (comparison only)" if fn=="2025-26" else ""}: three bots {bots["final"]:,.0f} / {bots["dd"]:.1f} / {bots["calmar"]:.2f}',flush=True)
        for nm,(cf,be,sk) in sets.items():
            key=(cf,be)
            if key not in cache:L=candidates(cf,be);cache[key]=(L,H4.features(L))
            L,X=cache[key];sc,te,R=scored(L,X,fold,sk);legs=[L[i] for i in np.where(te&(sc>=.7))[0]]
            r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=monthly(d,a//1440);both=WF.replay(dep+[dict(x,risk_scale=.3) for x in legs],a,b)
            res['fixes'][fn][nm]=dict(alone=r,with_bots=both,monthly=mo.round(2).tolist(),pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()))
            print(f'  {nm}: alone {r["final"]:>8,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} win {r["win"]:4.1f}% | months+ {(mo>0).mean()*100:3.0f}% mean {mo.mean():+5.1f}% worst {mo.min():+5.1f}% | +3 bots {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}',flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
