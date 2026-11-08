"""Coin lists by a STRUCTURAL rule (liquidity), because picking coins by past bot results did not carry over
(universe_select.carry_over: train-picked and train-rejected coins have the same validation R per trade).

Rule: rank eligible coins by median daily USDT volume (Binance 1m volume x close) over the 12 months before the decision
date; a coin is eligible if it has >= 12 months of history at the decision date and is a crypto asset (PAXG excluded:
gold token). Most liquid N_MAIN -> Shahin, next N_C3 -> Mojsavar, the rest -> Ghoghnous (one bot per coin).
HONEST test: decision date 2025-01-01 (2024 volume only), judged on the 2025-26 validation part of the shared-account
replay, against the current lists (TTT subset) and against RANDOM disjoint allocations of the same sizes from the same pool.
DEPLOY list: the same rule with the latest 12 months (2025-10-05 .. 2026-10-04).
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import universe_eval as U, universe_select as US, ledger as LG, prepare_ttt as PT
from high_cagr.ideas import xuni as X
EXCLUDE={'PAXGUSDT'};SIZES={'8/15/rest':(8,15),'5/10/20':(5,10,20),'6/12/rest':(6,12)};N_RANDOM=30
DAY=1440

def daily_usd_volume(s):
    p=np.load(X.PREP/s/'prices.npy',mmap_mode='r');v=np.load(X.PREP/s/'vol1m.npy',mmap_mode='r');n=len(v)//DAY*DAY
    return (np.asarray(v[:n],np.float64)*np.asarray(p[:n,3],np.float64)).reshape(-1,DAY).sum(1)

def ranking(end_day):
    rows=[]
    for s in U.coins():
        if s in EXCLUDE:continue
        if PT.listed_min(s)//DAY>end_day-365:continue
        dv=daily_usd_volume(s)[max(0,end_day-365):end_day];rows.append((s,float(np.median(dv))))
    return sorted(rows,key=lambda r:-r[1])

def allocate(order,sizes):
    a=sizes[0];b=a+sizes[1];c=b+sizes[2] if len(sizes)>2 else len(order)
    return dict(main=order[:a],c3=order[a:b],pa=order[b:c])

def main():
    legs={b:U.legs(b) for b in ('main','c3','pa')};split=LG.SPLIT_MIN//DAY;last=len(daily_usd_volume('BTCUSDT'))
    rank24=ranking(split);rankNow=ranking(last);res=dict(rank_2024=rank24,rank_latest=rankNow,runs={})
    cur={b:[s for s in v if s in legs[b]] for b,v in US.CURRENT.items()}
    def run(name,lists):
        st,_=US.account(legs,lists);res['runs'][name]=dict(lists=lists,**st)
        print(f"{name:28s}",{b:len(v) for b,v in lists.items()},f"WR {st['win_rate']['all']:.1f} va {st['win_rate']['valid']:.1f} | Calmar tr {st['train'][0]:.2f} va {st['valid'][0]:.2f} | CAGR va {st['valid'][1]:.1f} DD va {st['valid'][2]:.1f} full {st['dd']:.1f}",flush=True)
        return st
    run('CURRENT (TTT subset)',cur)
    order=[s for s,_ in rank24]
    for k,sz in SIZES.items():run(f'LIQ2024 {k}',allocate(order,sz))
    rng=np.random.default_rng(7);rnd=[]
    for i in range(N_RANDOM):
        o=list(rng.permutation(order));rnd.append(run(f'RANDOM#{i} 8/15/rest',allocate(o,SIZES['8/15/rest']))['valid'][0])
    res['random_valid_calmar']=dict(values=rnd,median=float(np.median(rnd)),p10=float(np.percentile(rnd,10)),p90=float(np.percentile(rnd,90)))
    print('RANDOM validation Calmar median',round(np.median(rnd),2),'p10',round(np.percentile(rnd,10),2),'p90',round(np.percentile(rnd,90),2))
    dep=allocate([s for s,_ in rankNow],SIZES['8/15/rest']);res['deploy']=dep;run('DEPLOY (latest 12m) 8/15/rest',dep)
    (U.OUT/'allocation.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
