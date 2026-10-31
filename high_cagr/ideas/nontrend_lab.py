"""Non-trend strategy lab (bot 5), pre-declared before any result was seen.
PROTOCOL: development folds 2023 and 2024 (no parameter is fitted on later data; ML variants train on data before the fold).
Selection rule: among variants that are profitable ALONE in both dev years, the highest average combined Calmar (trend bots +
the strategy) is selected and then run ONCE on 2025-01..2026-10 (python nontrend_lab.py final <variant>).
All strategies trade the 35 coins on 4h bars; costs 0.06% fee + 0.02% slippage per side on every unit of turnover; funding
charged / received on every leg (Binance history); equity marked every 4h bar.
FAMILIES
 PAIRS   statistical arbitrage. Every 7 days: on the last L bars of log prices, OLS hedge ratio for each of the 595 pairs, keep pairs
         with return correlation >= 0.7 and AR(1) half-life of the spread between 6 and 60 bars, top 10 by half-life. Trade the
         spread z-score (rolling 60-bar mean/std, hedge ratio frozen for the week): enter at |z| >= Z, exit at |z| <= 0.5,
         stop at |z| >= Z + 2 or after 30 bars. Each open pair: 20% of equity gross (legs dollar-split 1 : beta). L in {360, 540},
         Z in {2.0, 2.5}.
 FUNDSPR funding spread: every K bars rank the coins by the average funding of the last 18 bars (3 days); long the N lowest,
         short the N highest, equal weight, 50% / 50% of equity. K in {6 (daily), 18}, N in {5, 8}.
 XREV    short-term cross-sectional reversal: every 6 bars (daily) rank by the vol-scaled return of the last 6 bars; long the N
         most fallen, short the N most risen, 50% / 50%, hold 6 bars. N in {5, 8}; variant XREVq: only when the cross-sectional
         dispersion is in the top half of its 180-bar history.
 RANGEMR range mean reversion (leg-based, bot replay engine): ADX14 < 20 AND Bollinger width (20, 2) in the lowest 40% of its
         500-bar history; long when the close is below the lower band and RSI14 < 30 (short mirror); exit at the middle band
         close, stop 1.5 ATR, 12-bar time stop. Policies raw / ML top50 (gradient boosting on technical + sentiment, target R > 0).
COMBINED: trend bots = three bots + bot 4 (G2 at 0.15%). Portfolio strategies are added at 50% of equity gross (daily return
  = trend + 0.5 x strategy); RANGEMR legs at 0.15% risk in the shared replay. Also reported: correlation with the trend bots.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import contrarian_bot as CB, h4_ai_bot as H4, bot4_failures as BF, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, criteria_lib as C, live_monitor_study as LM, pabench as PB
OUT=ROOT/'high_cagr/output/ideas/nontrend_lab';SIDE=.0008;TB.DEFAULT['mr']=.005
COINS=C.COINS

_P={}
def panel():
    if _P:return _P
    n=min(len(PB._bars(s)['c']) for s in COINS);cl=np.stack([PB._bars(s)['c'][:n] for s in COINS],1)
    fc=np.stack([LM.fc(s)[np.minimum((np.arange(n)+1)*240,len(LM.fc(s))-1)] for s in COINS],1);fund=np.vstack([np.zeros((1,len(COINS))),np.diff(fc,axis=0)])   # funding paid by a long over bar t
    r=np.vstack([np.zeros((1,len(COINS))),cl[1:]/cl[:-1]-1]);_P.update(n=n,cl=cl,lc=np.log(cl),r=r,fund=fund,frate=np.stack([C.own(s)['funding'][:n] for s in COINS],1));return _P

def run_weights(Wt,a,b):
    """Wt[t] = weights held from close t to close t+1. Returns daily equity for bars a..b (bar indexes), $10,000 start."""
    P=panel();r,f=P['r'],P['fund'];eq=1e4;out=[];prev=np.zeros(Wt.shape[1])
    for t in range(a,b-1):
        w=Wt[t];eq*=1-SIDE*np.abs(w-prev).sum();prev=w
        eq*=1+(w*r[t+1]).sum()-(w*f[t+1]).sum()
        if (t+2)%6==0:out.append(eq)
    return np.array(out)

def pairs_weights(L,Z,a,b):
    P=panel();lc=P['lc'];r=P['r'];n,m=lc.shape;Wt=np.zeros((n,m));open_={}
    sel=[];beta={}
    for t in range(max(a-1,L),b-1):
        if (t-a)%42==0:   # weekly re-selection from the last L bars
            X=lc[t-L+1:t+1];R=r[t-L+1:t+1];cc=np.corrcoef(R.T);cand=[]
            for i in range(m):
                for j in range(i+1,m):
                    if cc[i,j]<.7:continue
                    x,y=X[:,j],X[:,i];bb=np.polyfit(x,y,1)[0];sp=y-bb*x;ds=np.diff(sp);lag=sp[:-1]-sp[:-1].mean()
                    ph=np.dot(lag,ds)/np.dot(lag,lag)
                    if ph>=0:continue
                    hl=-np.log(2)/np.log(1+ph)
                    if 6<=hl<=60:cand.append((hl,i,j,bb))
            cand.sort();sel=[(i,j,bb) for _,i,j,bb in cand[:10]]
        for (i,j,bb) in sel:
            key=(i,j);sp=lc[t-59:t+1,i]-bb*lc[t-59:t+1,j];z=(sp[-1]-sp.mean())/(sp.std()+1e-12)
            if key in open_:
                o=open_[key];zz=(lc[t,i]-o['b']*lc[t,j]-o['mu'])/o['sd']
                if abs(zz)<=.5 or abs(zz)>=Z+2 or t-o['t']>=30:del open_[key]
            elif len(open_)<10 and abs(z)>=Z:open_[key]=dict(t=t,b=bb,s=-np.sign(z),mu=sp.mean(),sd=sp.std()+1e-12)
        for (i,j),o in list(open_.items()):
            wi=.2/(1+abs(o['b']));wj=.2*abs(o['b'])/(1+abs(o['b']));Wt[t,i]+=o['s']*wi;Wt[t,j]-=o['s']*np.sign(o['b'])*wj
    return Wt

def rank_weights(score,K,N,a,b,mask=None):
    P=panel();n,m=P['cl'].shape;Wt=np.zeros((n,m));w=np.zeros(m)
    for t in range(a,b-1):
        if (t-a)%K==0:
            s=score[t];ok=np.isfinite(s);w=np.zeros(m)
            if ok.sum()>=2*N and (mask is None or mask[t]):
                o=np.argsort(np.where(ok,s,np.nan));v=[k for k in o if ok[k]];w[v[:N]]=.5/N;w[v[-N:]]=-.5/N
        Wt[t]=w
    return Wt

def stats(d):
    yrs=len(d)/365.25;dd=(d/np.maximum.accumulate(d)-1).min()*100;cagr=((d[-1]/1e4)**(1/yrs)-1)*100 if d[-1]>0 else -100.
    return dict(final=float(d[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else 0.)

@njit(cache=True)
def mr_engine(o,h,l,c,atr,mid,sig):
    n=len(c);out=np.zeros((n,6));k=0;t=600
    while t<n-2:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        e=o[t+1]*(1+s*2e-4);dist=max(1.5*atr[t],.004*e);stop=e-s*dist;x=-1;xp=0.
        for k2 in range(t+1,min(t+13,n)):
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t+1 else e;xr=min(op,stop) if s==1 else max(op,stop);x=k2;xp=xr*(1-s*2e-4);break
            if s*(c[k2]-mid[k2])>=0 or k2-t>=12:x=k2;xp=c[k2]*(1-s*2e-4);break
        if x<0:x=n-1;xp=c[n-1]
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;k+=1;t=x+1
    return out[:k]
def mr_candidates():
    legs=[]
    for s in COINS:
        B=PB._bars(s);o,h,l,c,a=B['o'],B['h'],B['l'],B['c'],B['atr'];F=C.own(s);n=len(c)
        m20=pd.Series(c).rolling(20).mean().to_numpy();sd=pd.Series(c).rolling(20).std().to_numpy();wd=sd/m20;wr=pd.Series(wd).rolling(500,min_periods=200).rank(pct=True).to_numpy()
        rsi=B['rsi'];reg=(F['adx'][:n]<20)&(wr<.4)
        sig=np.where(reg&(c<m20-2*sd)&(rsi<30),1,np.where(reg&(c>m20+2*sd)&(rsi>70),-1,0)).astype(np.int64)
        T=mr_engine(o,h,l,c,a,m20,sig);fc=LM.fc(s);nm=len(fc)-2
        for i,r in enumerate(T):
            t,x,sd_,e,xp,sf=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5];em=(t+1)*240;xm=min(x*240+239,nm);unit=sd_*(xp-e)-(e+xp)*.0006-sd_*e*(fc[xm+1]-fc[em])
            legs.append(dict(bot='mr',coin=s,side=sd_,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('mr',s,i),is_add=False,t=t,rule=0,q=float(sd_*(c[t]-m20[t])/a[t]),atrc=float(a[t]/c[t])))
    return legs

def variants():
    V={}
    for L in (360,540):
        for Z in (2.,2.5):V[f'PAIRS_L{L}_Z{Z}']=('pairs',dict(L=L,Z=Z))
    for K in (6,18):
        for N in (5,8):V[f'FUNDSPR_K{K}_N{N}']=('fund',dict(K=K,N=N))
    for N in (5,8):V[f'XREV_N{N}']=('xrev',dict(N=N,q=False));V[f'XREVq_N{N}']=('xrev',dict(N=N,q=True))
    V['RANGEMR_raw']=('mr',dict(pol='raw'));V['RANGEMR_top50']=('mr',dict(pol='top50'));return V
# DEV ROUND 2 (added after round 1 showed FUNDSPR and XREV losing in every dev setting; still judged on dev only, final once):
#  FUNDMOM = FUNDSPR reversed (long the HIGHEST recent funding, short the lowest); XMOM = XREV reversed (long the strongest 6-bar
#  movers, short the weakest), hold K bars; same costs. K in {6, 18}, N in {5, 8}.
def variants2():
    V={}
    for K in (6,18):
        for N in (5,8):V[f'FUNDMOM_K{K}_N{N}']=('fundmom',dict(K=K,N=N));V[f'XMOM_K{K}_N{N}']=('xmom',dict(K=K,N=N))
    return V

def evaluate(folds,names,tag):
    t0=time.time();P=panel();V={**variants(),**variants2()};trend=[dict(l) for l in FY.ledgers('soft')]+CB.g2_legs();res={}
    lc,r=P['lc'],P['r'];vol=pd.DataFrame(r).rolling(60).std().to_numpy();rev=-(lc-np.vstack([np.full((6,lc.shape[1]),np.nan),lc[:-6]]))/(vol*np.sqrt(6)+1e-12)
    disp=np.nanstd(lc-np.vstack([np.full((6,lc.shape[1]),np.nan),lc[:-6]]),axis=1);dq=disp>=pd.Series(disp).rolling(180,min_periods=60).median().to_numpy()
    fscore=-pd.DataFrame(P['frate']).rolling(18).mean().to_numpy()   # high score = low funding -> long
    mr=None
    for fn,(am,bm) in folds.items():
        a=am//240;b=min((bm//240) if bm else P['n'],P['n']);tr_=W.run_period(trend,[1.]*len(trend),am,bm);dt=tr_.pop('daily');rt=np.diff(np.concatenate([[1e4],dt]))/np.concatenate([[1e4],dt[:-1]])
        out={'trend':tr_};print(f'[{tag}] fold {fn}: trend bots {tr_["final"]:,.0f} / {tr_["dd"]:.1f} / {tr_["calmar"]:.2f} ({time.time()-t0:.0f}s)',flush=True)
        for nm in names:
            fam,p=V[nm]
            if fam=='mr':
                if mr is None:mr=mr_candidates();Xmr=H4.features(mr)
                R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in mr]);em=np.array([l['em'] for l in mr]);xm=np.array([l['xm'] for l in mr]);te=(em>=am)&((em<bm) if bm else True)
                if p['pol']=='raw':keep=te
                else:
                    tr=xm<am;A=Xmr.fillna(Xmr[tr].median()).to_numpy();pp=BF.gbm().fit(A[tr],(R[tr]>0).astype(int)).predict_proba(A)[:,1];keep=te&(BF.pct_of(pp[tr],pp)>=.5)
                legs=[mr[i] for i in np.where(keep)[0]]
                if len(legs)<5:continue
                rr=W.run_period(legs,[1.]*len(legs),am,bm);d=rr.pop('daily');both=W.run_period(trend+[dict(x,risk_scale=.3) for x in legs],[1.]*(len(trend)+len(legs)),am,bm);both.pop('daily')
                st=stats(d);st['trades']=rr['trades'];rs=np.diff(np.concatenate([[1e4],d]))/np.concatenate([[1e4],d[:-1]])
            else:
                if fam=='pairs':Wt=pairs_weights(p['L'],p['Z'],a,b)
                elif fam=='fund':Wt=rank_weights(fscore,p['K'],p['N'],a,b)
                elif fam=='fundmom':Wt=rank_weights(-fscore,p['K'],p['N'],a,b)
                elif fam=='xmom':Wt=rank_weights(-rev,p['K'],p['N'],a,b)
                else:Wt=rank_weights(rev,6,p['N'],a,b,mask=dq if p['q'] else None)
                d=run_weights(Wt,a,b);st=stats(d);rs=np.diff(np.concatenate([[1e4],d]))/np.concatenate([[1e4],d[:-1]]);mm=min(len(rs),len(rt))
                comb=1e4*np.cumprod(1+rt[:mm]+.5*rs[:mm]);both=stats(comb)
            mm=min(len(rs),len(rt));corr=float(np.corrcoef(rs[:mm],rt[:mm])[0,1]);mo=BF.monthly(d,am//1440)
            out[nm]=dict(alone=st,with_trend=both,corr=corr,pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()),monthly=mo.round(2).tolist())
            print(f'  {nm:18s} alone {st["final"]:>8,.0f} CAGR {st["cagr"]:6.1f}% DD {st["dd"]:6.1f}% | months+ {(mo>0).mean()*100:3.0f}% mean {mo.mean():+5.1f}% worst {mo.min():+5.1f}% | corr {corr:+.2f} | + trend {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}',flush=True)
        res[fn]=out
    if tag in ('dev','dev2'):
        ok=[k for k in names if all(k in res[f] and res[f][k]['alone']['final']>1e4 for f in folds)]
        best=max(ok,key=lambda k:np.mean([res[f][k]['with_trend']['calmar'] for f in folds])) if ok else None
        res['eligible']=ok;res['selected']=best;print('eligible (profitable alone in both dev years):',ok,'| selected:',best,flush=True)
    (OUT/f'result_{tag}.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s',flush=True)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>2 and sys.argv[1]=='final':evaluate({'2025-26':WF.FOLDS['2025-26']},[sys.argv[2]],'final')
    elif len(sys.argv)>1 and sys.argv[1]=='dev2':evaluate({k:WF.FOLDS[k] for k in ('2023','2024')},list(variants2()),'dev2')
    else:evaluate({k:WF.FOLDS[k] for k in ('2023','2024')},list(variants()),'dev')
