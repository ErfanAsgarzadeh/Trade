"""Bot 5: non-trend 'against the crowd' bot (4h, 35 coins), pre-declared before any result was seen.
CANDIDATES on closed 4h bars (all inputs known at the close; metrics records used only after their 5-min period ended):
  CROWD    crowd extreme + stretch + exhaustion, traded AGAINST the crowd:
           short when (global long/short z-score >= 1.5 OR 8h funding >= its 90th pct of the last 180 bars) AND the close is
           >= 1.5 ATR above EMA20 AND the 1-bar taker buy share is below its 6-bar average (buyers fading); long = mirror
  CAPIT    liquidation / capitulation reversal: long when the 6-bar move is <= -3 ATR AND open interest fell >= 4% over 6 bars AND
           volume >= 2x its 20-bar average AND the bar closed in its upper half; short = mirror (squeeze: up >= 3 ATR, OI -4%)
EXITS (mean-reversion): entry next 4h open (+2 bps), stop 1.5 ATR (1 R), target 1.5 R, time stop at the close of bar 12 (2 days);
  0.06% fee per side, 2 bps slippage per fill, funding. One position per coin.
MODEL: gradient boosting (depth 4, 300 trees, lr 0.03, min leaf 50) on the technical (48) + sentiment (15) criteria + rule id,
  target = trade ends > 0; policies: raw (all), top50, top30 by training percentile.
FOLDS: dev 2023, 2024 (train = candidates that exited before the fold); 2025-26 comparison. Risk 0.5% alone; next to the three
  bots + bot 4 (G2 at 0.15%) at x0.3 (0.15%). Also reported: correlation of daily returns with the trend bots, and the bot's
  return on the days the trend bots are in a drawdown deeper than 10%.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import h4_ai_bot as H4, bot4_failures as BF, bot4_f2 as G, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM, pabench as PB
OUT=ROOT/'high_cagr/output/ideas/contrarian_bot';FEE=.0006;TB.DEFAULT['ct']=.005;TB.DEFAULT['h4']=.005

@njit(cache=True)
def engine(o,h,l,c,atr,sig,tmax):
    n=len(c);out=np.zeros((n,7));k=0;t=210
    while t<n-2:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        e=o[t+1]*(1+s*2e-4);dist=max(1.5*atr[t],.004*e);stop=e-s*dist;tp=e+s*1.5*dist;x=-1;xp=0.
        for k2 in range(t+1,min(t+1+tmax,n)):
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t+1 else e;xr=min(op,stop) if s==1 else max(op,stop);x=k2;xp=xr*(1-s*2e-4);break
            if (s==1 and h[k2]>=tp) or (s==-1 and l[k2]<=tp):
                op=o[k2] if k2>t+1 else e;xr=max(op,tp) if s==1 else min(op,tp);x=k2;xp=xr*(1-s*2e-4);break
            if k2-t>=tmax:x=k2;xp=c[k2]*(1-s*2e-4);break
        if x<0:x=n-1;xp=c[n-1]
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;k+=1;t=x+1
    return out[:k]

def candidates():
    legs=[]
    for s in C.COINS:
        B=PB._bars(s);o,h,l,c,v,a,e20=B['o'],B['h'],B['l'],B['c'],B['v'],B['atr'],B['e20'];n=len(c);S=SL.own(s);F=C.own(s)
        z=np.nan_to_num(S['ls_global_z'][:n]);fu=F['funding'][:n];fq=pd.Series(fu).rolling(180,min_periods=60).quantile(.9).to_numpy();fql=pd.Series(fu).rolling(180,min_periods=60).quantile(.1).to_numpy()
        tk=SL.taker(s);r1=np.where(tk[1][:n]>0,tk[0][:n]/np.maximum(tk[1][:n],1e-12),.5);r6=pd.Series(r1).rolling(6).mean().to_numpy()
        up_st=(c-e20)>=1.5*a;dn_st=(e20-c)>=1.5*a
        crowd_s=((z>=1.5)|(fu>=fq))&up_st&(r1<r6);crowd_l=((z<=-1.5)|(fu<=fql))&dn_st&(r1>r6)
        m6=c-np.concatenate([np.full(6,np.nan),c[:-6]]);oi=S['oi_chg6'][:n];va=pd.Series(v).rolling(20).mean().to_numpy();pos=(c-l)/np.maximum(h-l,1e-12)
        cap_l=(m6<=-3*a)&(oi<=-.04)&(v>=2*va)&(pos>=.5);cap_s=(m6>=3*a)&(oi<=-.04)&(v>=2*va)&(pos<=.5)
        for rule,(lo,sh_) in (('CROWD',(crowd_l,crowd_s)),('CAPIT',(cap_l,cap_s))):
            sig=np.where(np.nan_to_num(lo),1,np.where(np.nan_to_num(sh_),-1,0)).astype(np.int64);sig[:300]=0
            T=engine(o,h,l,c,a,sig,12);fc=LM.fc(s);nm=len(fc)-2
            for i,r in enumerate(T):
                t,x,sd,e,xp,sf=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5];em=(t+1)*240;xm=min(x*240+239,nm)
                unit=sd*(xp-e)-(e+xp)*FEE-sd*e*(fc[xm+1]-fc[em])
                legs.append(dict(bot='ct',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('ct',rule,s,i),is_add=False,t=t,
                                 rule=0 if rule=='CROWD' else 1,rname=rule,q=float(sd*(c[t]-e20[t])/a[t]),atrc=float(a[t]/c[t])))
    return legs

def g2_legs():
    pbc=BF.candidates(True,0.);pbu=BF.candidates(False,0.);brc=G.brk_candidates(True)
    for l in pbu:l['rule']=2
    L=pbc+brc+pbu;X=H4.features(L);R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>=2).astype(int)
    em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);rule=np.array([l['rule'] for l in L]);legs=[]
    for fn,(a,b) in WF.FOLDS.items():
        tr=xm<a;A=X.fillna(X[tr].median()).to_numpy();p=BF.gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];pc=BF.pct_of(p[tr&(rule==1)],p)
        legs+=[dict(L[i],risk_scale=.3) for i in np.where((em>=a)&((em<b) if b else True)&(rule==1)&(pc>=.7))[0]]
    return legs

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();L=candidates();X=H4.features(L)
    R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>0).astype(int);em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);rn=np.array([l['rname'] for l in L])
    for r_ in ('CROWD','CAPIT'):m=rn==r_;print(f'{r_}: {m.sum()} candidates, win {(R[m]>0).mean()*100:.1f}%, mean R {R[m].mean():+.3f}',flush=True)
    trend=[dict(l) for l in FY.ledgers('soft')]+g2_legs();res={}
    for fn,(a,b) in WF.FOLDS.items():
        tb=W.run_period(trend,[1.]*len(trend),a,b);dtb=tb.pop('daily');rtb=np.diff(np.concatenate([[1e4],dtb]))/np.concatenate([[1e4],dtb[:-1]]);ddtb=dtb/np.maximum.accumulate(dtb)-1
        out={'trend_bots':tb};print(f'fold {fn}{" (comparison only)" if fn=="2025-26" else ""}: 3 bots + bot 4 {tb["final"]:,.0f} / {tb["dd"]:.1f} / {tb["calmar"]:.2f}',flush=True)
        tr=xm<a;te=(em>=a)&((em<b) if b else True);A=X.fillna(X[tr].median()).to_numpy();p=BF.gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];pc=BF.pct_of(p[tr],p)
        for pol in ('raw','top50','top30'):
            for rr in ('CROWD','CAPIT','BOTH'):
                keep=te&((rn==rr) if rr!='BOTH' else True)&(pc>={'raw':-1,'top50':.5,'top30':.7}[pol]);legs=[L[i] for i in np.where(keep)[0]]
                if len(legs)<5:continue
                r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=BF.monthly(d,a//1440);rd=np.diff(np.concatenate([[1e4],d]))/np.concatenate([[1e4],d[:-1]]);m_=min(len(rd),len(rtb))
                corr=float(np.corrcoef(rd[:m_],rtb[:m_])[0,1]);bad=ddtb[:m_]<-.10;inbad=float((np.prod(1+rd[:m_][bad])-1)*100) if bad.any() else 0.
                both=W.run_period(trend+[dict(x,risk_scale=.3) for x in legs],[1.]*(len(trend)+len(legs)),a,b);both.pop('daily');ok=bool(r['final']>1e4 and both['calmar']>tb['calmar'] and both['dd']>=tb['dd']-2)
                k=f'{rr}|{pol}';out[k]=dict(alone=r,with_bots=both,monthly=mo.round(2).tolist(),pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()),corr=corr,return_in_trend_dd=inbad,passed=ok)
                print(f'  {k:12s} alone {r["final"]:>8,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} win {r["win"]:4.1f}% | months+ {(mo>0).mean()*100:3.0f}% mean {mo.mean():+5.1f}% | corr {corr:+.2f} | in trend-DD days {inbad:+6.1f}% | +trend bots {both["final"]:>10,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}{" PASS" if ok else ""}',flush=True)
        res[fn]=out
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
