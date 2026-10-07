"""Risk sweep: bot (2A+5A, 5 coins) and C3+D (10 coins) trading together. Each strategy re-simulated at every risk
level (bot: kernel_fixes.simulate with its notional caps / 4 slots; C3+D: mode-6 engine with 0.4x notional cap per
position), daily mark-to-market; combined account = sum of the two daily return series (same equity, each sized on it).
Optimum is chosen on TRAIN (2021-10-05..2024-12-31); VALIDATION (2025-01-01..2026-10-04) is reported unchanged.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc, c3bench_d as BD, c3r2_a4_sizing as S, xuni as X, mtf_search as M
B=BD.B;OUT=X.OUT/'risk_sweep';OUT.mkdir(parents=True,exist_ok=True)
BOT_R=[.0025,.005,.0075,.01,.0125,.015,.0175,.02,.025,.03]
C3_R=[.001,.002,.003,.004,.005,.0075,.01,.0125,.015,.02]

def bot_series(r):
    bench.RISK=r;(a,t,curve),_,_=bench._sim(hc.build(bench.load(),None),'full',2);return X.daily_from_curve(curve,B.days())

def c3_series(r):
    out=np.zeros(B.days())
    for s in B.MAIN10:
        d=B.coin(s);le,se=BD.confirm_signals(d);m=np.full(d['n'],r/.005)
        T=S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)[:,:9]
        if len(T):out+=M.m2m(np.asarray(T,float),d['c'],240,B.days())
    return out

def main():
    bot={r:bot_series(r) for r in BOT_R};c3={r:c3_series(r) for r in C3_R}
    chk=np.abs(bot[.0075]-B.bot()).max();print('bot 0.75% vs saved series max abs diff',chk,flush=True)
    rows=[]
    for name,ser in (('bot',bot),('c3',c3)):
        for r,x in ser.items():st=X.stats(x);rows.append(dict(kind=name,bot=r if name=='bot' else 0,c3=r if name=='c3' else 0,**{f'{p}_{m}':st[p][i] for p in st for i,m in enumerate(('cal','cagr','dd'))}))
    for rb in [0]+BOT_R:
        for rc in [0]+C3_R:
            if rb==0 or rc==0:continue
            st=X.stats(bot[rb]+c3[rc]);rows.append(dict(kind='both',bot=rb,c3=rc,**{f'{p}_{m}':st[p][i] for p in st for i,m in enumerate(('cal','cagr','dd'))}))
    P=pd.DataFrame(rows);P.to_csv(OUT/'grid.csv',index=False)
    np.savez(OUT/'series.npz',**{f'bot_{r}':v for r,v in bot.items()},**{f'c3_{r}':v for r,v in c3.items()})
    print(P.round(2).to_string(),flush=True)
if __name__=='__main__':main()

def notional(rb,rc):
    """Peak daily open notional / equity for bot at rb plus C3+D at rc (C3 notional measured on its 1e4 base)."""
    bench.RISK=rb;(a,t,cv),_,_=bench._sim(hc.build(bench.load(),None),'full',2);days=B.days();nb=np.zeros(days)
    from high_cagr import run_suite as rs
    for r_ in t:
        e=int((r_[1]-rs.START)//86400000);x=int((r_[2]-rs.START)//86400000);nb[e:x+1]+=r_[5]*r_[4]/max(r_[14],1)
    nc=np.zeros(days)
    for s in B.MAIN10:
        d=B.coin(s);le,se=BD.confirm_signals(d);m=np.full(d['n'],rc/.005)
        T=S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
        for e,x,q,en in zip(T[:,0],T[:,1],T[:,5],T[:,6]):nc[int(e*240//1440):int(x*240//1440)+1]+=q*en/1e4
    return float(nb.max()),float(nc.max()),float((nb+nc).max()),float(np.percentile(nb+nc,95))
