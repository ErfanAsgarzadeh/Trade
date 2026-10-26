"""Risk mix check (after the S-variant run): does bot 5 lower the drawdown when the TOTAL risk is kept similar? Continuous
2023-01..2026-10, trend bots scaled by k (returns scaled linearly - an approximation of lower per-trade risk) + bot 5 (S0) at a."""
import sys,json,warnings;warnings.filterwarnings('ignore')
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import xsec_bot5 as X5, contrarian_bot as CB, ml_walkforward as WF, win_prob_model as W, five_year_report as FY
X,feats,coins,r1,fund,n=X5.panel();trend=[dict(l) for l in FY.ledgers('soft')]+CB.g2_legs();rx=[]
for fn,(am,bm) in WF.FOLDS.items():
    a=am//1440;b=min((bm//1440) if bm else n,n);sc=X5.scores(X,feats,a,7);S=np.full((n,len(coins)),np.nan);ci={c:i for i,c in enumerate(coins)};S[X.day.values,[ci[c] for c in X.coin]]=sc
    c=X5.book(S,coins,r1,fund,a,b,7,False);rx.append(np.diff(np.concatenate([[1e4],c]))/np.concatenate([[1e4],c[:-1]]))
rx=np.concatenate(rx);r=W.run_period(trend,[1.]*len(trend),WF.FOLDS['2023'][0]);d=r.pop('daily');rt=np.diff(np.concatenate([[1e4],d]))/np.concatenate([[1e4],d[:-1]]);m=min(len(rx),len(rt));out={}
for k in (1.,.9,.8,.7):
    for a in (0.,.5,1.):
        s=X5.stats(1e4*np.cumprod(1+k*rt[:m]+a*rx[:m]));out[f'trend x{k} + bot5 x{a}']=s;print(f'trend x{k:.1f} + bot5 x{a:.1f}: final {s["final"]:>11,.0f} CAGR {s["cagr"]:6.1f}% DD {s["dd"]:6.1f}% Calmar {s["calmar"]:5.2f}',flush=True)
(X5.OUT/'risk_mix.json').write_text(json.dumps(out,indent=1))
