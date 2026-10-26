"""Cross-sectional ML ranking of the 35 coins (daily data, weekly rebalance), pre-declared before any result was seen.
FEATURES per coin and day (data up to that day's close; then ranked across coins, 0..1): vol-scaled returns over 1/3/7/14/30/60/90
days, realised vol 7/30, distance to EMA50/EMA200 (vol units), drawdown from the 90-day high, 30-day skew, volume trend (7d vs
90d), taker buy share 7d/30d, open interest change 7/30d, global and top-trader long/short ratio (level, 7d change), funding 7d,
60-day correlation and beta to BTC; market context (not ranked): BTC 30d return, breadth (share above EMA50), Fear & Greed.
TARGET: cross-sectional rank of the next-7-day return. Rebalance every 7 days at the daily close.
MODELS: ridge (alpha 10) and gradient boosting (depth 4, 300 trees, lr 0.03, min leaf 200); baselines: 30-day momentum rank, and
the equal-weight basket. WALK-FORWARD: test 2023, 2024, 2025-01..2026-10; train = weeks whose target ended before the test start.
USES (judged on every fold):
 A) stand-alone portfolios, costs 0.16% per unit of turnover (fee + slippage), funding on each leg:
    LS5  long the top 5, short the bottom 5, 50% / 50% of equity (market neutral)     LO5  long the top 5, 100% of equity
    benchmarks: equal-weight long all 35 (EW), BTC buy and hold
 B) overlay on the three bots (deployed ledger, same replay engine): each entry's risk x multiplier from the coin's latest score,
    side-adjusted (pct for longs, 1-pct for shorts): size (0.5 + pct), skip20 (no entry when pct < 0.2)
Pass for B = Calmar above the current bots AND max DD not worse by more than 2 pp, in every fold.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_short as MS, ml_walkforward as WF, win_prob_model as W, five_year_report as FY
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/ml_xsec';COST=.0016;REB=7;WARM=200
COINS=MS.COINS;START=pd.Timestamp('2021-10-05')
FOLDS={k:(a//1440,b//1440) for k,(a,b) in MS.FOLDS.items()}

def daily(s):
    b=MS.base15(s);n=len(b['c'])//96;r=lambda x:x[:n*96].reshape(n,96)
    return dict(c=r(b['c'])[:,-1],h=r(b['h']).max(1),l=r(b['l']).min(1),v=r(b['v']).sum(1),tb=r(b['tb']).sum(1),oi=r(b['oi'])[:,-1],lsg=r(b['lsg'])[:,-1],lst=r(b['lst'])[:,-1],fcum=r(b['fcum'])[:,-1])

def build():
    D={s:daily(s) for s in COINS};n=min(len(D[s]['c']) for s in COINS);S=pd.Series;sh=lambda x,k:np.concatenate([np.full(k,np.nan),x[:-k]])
    btc=np.log(D['BTCUSDT']['c'][:n]);rb=np.diff(btc,prepend=np.nan);rows=[]
    above=np.mean([D[s]['c'][:n]>S(D[s]['c'][:n]).ewm(span=50,adjust=False).mean().to_numpy() for s in COINS],0)
    import json as js
    fd=js.loads((MS.CACHE/'fng.json').read_text())['data'];fs=pd.Series({int(x['timestamp'])*1000:float(x['value']) for x in fd}).sort_index()
    from high_cagr import run_suite as rs
    closes=rs.START+(np.arange(n)+1)*86400000;ix=np.searchsorted(fs.index.to_numpy(),closes-86400000,side='right')-1;fng=np.where(ix>=0,fs.to_numpy()[np.maximum(ix,0)],np.nan)
    for s in COINS:
        d=D[s];c=d['c'][:n];lc=np.log(c);r1=np.diff(lc,prepend=np.nan);F={}
        v30=S(r1).rolling(30).std().to_numpy()+1e-9
        for k in (1,3,7,14,30,60,90):F[f'r{k}']=(lc-sh(lc,k))/(v30*np.sqrt(k))
        F['vol7']=S(r1).rolling(7).std().to_numpy();F['vol30']=v30
        F['ema50']=(lc-np.log(S(c).ewm(span=50,adjust=False).mean().to_numpy()))/v30;F['ema200']=(lc-np.log(S(c).ewm(span=200,adjust=False).mean().to_numpy()))/v30
        F['dd90']=c/S(d['h'][:n]).rolling(90).max().to_numpy()-1;F['skew30']=S(r1).rolling(30).skew().to_numpy()
        v=d['v'][:n];F['vtrend']=np.log((S(v).rolling(7).mean().to_numpy()+1)/(S(v).rolling(90).mean().to_numpy()+1))
        tb=d['tb'][:n];F['tb7']=S(tb).rolling(7).sum().to_numpy()/np.maximum(S(v).rolling(7).sum().to_numpy(),1e-9);F['tb30']=S(tb).rolling(30).sum().to_numpy()/np.maximum(S(v).rolling(30).sum().to_numpy(),1e-9)
        oi=d['oi'][:n];F['oi7']=oi/sh(oi,7)-1;F['oi30']=oi/sh(oi,30)-1
        F['lsg']=np.log(d['lsg'][:n]);F['lst']=np.log(d['lst'][:n]);F['lsg7']=F['lsg']-sh(F['lsg'],7);F['lst7']=F['lst']-sh(F['lst'],7)
        fc=d['fcum'][:n];F['fund7']=(fc-sh(fc,7))*1e3
        F['corr60']=S(r1).rolling(60).corr(S(rb)).to_numpy();F['beta60']=S(r1).rolling(60).cov(S(rb)).to_numpy()/(S(rb).rolling(60).var().to_numpy()+1e-12)
        F['y']=np.concatenate([lc[REB:]-lc[:-REB],np.full(REB,np.nan)]);F['ret1']=np.concatenate([r1[1:],[np.nan]])   # next-day return for daily marking
        F['fnext']=np.concatenate([fc[REB:]-fc[:-REB],np.full(REB,np.nan)])
        F['coin']=s;F['day']=np.arange(n);rows.append(pd.DataFrame(F))
    X=pd.concat(rows,ignore_index=True).replace([np.inf,-np.inf],np.nan)
    feats=[c for c in X.columns if c not in ('coin','day','y','ret1','fnext')]
    for f in feats:X[f]=X.groupby('day')[f].rank(pct=True)
    mk=pd.DataFrame(dict(day=np.arange(n),btc30=btc-sh(btc,30),breadth=above,fng=fng/100));X=X.merge(mk,on='day')
    X['yr']=X.groupby('day').y.rank(pct=True);return X,feats+['btc30','breadth','fng'],D,n

def portfolio(X,score,a,b,kind):
    """weekly rebalance on days a+0, a+7, ...; daily marked. returns daily equity array and stats."""
    days=list(range(a,b-REB,REB));eq=10000.;curve=[];prev_w={};
    for d0 in days:
        g=X[(X.day==d0)].dropna(subset=[score])
        if kind=='EW':w={c:1/len(g) for c in g.coin}
        elif kind=='BTC':w={'BTCUSDT':1.}
        else:
            g=g.sort_values(score);top=list(g.coin.tail(5));bot=list(g.coin.head(5))
            w={c:(.5/5 if kind=='LS5' else 1/5) for c in top}
            if kind=='LS5':w.update({c:-.5/5 for c in bot})
        turn=sum(abs(w.get(c,0)-prev_w.get(c,0)) for c in set(w)|set(prev_w));eq*=(1-COST/2*turn*1.)   # cost per unit traded (one side = half round trip)
        prev_w=w;W_=X[(X.day>=d0)&(X.day<d0+REB)]
        for d in range(d0,d0+REB):
            day=W_[W_.day==d].set_index('coin');r=sum(wt*(np.exp(day.ret1.get(c,0.) if np.isfinite(day.ret1.get(c,np.nan)) else 1.)-1) for c,wt in w.items())
            eq*=(1+r);curve.append(eq)
        fund=X[(X.day==d0)].set_index('coin').fnext;eq*=(1-sum(wt*(fund.get(c,0.) if np.isfinite(fund.get(c,np.nan)) else 0.) for c,wt in w.items()));curve[-1]=eq
    c=np.array(curve);yrs=len(c)/365.25;dd=(c/np.maximum.accumulate(c)-1).min()*100;cagr=((c[-1]/10000)**(1/yrs)-1)*100
    return dict(final=float(c[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else 0.),c

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();X,feats,D,n=build();print('panel',X.shape,'built',round(time.time()-t0),'s',flush=True)
    X=X[X.day>=WARM].reset_index(drop=True);L=FY.ledgers('soft');res={}
    for fn,(a,b) in FOLDS.items():
        tr=(X.day+REB<a)&X.y.notna()&(((X.day-WARM)%REB)==0);Tr=X[tr];med=Tr[feats].median()
        sc={}
        for mname,mk in {'ridge':lambda:Ridge(alpha=10.),'gbm':lambda:HistGradientBoostingRegressor(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=200,random_state=0)}.items():
            m=mk().fit(Tr[feats].fillna(med),Tr.yr);X[f's_{mname}']=m.predict(X[feats].fillna(med))
        X['s_mom']=X['r30'];out={}
        te=(X.day>=a)&(X.day<b-REB)&(((X.day-a)%REB)==0)&X.y.notna()
        for s in ('s_ridge','s_gbm','s_mom'):
            ic=X[te].groupby('day').apply(lambda g:spearmanr(g[s],g.y)[0]).mean();o={'ic':float(ic)}
            for kind in ('LS5','LO5'):
                r,c=portfolio(X,s,a,b,kind);o[kind]=r;np.save(OUT/f'curve_{fn}_{s}_{kind}.npy',c)
            out[s]=o
            print(f'{fn:7s} {s:8s} weekly IC {ic:+.3f} | LS5 final {o["LS5"]["final"]:>9,.0f} CAGR {o["LS5"]["cagr"]:6.1f}% DD {o["LS5"]["dd"]:6.1f}% | LO5 final {o["LO5"]["final"]:>9,.0f} CAGR {o["LO5"]["cagr"]:6.1f}% DD {o["LO5"]["dd"]:6.1f}%',flush=True)
        for kind in ('EW','BTC'):
            r,c=portfolio(X,'s_mom',a,b,kind);out[kind]=r;print(f'{fn:7s} {kind:8s} final {r["final"]:>9,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}%',flush=True)
        # B) overlay on the bots: latest weekly score at or before the entry day
        base=WF.replay(L,a*1440,(b*1440) if fn!='2025-26' else None);out['bots_base']=base
        for s in ('s_ridge','s_gbm','s_mom'):
            P=X[((X.day-WARM)%REB)==0].pivot(index='day',columns='coin',values=s);P['pct']=0
            P=P.drop(columns='pct').rank(axis=1,pct=True);idx=P.index.to_numpy()
            def pct_for(l):
                d=l['em']//1440;k=np.searchsorted(idx,d,side='right')-1
                if k<0:return .5
                v=P.iloc[k].get(l['coin'],np.nan);v=.5 if not np.isfinite(v) else v;return v if l['side']>0 else 1-v
            pc=np.array([pct_for(l) for l in L]);o={}
            for scn,mult in {'size':.5+pc,'skip20':(pc>=.2).astype(float)}.items():
                r=W.run_period(L,mult,a*1440,(b*1440) if fn!='2025-26' else None);r.pop('daily');r['pass']=WF.judge(r,base);o[scn]=r
                print(f'{fn:7s} bots+{s:8s} {scn:7s} final {r["final"]:>9,.0f} DD {r["dd"]:6.1f} Calmar {r["calmar"]:5.2f} {"PASS" if r["pass"] else ""} (base {base["final"]:,.0f} / {base["dd"]:.1f} / {base["calmar"]:.2f})',flush=True)
            out[f'bots_{s}']=o
        res[fn]=out
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
