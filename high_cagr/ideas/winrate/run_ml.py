"""Family 2 of PREDECLARED.md: walk-forward XGBoost entry gate for all three bots, shared-account replay."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG, exits as E, ml_gate as G
from high_cagr.ideas import five_year_report as FY

def window_stats(r,a,b):
    """CAGR / max DD / Calmar of the daily equity between day indexes a..b, and trade win rate of entries in it."""
    d=r['daily'];seg=d[a:b];start=d[a-1] if a>0 else FY.SEED;yrs=len(seg)/365.25
    cagr=((seg[-1]/start)**(1/yrs)-1)*100;curve=np.concatenate([[start],seg]);dd=float((1-curve/np.maximum.accumulate(curve)).max()*100)
    t=r['trades'];m=(t.entry_min>=a*1440)&(t.entry_min<b*1440)
    return dict(cagr=float(cagr),dd=dd,calmar=float(cagr/dd),win=float((t.pnl[m]>0).mean()*100),trades=int(m.sum()),
                win_by_bot={k:float((g.pnl>0).mean()*100) for k,g in t[m].groupby('bot')},net=float(t.pnl[m].sum()))

def days(y):return (pd.Timestamp(f'{y}-01-01')-G.START).days

def evaluate(legs,keep):
    r=E.replay_legs([l for l,k in zip(legs,keep) if k])
    A=days(2023);S=days(2025);N=len(r['daily'])
    return dict(w2324=window_stats(r,A,S),w2526=window_stats(r,S,N),full=E.account_stats(r))

def main():
    df=LG.build();legs=LG.raw_legs();assert len(df)==len(legs);y=df.win.to_numpy()
    base=evaluate(legs,np.ones(len(legs),bool));res=dict(baseline=base,variants={})
    print('BASE 23-24',base['w2324'],'\nBASE 25-26',base['w2526'],flush=True)
    variants={'xgb_all':dict(groups=None),'xgb_market':dict(groups=['f_']),'xgb_q20':dict(groups=None,fixed_q=dict(main=.2,c3=.2,pa=.2))}
    for name,kw in variants.items():
        aucs={};seeds=[]
        score,keep,info=G.walk_forward(df,**kw)
        for Y in G.YEARS:
            m=(df.em>=G.ymin(Y))&(df.em<G.ymin(Y+1))&~df.is_add
            aucs[Y]={b:G.auc(y[m&(df.bot==b)],score[m&(df.bot==b)]) for b in ('main','c3','pa')}
        ev=evaluate(legs,keep);ev.update(aucs=aucs,info={str(k):v for k,v in info.items()},dropped=int((~keep).sum()))
        res['variants'][name]=ev
        print(name,'dropped',ev['dropped'],'AUC',json.dumps(aucs),'\n  23-24',ev['w2324'],'\n  25-26',ev['w2526'],'\n  q',info,flush=True)
    (LG.OUT/'ml_gate.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
