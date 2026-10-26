"""Bot 5, dev round 2 (pre-declared, judged on 2023/2024 only; 2025-26 comparison): exits and thresholds.
  thresholds T1 = round 1 (z >= 1.5 or funding >= 90th pct; stretch >= 1.5 ATR), T2 = strict (z >= 2.5 or funding >= 97th pct;
  stretch >= 2 ATR)
  exits X1 = round 1 (stop 1.5 ATR, target 1.5 R, 12 bars), X2 = mean exit (stop 1.5 ATR; exit at the first close back at/through
  EMA20; 12 bars), X3 = quick (stop 2 ATR, target 1 R, 6 bars)
  CROWD candidates; policies top30 / top50 (same model as round 1). Selection rule: best average combined Calmar (with the three
  bots + bot 4) over the dev folds among variants whose stand-alone result is > 0 in both dev folds."""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import contrarian_bot as CB, h4_ai_bot as H4, bot4_failures as BF, ml_walkforward as WF, win_prob_model as W, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM, pabench as PB, five_year_report as FY
OUT=CB.OUT
@njit(cache=True)
def engine(o,h,l,c,atr,e20,sig,mode):
    n=len(c);out=np.zeros((n,6));k=0;t=210
    sl=2. if mode==3 else 1.5;tpR=1. if mode==3 else 1.5;tmax=6 if mode==3 else 12
    while t<n-2:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        e=o[t+1]*(1+s*2e-4);dist=max(sl*atr[t],.004*e);stop=e-s*dist;tp=e+s*tpR*dist;x=-1;xp=0.
        for k2 in range(t+1,min(t+1+tmax,n)):
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t+1 else e;xr=min(op,stop) if s==1 else max(op,stop);x=k2;xp=xr*(1-s*2e-4);break
            if mode!=2 and ((s==1 and h[k2]>=tp) or (s==-1 and l[k2]<=tp)):
                op=o[k2] if k2>t+1 else e;xr=max(op,tp) if s==1 else min(op,tp);x=k2;xp=xr*(1-s*2e-4);break
            if mode==2 and s*(c[k2]-e20[k2])>=0:x=k2;xp=c[k2]*(1-s*2e-4);break
            if k2-t>=tmax:x=k2;xp=c[k2]*(1-s*2e-4);break
        if x<0:x=n-1;xp=c[n-1]
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;k+=1;t=x+1
    return out[:k]
def candidates(th,mode):
    legs=[]
    for s in C.COINS:
        B=PB._bars(s);o,h,l,c,v,a,e20=B['o'],B['h'],B['l'],B['c'],B['v'],B['atr'],B['e20'];n=len(c);S=SL.own(s);F=C.own(s)
        z=np.nan_to_num(S['ls_global_z'][:n]);fu=F['funding'][:n];qh,ql,zt,st=(.9,.1,1.5,1.5) if th==1 else (.97,.03,2.5,2.)
        fq=pd.Series(fu).rolling(180,min_periods=60).quantile(qh).to_numpy();fql=pd.Series(fu).rolling(180,min_periods=60).quantile(ql).to_numpy()
        tk=SL.taker(s);r1=np.where(tk[1][:n]>0,tk[0][:n]/np.maximum(tk[1][:n],1e-12),.5);r6=pd.Series(r1).rolling(6).mean().to_numpy()
        cs=((z>=zt)|(fu>=fq))&((c-e20)>=st*a)&(r1<r6);cl=((z<=-zt)|(fu<=fql))&((e20-c)>=st*a)&(r1>r6)
        sig=np.where(np.nan_to_num(cl),1,np.where(np.nan_to_num(cs),-1,0)).astype(np.int64);sig[:300]=0;T=engine(o,h,l,c,a,e20,sig,mode);fc=LM.fc(s);nm=len(fc)-2
        for i,r in enumerate(T):
            t,x,sd,e,xp,sf=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5];em=(t+1)*240;xm=min(x*240+239,nm);unit=sd*(xp-e)-(e+xp)*CB.FEE-sd*e*(fc[xm+1]-fc[em])
            legs.append(dict(bot='ct',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('ct2',th,mode,s,i),is_add=False,t=t,rule=0,q=float(sd*(c[t]-e20[t])/a[t]),atrc=float(a[t]/c[t])))
    return legs
def main():
    t0=time.time();trend=[dict(l) for l in FY.ledgers('soft')]+CB.g2_legs();res={};tbs={}
    for fn,(a,b) in WF.FOLDS.items():r=W.run_period(trend,[1.]*len(trend),a,b);r.pop('daily');tbs[fn]=r
    for th in (1,2):
        for mode in (1,2,3):
            L=candidates(th,mode);X=H4.features(L);R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>0).astype(int);em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L])
            print(f'T{th} X{mode}: {len(L)} candidates, win {(R>0).mean()*100:.1f}%, mean R {R.mean():+.3f}',flush=True)
            for fn,(a,b) in WF.FOLDS.items():
                tr=xm<a;te=(em>=a)&((em<b) if b else True);A=X.fillna(X[tr].median()).to_numpy();p=BF.gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];pc=BF.pct_of(p[tr],p)
                for pol,q in (('top50',.5),('top30',.7)):
                    legs=[L[i] for i in np.where(te&(pc>=q))[0]]
                    if len(legs)<5:continue
                    r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=BF.monthly(d,a//1440);both=W.run_period(trend+[dict(x,risk_scale=.3) for x in legs],[1.]*(len(trend)+len(legs)),a,b);both.pop('daily')
                    k=f'T{th}|X{mode}|{pol}';res.setdefault(k,{})[fn]=dict(alone=r,with_bots=both,mean=float(mo.mean()),pos=float((mo>0).mean()*100))
                    tb=tbs[fn];print(f'  {fn:7s} {k:14s} alone {r["final"]:>8,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} win {r["win"]:4.1f}% months+ {(mo>0).mean()*100:3.0f}% | +trend bots {both["final"]:>10,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f} (trend alone {tb["calmar"]:.2f}, DD {tb["dd"]:.1f})',flush=True)
    ok={k:v for k,v in res.items() if all(v.get(f,{}).get('alone',{}).get('final',0)>1e4 for f in ('2023','2024'))}
    best=max(ok,key=lambda k:np.mean([ok[k][f]['with_bots']['calmar'] for f in ('2023','2024')])) if ok else None
    print('dev-eligible (profitable alone in both dev years):',list(ok),'| selected:',best,flush=True)
    (OUT/'result_round2.json').write_text(json.dumps(dict(res=res,trend=tbs,selected=best),indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
