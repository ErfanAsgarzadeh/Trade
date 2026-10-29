"""AI cross-sectional strategy ('fourth bot'), developed with a held-out final test. PROTOCOL (fixed before any run):
  DEVELOPMENT folds 2023 and 2024 only (train = days whose 7-day target ended before the fold). Any number of the variants
  below may be compared there; the one with the best average combined Calmar that passes both dev folds is selected.
  FINAL TEST 2025-01..2026-10 is run ONCE for the selected variant (python ml_xsec2.py final <variant>) and reported as is.
SIGNAL: ensemble of ridge (alpha 10) + gradient boosting (depth 4, 300 trees, lr 0.03, min leaf 200), trained on EVERY day
  (7x the earlier weekly rows), target = cross-sectional rank of the next-7-day return; features = ml_xsec.build() (28 ranked
  criteria + market context). Score = average of the two models' daily cross-sectional ranks.
PORTFOLIO (daily marked, costs 0.16% per unit of turnover, daily funding on every leg):
  V1  weekly, long top 5 / short bottom 5, equal weight, 50% / 50%                      (the earlier LS5)
  V2  weekly, top 8 / bottom 8, inverse-30d-vol weights, 50% / 50%
  V3  V2 + trend gate: a long needs close > EMA50(daily), a short needs close < EMA50; empty slots stay in cash
  V4  V3, but each week only half of the book is moved toward the new target (halves turnover, ~2-week holding)
  V5  V4 + BTC regime tilt: 70% long / 30% short when BTC > its EMA200, else 30% / 70% (gross 100%)
COMBINED with the three bots on one account: daily return = bots + a x strategy (a = 0.5 and 1.0 of equity gross).
PASS (dev): strategy profit > 0 in both dev folds AND combined Calmar > bots alone with max DD not worse by > 2 pp in both.
"""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_xsec as XS, ml_walkforward as WF, win_prob_model as W, five_year_report as FY
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/ml_xsec2';COST=.0016
DEV={'2023':XS.FOLDS['2023'],'2024':XS.FOLDS['2024']};FINAL={'2025-26':XS.FOLDS['2025-26']}
VARIANTS={'V1':dict(n=5,ivol=False,gate=False,blend=1.,tilt=False),'V2':dict(n=8,ivol=True,gate=False,blend=1.,tilt=False),
          'V3':dict(n=8,ivol=True,gate=True,blend=1.,tilt=False),'V4':dict(n=8,ivol=True,gate=True,blend=.5,tilt=False),
          'V5':dict(n=8,ivol=True,gate=True,blend=.5,tilt=True)}

_cache={}
def panel():
    if 'p' in _cache:return _cache['p']
    X,feats,D,n=XS.build();X=X[X.day>=XS.WARM].reset_index(drop=True);coins=XS.COINS
    c=np.stack([D[s]['c'][:n] for s in coins],1);lc=np.log(c);r1=np.vstack([np.diff(lc,axis=0),np.full((1,len(coins)),np.nan)])   # r1[d] = return d -> d+1
    fc=np.stack([D[s]['fcum'][:n] for s in coins],1);fund=np.vstack([np.diff(fc,axis=0),np.zeros((1,len(coins)))])
    ema=pd.DataFrame(c).ewm(span=50,adjust=False).mean().to_numpy();up=c>ema
    vol=pd.DataFrame(np.vstack([np.full((1,len(coins)),np.nan),np.diff(lc,axis=0)])).rolling(30).std().to_numpy()
    b=c[:,coins.index('BTCUSDT')];bull=b>pd.Series(b).ewm(span=200,adjust=False).mean().to_numpy()
    _cache['p']=(X,feats,coins,r1,fund,up,vol,bull,n);return _cache['p']

def scores(X,feats,a):
    tr=(X.day+XS.REB<a)&X.y.notna();Tr=X[tr];med=Tr[feats].median();A=X[feats].fillna(med)
    out=np.zeros(len(X))
    for mk in (lambda:Ridge(alpha=10.),lambda:HistGradientBoostingRegressor(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=200,random_state=0)):
        p=mk().fit(Tr[feats].fillna(med),Tr.yr).predict(A);out+=pd.Series(p).groupby(X.day.values).rank(pct=True).to_numpy()
    return out/2

