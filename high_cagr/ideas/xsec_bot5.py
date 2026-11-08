"""Bot 5 = AI market-neutral cross-sectional strategy, strengthened. Pre-declared before running.
Base S0 = ml_xsec2 V1: ridge + gradient boosting trained on every day, target = cross-sectional rank of the next H-day return,
features = ml_xsec.build() (technical + sentiment, ranked across the 35 coins + market context); every H days long the top 5 and
short the bottom 5, equal weight, 50% / 50% of equity; costs 0.16% per unit of turnover, daily funding on every leg.
  S1  S0 + extra features: Fear & Greed 7-day change, stablecoin supply 30-day growth (market context), smart-vs-crowd
      (log top-trader minus log global long/short, ranked)
  S2  S0 with H = 14 (two-week target and rebalance: half the turnover)
  S3  S0 + confidence filter: hold the book only when the cross-sectional std of the scores is in the top half of its last
      26 rebalances; otherwise flat
  S4  S1 + S2 + S3
FOLDS: dev 2023, 2024; 2025-26 reported for comparison (V1 already ran once on it, so it is not independent).
TREND BOTS = three bots + bot 4 (G2 at 0.15%). Combined daily return = trend + a x strategy, a in {0.5, 1.0}.
Selection (dev): the variant with the best average combined Calmar at a = 0.5 among variants profitable alone in both dev years.
Main measure requested: max drawdown of the combined account vs the trend bots alone.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,matplotlib.ticker as mt
from high_cagr.ideas import ml_xsec as XS, contrarian_bot as CB, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, bot4_failures as BF
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/xsec_bot5';COST=.0016
VAR={'S0':dict(extra=False,H=7,conf=False),'S1':dict(extra=True,H=7,conf=False),'S2':dict(extra=False,H=14,conf=False),'S3':dict(extra=False,H=7,conf=True),'S4':dict(extra=True,H=14,conf=True)}

def panel():
    X,feats,D,n=XS.build();coins=XS.COINS;S=pd.Series;sh=lambda x,k:np.concatenate([np.full(k,np.nan),x[:-k]])
    c=np.stack([D[s]['c'][:n] for s in coins],1);lc=np.log(c);fc=np.stack([D[s]['fcum'][:n] for s in coins],1)
    r1=np.vstack([np.diff(lc,axis=0),np.full((1,len(coins)),np.nan)]);fund=np.vstack([np.diff(fc,axis=0),np.zeros((1,len(coins)))])
    y14=np.vstack([lc[14:]-lc[:-14],np.full((14,len(coins)),np.nan)]);ci={s:i for i,s in enumerate(coins)};X['y14']=y14[X.day.values,[ci[s] for s in X.coin]]
    X['yr14']=X.groupby('day').y14.rank(pct=True)
    svc={s:np.log(D[s]['lst'][:n])-np.log(D[s]['lsg'][:n]) for s in coins};X['svc']=np.array([svc[s][d] for s,d in zip(X.coin,X.day)]);X['svc']=X.groupby('day').svc.rank(pct=True)
    import json as js
    from high_cagr import run_suite as rs
    closes=rs.START+(np.arange(n)+1)*86400000
    fd=js.loads((XS.ROOT/'high_cagr/cache_sentiment/fng.json').read_text())['data'];fs=pd.Series({int(x['timestamp'])*1000:float(x['value']) for x in fd}).sort_index()
    st=js.loads((XS.ROOT/'high_cagr/cache_sentiment/stablecoins.json').read_text());ss=pd.Series({int(x['date'])*1000:float(x['totalCirculatingUSD']['peggedUSD']) for x in st}).sort_index()
    asof=lambda ser:np.where((ix:=np.searchsorted(ser.index.to_numpy(),closes-86400000,side='right')-1)>=0,ser.to_numpy()[np.maximum(ix,0)],np.nan)
    f=asof(fs);sg=asof(ss);mk=pd.DataFrame(dict(day=np.arange(n),fng7=f-sh(f,7),stab30=sg/sh(sg,30)-1));X=X.merge(mk,on='day',how='left')
    X=X[X.day>=XS.WARM].reset_index(drop=True);return X,feats,coins,r1,fund,n

def scores(X,feats,a,H):
    yt,yc=('yr','y') if H==7 else ('yr14','y14');tr=(X.day+H<a)&X[yc].notna();Tr=X[tr];med=Tr[feats].median();A=X[feats].fillna(med);out=np.zeros(len(X))
    for mk in (lambda:Ridge(alpha=10.),lambda:HistGradientBoostingRegressor(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=200,random_state=0)):
        p=mk().fit(Tr[feats].fillna(med),Tr[yt]).predict(A);out+=pd.Series(p).groupby(X.day.values).rank(pct=True).to_numpy()
    return out/2

def book(S,coins,r1,fund,a,b,H,conf):
    nc=len(coins);w=np.zeros(nc);eq=1e4;curve=[];disp=[]
    for d in range(a,b-1):
        if (d-a)%H==0:
            s=S[d];ok=np.isfinite(s);tgt=np.zeros(nc)
            if ok.sum()>=10:
                o=[i for i in np.argsort(np.where(ok,s,np.nan)) if ok[i]];dv=np.nanstd(s[ok]);disp.append(dv)
                active=(not conf) or len(disp)<8 or dv>=np.median(disp[-26:])
                if active:
                    for i in o[-5:]:tgt[i]=.1
                    for i in o[:5]:tgt[i]=-.1
            eq*=1-COST/2*np.abs(tgt-w).sum();w=tgt
        rr=np.nan_to_num(np.exp(r1[d])-1);eq*=1+(w*rr).sum()-(w*fund[d]).sum();curve.append(eq)
    return np.array(curve)

def stats(c):
    yrs=len(c)/365.25;dd=(c/np.maximum.accumulate(c)-1).min()*100;cagr=((c[-1]/1e4)**(1/yrs)-1)*100;return dict(final=float(c[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else 0.)

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();X,base_feats,coins,r1,fund,n=panel();trend=[dict(l) for l in FY.ledgers('soft')]+CB.g2_legs();res={};curves={}
    print('panel',X.shape,round(time.time()-t0),'s',flush=True)
    for fn,(am,bm) in WF.FOLDS.items():
        a=am//1440;b=min((bm//1440) if bm else n,n);tr_=W.run_period(trend,[1.]*len(trend),am,bm);dt=tr_.pop('daily');rt=np.diff(np.concatenate([[1e4],dt]))/np.concatenate([[1e4],dt[:-1]])
        out={'trend':tr_};print(f'fold {fn}{" (comparison only)" if fn=="2025-26" else ""}: trend bots final {tr_["final"]:,.0f} DD {tr_["dd"]:.1f} Calmar {tr_["calmar"]:.2f}',flush=True)
        for v,cfg in VAR.items():
            feats=base_feats+(['fng7','stab30','svc'] if cfg['extra'] else []);sc=scores(X,feats,a,cfg['H'])
            S=np.full((n,len(coins)),np.nan);ci={c:i for i,c in enumerate(coins)};S[X.day.values,[ci[c] for c in X.coin]]=sc
            yc='y' if cfg['H']==7 else 'y14';te=(X.day>=a)&(X.day<b-cfg['H'])&X[yc].notna()&(((X.day-a)%cfg['H'])==0)
            ic=float(X[te].assign(s=sc[te]).groupby('day').apply(lambda g:spearmanr(g.s,g[yc])[0]).mean())
            c=book(S,coins,r1,fund,a,b,cfg['H'],cfg['conf']);st=stats(c);rx=np.diff(np.concatenate([[1e4],c]))/np.concatenate([[1e4],c[:-1]]);m=min(len(rx),len(rt));o={'ic':ic,'alone':st,'corr':float(np.corrcoef(rx[:m],rt[:m])[0,1])}
            mo=BF.monthly(c,a);o.update(pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()))
            for al in (.5,1.):
                cb=1e4*np.cumprod(1+rt[:m]+al*rx[:m]);o[f'comb{al}']=stats(cb)
            curves[(fn,v)]=rx;out[v]=o
            print(f'  {v}: IC {ic:+.3f} | alone {st["final"]:>8,.0f} CAGR {st["cagr"]:6.1f}% DD {st["dd"]:6.1f}% months+ {o["pos"]:3.0f}% | corr {o["corr"]:+.2f} | trend+0.5x {o["comb0.5"]["final"]:>9,.0f} DD {o["comb0.5"]["dd"]:6.1f} Calmar {o["comb0.5"]["calmar"]:5.2f} | trend+1.0x {o["comb1.0"]["final"]:>9,.0f} DD {o["comb1.0"]["dd"]:6.1f} Calmar {o["comb1.0"]["calmar"]:5.2f}',flush=True)
        res[fn]=out
    ok=[v for v in VAR if all(res[f][v]['alone']['final']>1e4 for f in ('2023','2024'))];best=max(ok,key=lambda v:np.mean([res[f][v]['comb0.5']['calmar'] for f in ('2023','2024')])) if ok else 'S0'
    res['eligible']=ok;res['selected']=best;print('eligible:',ok,'selected:',best,flush=True)
    # continuous 2023..2026 chart: trend bots vs trend + selected (0.5x, 1.0x); each year's scores from that year's model
    a0=WF.FOLDS['2023'][0];tr_=W.run_period(trend,[1.]*len(trend),a0);dt=tr_.pop('daily');rt=np.diff(np.concatenate([[1e4],dt]))/np.concatenate([[1e4],dt[:-1]])
    rx=np.concatenate([curves[(f,best)] for f in WF.FOLDS]);m=min(len(rx),len(rt));x=pd.date_range('2023-01-01',periods=m)
    lines={'Trend bots (3 bots + bot 4)':1e4*np.cumprod(1+rt[:m]),f'Trend bots + bot 5 ({best}) at 50%':1e4*np.cumprod(1+rt[:m]+.5*rx[:m]),f'Trend bots + bot 5 ({best}) at 100%':1e4*np.cumprod(1+rt[:m]+rx[:m]),f'Bot 5 ({best}) alone':1e4*np.cumprod(1+rx[:m])}
    res['continuous']={k:stats(v) for k,v in lines.items()}
    cols=['#6b7280','#2563eb','#0d9488','#d97706'];fig,(ax,ax2)=plt.subplots(2,1,figsize=(11,7.5),sharex=True,gridspec_kw=dict(height_ratios=[3,1.4]))
    for (k,v),cl in zip(lines.items(),cols):
        s_=stats(v);ax.plot(x,v,color=cl,lw=1.9 if 'alone' not in k else 1.3,label=f'{k}: ${v[-1]:,.0f}  (max DD {s_["dd"]:.1f}%)');ax2.plot(x,(v/np.maximum.accumulate(v)-1)*100,color=cl,lw=1.1)
    ax.set_yscale('log');ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v_,_:f'${v_/1000:,.0f}k'));ax.legend(frameon=False,loc='upper left',fontsize=9);ax.grid(alpha=.3);ax2.grid(alpha=.3)
    ax.set_title('One $10,000 account, 2023-01-01 .. 2026-10-04: trend bots with and without the AI market-neutral bot 5',loc='left',fontsize=11,fontweight='bold');ax2.set_ylabel('drawdown %');ax2.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    for a_ in (ax,ax2):a_.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(OUT/'bot5_with_trend_2023_2026.png',dpi=130)
    for k,v in res['continuous'].items():print(f'continuous {k:45s} final {v["final"]:>10,.0f} CAGR {v["cagr"]:6.1f}% DD {v["dd"]:6.1f}% Calmar {v["calmar"]:5.2f}',flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
