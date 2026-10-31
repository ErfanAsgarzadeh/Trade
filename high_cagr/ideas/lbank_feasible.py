"""Re-test of every component with ONLY the inputs the live LBank bot can get. Pre-declared before running.
Available live: prices / candles and volume (LBank), funding (LBank), Fear & Greed (alternative.me), stablecoin supply (DefiLlama).
NOT available: Binance open interest, long/short ratios, taker buy volume (Binance futures API blocked; LBank has no history).
Removed inputs: taker buy share, OI, global / top long-short ratios, taker long/short ratio, market OI, and everything derived
from them (smart-vs-crowd, OI-since-entry, taker-since-entry, ...). Everything else (models, folds, policies, pass rule) is
exactly as in the original scripts: combo_all.py (entry filter E + momentum sizing M + in-trade protect), bot4_f2.py G2 (bot 4),
xsec_bot5.py S0 (bot 5). Folds 2023 / 2024 / 2025-26, each model trained only on data before its fold.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, sentiment_lib as SL, five_year_report as FY, ml_xsec as XS, ml_trend_state as TS, live_monitor_study as LM
from high_cagr.ideas import bot4_failures as BF, bot4_f2 as G, h4_ai_bot as H4, contrarian_bot as CB, xsec_bot5 as X5, combo_all as CA
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
OUT=ROOT/'high_cagr/output/ideas/lbank_feasible'
SENT_OK=['fng','fng_chg7','fng_extreme','stable_g30']
BLOCKED=set(SL.SENT)-set(SENT_OK)|{'tbr1h','tb_since','tb_24h','tb_div','oi_since','oi_24h','tbr6','tbr_z','taker_ls6','tb1','tb4','tb16','tbz','oi1','oi4','oi16','lsg','lst','lsg16','lst16','tls','tb7','tb30','oi7','oi30','lsg7','lst7','svc','btc_tb4'}

def entry_mult(L,dep,a):
    ri=[i for i,l in enumerate(L) if not l['is_add']];R=[L[i] for i in ri]
    X=pd.concat([W.features(R).astype(float),pd.DataFrame([SL.at(l['coin'],l['em']//240-1,l['side']) for l in R])[SENT_OK].astype(float)],axis=1).replace([np.inf,-np.inf],np.nan)
    Rr=np.array([l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in R]);y=(Rr>=3).astype(int);xm=np.array([l['xm'] for l in R]);tr=xm<a
    Xf=X.fillna(X[tr].median()).to_numpy();p=make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=3000)).fit(Xf[tr],y[tr]).predict_proba(Xf)[:,1]
    pct=BF.pct_of(p[tr],p);rp={R[k]['root']:pct[k] for k in range(len(R))};return np.array([rp.get(l['root'],.5) for l in dep])

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();res={}
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n]
    P,_,_,_=XS.build();Pm=P[((P.day-XS.WARM)%XS.REB)==0].pivot(index='day',columns='coin',values='r30').rank(axis=1,pct=True);idx=Pm.index.to_numpy()
    def mom(l):
        k=np.searchsorted(idx,l['em']//1440,side='right')-1
        if k<0:return .5
        v=Pm.iloc[k].get(l['coin'],np.nan);v=.5 if not np.isfinite(v) else v;return v if l['side']>0 else 1-v
    mp=np.array([mom(l) for l in dep])
    S=pd.read_parquet(MD.OUT/'states_trend.parquet');em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg]
    feats=[c for c in [c for c in MD.FEATS if c in S.columns]+TS.NEW if c not in BLOCKED];yb=(S.v_hold>=2).astype(int).to_numpy();Xs=S[feats].astype(np.float32).replace([np.inf,-np.inf],np.nan).to_numpy()
    print('protect features',len(feats),flush=True);Pc=lambda j,m:LM.px(L[j]['coin'])[m,3]
    # bot 4 (G2) with LBank-feasible features
    pbc=BF.candidates(True,0.);pbu=BF.candidates(False,0.);brc=G.brk_candidates(True)
    for l in pbu:l['rule']=2
    G2=pbc+brc+pbu;XG=H4.features(G2);XG=XG[[c for c in XG.columns if c not in BLOCKED]];RG=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in G2]);yG=(RG>=2).astype(int)
    emG=np.array([l['em'] for l in G2]);xmG=np.array([l['xm'] for l in G2]);ruG=np.array([l['rule'] for l in G2])
    # bot 5 (S0) with LBank-feasible features
    X5p,f5,coins,r1,fund,n5=X5.panel();f5=[f for f in f5 if f not in BLOCKED];print('bot 5 features',len(f5),'bot 4 features',XG.shape[1],flush=True)
    for fn,(a,b) in WF.FOLDS.items():
        base=WF.replay(dep,a,b);ep=entry_mult(L,dep,a);mult=(ep>=.2).astype(float)*(.5+mp)
        tr=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy();tri=np.where(tr)[0];tri=np.sort(np.random.RandomState(0).choice(tri,min(len(tri),600000),replace=False))
        cb=HistGradientBoostingClassifier(max_depth=5,max_iter=400,learning_rate=.05,min_samples_leaf=200,random_state=0).fit(Xs[tri],yb[tri]);b30=np.quantile(cb.predict_proba(Xs[tri])[:,1],.3)
        St=S[te].copy();St['pb']=cb.predict_proba(Xs[te])[:,1];St['kind']='TIGHTEN';Lp=WF.apply(dep,WF.triggers(St,(St.unreal_R>=1)&(St.pb<b30),dep_n,Pc))
        o={'base':base}
        for nm,(legs,mu) in {'E+M':(dep,mult),'M only':(dep,.5+mp),'protect':(Lp,np.ones(dep_n)),'all three':(Lp,mult)}.items():
            r=W.run_period(legs,mu,a,b);r.pop('daily');r['pass']=WF.judge(r,base);o[nm]=r
        # bot 4
        trg=xmG<a;A=XG.fillna(XG[trg].median()).to_numpy();p=BF.gbm().fit(A[trg],yG[trg]).predict_proba(A)[:,1];pc=BF.pct_of(p[trg&(ruG==1)],p)
        b4=[G2[i] for i in np.where((emG>=a)&((emG<b) if b else True)&(ruG==1)&(pc>=.7))[0]];r=W.run_period(b4,[1.]*len(b4),a,b);r.pop('daily');o['bot4 alone']=r
        tb=W.run_period(Lp+[dict(x,risk_scale=.3) for x in b4],np.concatenate([mult,np.ones(len(b4))]),a,b);dtb=tb.pop('daily');o['trend: all three + bot4']=tb
        # bot 5
        ad=a//1440;bd=min((b//1440) if b else n5,n5);sc=X5.scores(X5p,f5,ad,7);Sm=np.full((n5,len(coins)),np.nan);ci={c:i for i,c in enumerate(coins)};Sm[X5p.day.values,[ci[c] for c in X5p.coin]]=sc
        c5=X5.book(Sm,coins,r1,fund,ad,bd,7,False);o['bot5 alone']=X5.stats(c5)
        rt=np.diff(np.concatenate([[1e4],dtb]))/np.concatenate([[1e4],dtb[:-1]]);rx=np.diff(np.concatenate([[1e4],c5]))/np.concatenate([[1e4],c5[:-1]]);m=min(len(rt),len(rx))
        o['everything (trend + bot5 x0.5)']=X5.stats(1e4*np.cumprod(1+rt[:m]+.5*rx[:m]))
        res[fn]=o;print(f'fold {fn}: base {base["final"]:,.0f} / {base["dd"]:.1f} / {base["calmar"]:.2f}',flush=True)
        for k,v in o.items():
            if k!='base':print(f'   {k:32s} final {v["final"]:>9,.0f} DD {v["dd"]:6.1f} Calmar {v["calmar"]:5.2f}{" PASS" if v.get("pass") else ""}',flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
