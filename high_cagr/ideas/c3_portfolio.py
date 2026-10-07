"""C3 coin count and bot + C3 allocation. Written and committed BEFORE running.

Universe for C3: the 30 tested coins that the bot does not trade (NEW10 + HOLD10 + HOLD2); the bot's 5 coins are
excluded so the two strategies never hold the same symbol on one account.
All choices are made on TRAIN (2021-10-05..2024-12-31) only; VALIDATION (2025-01-01..2026-10-04) is reported.
PART 1 - number of coins: rank the 30 coins by C3 TRAIN profit, take the top N for N in 5,10,15,20,25,30.
   (a) fixed 0.25% risk per trade, (b) same total budget: per-trade risk = 2.5% / N.
PART 2 - allocation. Daily mark-to-market returns scale linearly with per-trade risk, so splitting the account w / 1-w
   with each part at full size is the same as one shared account with risks w x bot and (1-w) x C3; one grid covers both:
   bot risk multiplier mb in {0.5, 0.75, 1, 1.25, 1.5} (x its 0.75% per trade), C3 per-trade risk rc in
   {0, .1, .15, .2, .25, .3, .4, .5}%, C3 coin set N in {10, 15, 20, 30} (top-N by train), C3 concurrent-position cap
   K in {none, 8, 5, 3} (first-come by entry time; a skipped trade does not free the coin earlier - approximation).
   PICK = highest TRAIN CAGR with TRAIN max DD <= 20%. Also reported: highest TRAIN Calmar.
   Margin check for the pick: peak combined notional / equity (bot + C3), must stay <= 3x (= 60% margin at 5x).
"""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import ltf_search as L, mtf_search as M, xuni as X, holdout_test as H, orb_intraday as oi, bench, htf_confirm as hc
COINS=X.NEW+H.H10+H.H2;SPLIT=X.SPLIT

