"""Follow-up to universe_alloc.py: (1) random disjoint lists of the CURRENT sizes (5/7/10, the TTT subset of today's lists)
from the 2024-eligible pool, to see whether today's lists beat chance; (2) today's lists with the coins TTT does not list
REPLACED by the most liquid unused coins (2024 volume for the honest test, latest 12 months for deployment), at the
original sizes 5/10/20."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import universe_eval as U, universe_select as US, universe_alloc as UA, ledger as LG
def main():
    legs={b:U.legs(b) for b in ('main','c3','pa')};split=LG.SPLIT_MIN//1440;last=len(UA.daily_usd_volume('BTCUSDT'))
    res=dict(runs={})
    def run(name,lists,show=True):
        st,_=US.account(legs,lists);res['runs'][name]=dict(lists=lists,**st)
        if show:print(f"{name:30s}",{b:len(v) for b,v in lists.items()},f"WR va {st['win_rate']['valid']:.1f} | Calmar tr {st['train'][0]:.2f} va {st['valid'][0]:.2f} | CAGR full {st['cagr']:.1f} va {st['valid'][1]:.1f} | DD full {st['dd']:.1f}",flush=True)
        return st
    cur={b:[s for s in v if s in legs[b]] for b,v in US.CURRENT.items()};base=run('CURRENT (TTT subset 5/7/10)',cur)
    pool=[s for s,_ in UA.ranking(split)];rng=np.random.default_rng(11);vals=[];trs=[]
    for i in range(40):
        o=list(rng.permutation(pool));st=run(f'RANDOM 5/7/10 #{i}',dict(main=o[:5],c3=o[5:12],pa=o[12:22]),show=False);vals.append(st['valid'][0]);trs.append(st['train'][0])
    res['random_5_7_10']=dict(valid=vals,train=trs)
    print(f"RANDOM 5/7/10 x40: validation Calmar median {np.median(vals):.2f} p10 {np.percentile(vals,10):.2f} p90 {np.percentile(vals,90):.2f}; current {base['valid'][0]:.2f} beats {np.mean(np.array(vals)<base['valid'][0])*100:.0f}%")
    print(f"                   train Calmar median {np.median(trs):.2f}; current {base['train'][0]:.2f} beats {np.mean(np.array(trs)<base['train'][0])*100:.0f}%")
    for tag,day in (('2024',split),('latest',last)):
        order=[s for s,_ in UA.ranking(day)];used=set(sum(cur.values(),[]));extra=[s for s in order if s not in used]
        fill={b:list(v) for b,v in cur.items()};need=dict(main=5,c3=10,pa=20)
        for b in ('main','c3','pa'):
            while len(fill[b])<need[b] and extra:fill[b].append(extra.pop(0))
        res[f'filled_{tag}']=fill;run(f'CURRENT + liquid fill ({tag})',fill);print('    added',{b:[s for s in fill[b] if s not in cur[b]] for b in fill})
    (U.OUT/'allocation2.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