def run(v,S,coins,r1,fund,up,vol,bull,a,b):
    cfg=VARIANTS[v];nc=len(coins);w=np.zeros(nc);eq=10000.;curve=[]
    for d in range(a,b-1):
        if (d-a)%XS.REB==0:
            s=S[d];ok=np.isfinite(s);tgt=np.zeros(nc);order=np.argsort(np.where(ok,s,np.nan))
            valid=[i for i in order if ok[i]];longs=valid[-cfg['n']:];shorts=valid[:cfg['n']]
            if cfg['gate']:longs=[i for i in longs if up[d,i]];shorts=[i for i in shorts if not up[d,i]]
            gl,gs=(.7,.3) if (cfg['tilt'] and bull[d]) else ((.3,.7) if cfg['tilt'] else (.5,.5))
            for side,names,g in ((1,longs,gl),(-1,shorts,gs)):
                if not names:continue
                wt=np.array([1/vol[d,i] if (cfg['ivol'] and vol[d,i]>0) else 1. for i in names]);wt=wt/wt.sum()*g*(len(names)/cfg['n'])
                for i,x in zip(names,wt):tgt[i]=side*x
            new=w+cfg['blend']*(tgt-w);eq*=1-COST/2*np.abs(new-w).sum();w=new
        rr=np.nan_to_num(np.exp(r1[d])-1);eq*=1+(w*rr).sum()-(w*fund[d]).sum();w=w*(1+rr)/max(1+(w*rr).sum(),1e-9) if False else w;curve.append(eq)
    c=np.array(curve);return c

def stats(c):
    yrs=len(c)/365.25;dd=(c/np.maximum.accumulate(c)-1).min()*100;cagr=((c[-1]/10000)**(1/yrs)-1)*100;return dict(final=float(c[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else 0.)

def bots_curve(a,b):
    L=FY.ledgers('soft');r=W.run_period(L,[1.]*len(L),a*1440,b*1440 if b*1440<(FY.DAYS*1440) else None);return r['daily']

def evaluate(folds,variants,tag):
    X,feats,coins,r1,fund,up,vol,bull,n=panel();res={}
    for fn,(a,b) in folds.items():
        b=min(b,n);sc=scores(X,feats,a);S=np.full((n,len(coins)),np.nan);ci={c:i for i,c in enumerate(coins)}
        S[X.day.values,[ci[c] for c in X.coin]]=sc
        te=(X.day>=a)&(X.day<b-XS.REB)&X.y.notna();ic=float(X[te].assign(s=sc[te]).groupby('day').apply(lambda g:spearmanr(g.s,g.y)[0]).mean())
        bc=bots_curve(a,b);rb=np.diff(np.concatenate([[10000.],bc]))/np.concatenate([[10000.],bc[:-1]]);bs=stats(bc);out={'ic':ic,'bots':bs}
        print(f'[{tag}] fold {fn}: ensemble daily-trained IC {ic:+.3f} | bots alone final {bs["final"]:,.0f} DD {bs["dd"]:.1f} Calmar {bs["calmar"]:.2f}',flush=True)
        for v in variants:
            c=run(v,S,coins,r1,fund,up,vol,bull,a,b);st=stats(c);rx=np.diff(np.concatenate([[10000.],c]))/np.concatenate([[10000.],c[:-1]]);m=min(len(rx),len(rb));o={'alone':st}
            for al in (.5,1.):
                comb=10000*np.cumprod(1+rb[:m]+al*rx[:m]);cs=stats(comb);cs['pass']=bool(cs['calmar']>bs['calmar'] and cs['dd']>=bs['dd']-2);o[f'comb{al}']=cs
            o['corr_with_bots']=float(np.corrcoef(rb[:m],rx[:m])[0,1]);out[v]=o;np.save(OUT/f'curve_{tag}_{fn}_{v}.npy',c)
            print(f'   {v}: alone final {st["final"]:>8,.0f} CAGR {st["cagr"]:6.1f}% DD {st["dd"]:6.1f}% Calmar {st["calmar"]:5.2f} | corr with bots {o["corr_with_bots"]:+.2f} | '+
                  ' | '.join(f'bots+{al}x {o[f"comb{al}"]["final"]:,.0f} / {o[f"comb{al}"]["dd"]:.1f} / {o[f"comb{al}"]["calmar"]:.2f}{" PASS" if o[f"comb{al}"]["pass"] else ""}' for al in (.5,1.)),flush=True)
        res[fn]=out
    (OUT/f'result_{tag}.json').write_text(json.dumps(res,indent=1,default=float));return res

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>2 and sys.argv[1]=='final':evaluate(FINAL,[sys.argv[2]],'final')
    else:evaluate(DEV,list(VARIANTS),'dev')