def c3_trades(s,days):
    p=np.load(X.PREP/s/'prices.npy');f=np.load(X.PREP/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fc=np.concatenate([[0.],np.cumsum(f)])
    o,h,l,c=L.bars(p,240);sig,atr,adx=L.signals(o,h,l,c);n=len(c);wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    T=M.engine(o,h,l,c,atr,*sig['PULL'],wk,wk,M.EXITS['TRAILW'],.0006,.0002,fc[np.minimum(np.arange(n)*240,len(fc)-1)],300);return T,c

def daily_of(T,c,days):return M.m2m(T,c,240,days) if len(T) else np.zeros(days)

def notional_daily(T,days,bm=240):
    """Open notional per day (fraction of the 1e4 base) from engine rows (qty in col 5, entry in col 6)."""
    out=np.zeros(days)
    for e,x,q,en in zip(T[:,0],T[:,1],T[:,5],T[:,6]):out[int(e*bm//1440):int(x*bm//1440)+1]+=q*en/1e4
    return out

def capped(trades,K):
    """Keep trades first-come by entry bar while fewer than K are open (all coins)."""
    allt=sorted(((T[i,0],T[i,1],s,i) for s,(T,c) in trades.items() for i in range(len(T))))
    open_=[];keep={s:[] for s in trades}
    for e,x,s,i in allt:
        open_=[z for z in open_ if z>e]
        if len(open_)<K:open_.append(x);keep[s].append(i)
    return {s:(trades[s][0][keep[s]],trades[s][1]) for s in trades}

def st(r):return X.stats(r)

def main():
    days=len(np.load(X.PREP/COINS[0]/'prices.npy',mmap_mode='r'))//1440;tr={s:c3_trades(s,days) for s in COINS}
    dly={s:daily_of(*tr[s],days) for s in COINS};rank=sorted(COINS,key=lambda s:-dly[s][:SPLIT].sum())
    res=dict(notes=__doc__,rank=rank,part1=[],part2=[])
    print('coins ranked by C3 TRAIN profit:',[s[:-4] for s in rank],flush=True)
    print('\nPART 1  N coins | (a) 0.25%/trade: train CAGR/DD -> valid CAGR/DD/Calmar | (b) budget 2.5%/N: same')
    for N in (5,10,15,20,25,30):
        r=sum(dly[s] for s in rank[:N]);a=st(r*.5);b=st(r*(2.5/N)/.5)
        res['part1'].append(dict(N=N,fixed=a,budget=b))
        print(f"  N={N:2d} | (a) {a['train'][1]:5.1f}%/{a['train'][2]:4.1f}% -> {a['oos'][1]:5.1f}%/{a['oos'][2]:4.1f}% Calmar {a['oos'][0]:.2f} | (b) {b['train'][1]:5.1f}%/{b['train'][2]:4.1f}% -> {b['oos'][1]:5.1f}%/{b['oos'][2]:4.1f}% Calmar {b['oos'][0]:.2f}",flush=True)
    bot=oi.bot_daily(days)
    ctx=bench.load();(a_,bt,cv),_,_=bench._sim(hc.build(ctx,None),'full',2)
    bot_not=np.zeros(days)
    for r_ in bt:
        e=int((r_[1]-rs.START)//86400000);x=int((r_[2]-rs.START)//86400000);bot_not[e:x+1]+=r_[5]*r_[4]/max(r_[14],1)   # qty*entry / equity at entry
    sets={}
    for N in (10,15,20,30):
        for K in (None,8,5,3):
            t=tr if K is None else capped({s:tr[s] for s in rank[:N]},K)
            t={s:t[s] for s in rank[:N]};sets[(N,K)]=(sum(daily_of(*t[s],days) for s in t),sum(notional_daily(t[s][0],days) for s in t))
    for mb,rc,(N,K) in itertools.product((.5,.75,1.,1.25,1.5),(0,.001,.0015,.002,.0025,.003,.004,.005),sets):
        if rc==0 and (N,K)!=(10,None):continue
        r=bot*mb+sets[(N,K)][0]*(rc/.005);s_=st(r);peak=float(np.max(bot_not*mb+sets[(N,K)][1]*(rc/.005)))
        res['part2'].append(dict(mb=mb,rc=rc,N=N,K=K or 0,train=s_['train'],oos=s_['oos'],full=s_['full'],peak_notional=peak))
    P=pd.DataFrame([dict(mb=x['mb'],rc=x['rc'],N=x['N'] if x['rc'] else 0,K=x['K'],tr_cagr=x['train'][1],tr_dd=x['train'][2],tr_cal=x['train'][0],va_cagr=x['oos'][1],va_dd=x['oos'][2],va_cal=x['oos'][0],
                       fu_cagr=x['full'][1],fu_dd=x['full'][2],fu_cal=x['full'][0],peak=x['peak_notional']) for x in res['part2']])
    P.to_csv(X.OUT/'c3_portfolio_grid.csv',index=False)
    ok=P[P.tr_dd<=20];pick=ok.sort_values('tr_cagr',ascending=False).iloc[0];cal=P.sort_values('tr_cal',ascending=False).iloc[0]
    base=P[(P.mb==1)&(P.rc==0)].iloc[0];cur=P[(P.mb==1)&(P.rc==.0025)&(P.N==10)&(P.K==0)].iloc[0]
    fmt=lambda x,lab:print(f"  {lab:34s} bot x{x.mb:.2f}, C3 {x.rc*100:.2f}%/trade N={int(x.N)} cap={int(x.K) or '-'} | TRAIN {x.tr_cagr:5.1f}% DD {x.tr_dd:4.1f}% | VALID {x.va_cagr:5.1f}% DD {x.va_dd:4.1f}% Calmar {x.va_cal:.2f} | FULL {x.fu_cagr:5.1f}% DD {x.fu_dd:4.1f}% | peak notional {x.peak:.2f}x")
    print('\nPART 2')
    fmt(base,'bot alone');fmt(cur,'current (bot + C3 0.25% on 10)');fmt(pick,'PICK: max train CAGR, train DD<=20%');fmt(cal,'max train Calmar')
    for dd in (15,25,30):
        q=P[P.tr_dd<=dd].sort_values('tr_cagr',ascending=False).iloc[0];fmt(q,f'max train CAGR, train DD<={dd}%')
    res['pick']=pick.to_dict();res['max_calmar']=cal.to_dict()
    (X.OUT/'c3_portfolio.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
