"""Coin lists for the three bots on the TheTrueTrade futures universe.

1. Does coin selection carry over? Coins are chosen on TRAIN legs only (< 2025): n >= N_MIN[bot], mean R > 0 and
   profit factor (in R) >= 1.1. Their VALIDATION legs (2025-01-01 .. 2026-10-04) are compared with the rejected coins'.
2. Lists are made DISJOINT (one bot per coin, so two bots never hold the same symbol on one exchange account):
   a coin that qualifies for several bots goes to the bot with the highest score = mean R x R-weight (dollar size of one R:
   Shahin 1.0%, Mojsavar 0.4%, Ghoghnous 0.4% x 1.5).
3. Shared-account replay (five_year_report.replay sizing, 80% margin cap; Shahin limited to 4 concurrent roots as live):
   CURRENT = today's lists minus coins TTT does not list; TRAIN_PICK = step 1+2 on train only (honest, judge 2025-26);
   FULL_PICK = the same rule on the whole period (what we would deploy; in-sample); ALL = every eligible coin, disjoint.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import universe_eval as U, ledger as LG, exits as E, prepare_ttt as PT
from high_cagr.ideas import five_year_report as FY
N_MIN=dict(main=20,c3=15,pa=6);PF_MIN=1.1;WEIGHT=dict(main=.01,c3=.004,pa=.006);SLOTS=4
CURRENT=dict(main=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT'],
             c3=['AAVEUSDT','UNIUSDT','AVAXUSDT','KSMUSDT','EGLDUSDT','DOTUSDT','DOGEUSDT','ONEUSDT','TRXUSDT','SUSHIUSDT'],
             pa=['ATOMUSDT','FILUSDT','LTCUSDT','AXSUSDT','LINKUSDT','XTZUSDT','ALGOUSDT','ETCUSDT','NEARUSDT','CELRUSDT','BCHUSDT','ALICEUSDT',
                 'C98USDT','1000SHIBUSDT','THETAUSDT','IOSTUSDT','CVCUSDT','CRVUSDT','IOTAUSDT','VETUSDT'])

def R(l):return l['unit']/l['entry']/l['stop_frac']

def stats(L):
    if not L:return dict(n=0,win=np.nan,meanR=np.nan,pf=np.nan)
    r=np.array([R(l) for l in L]);g=r[r>0].sum();b=-r[r<0].sum()
    return dict(n=len(r),win=float((r>0).mean()*100),meanR=float(r.mean()),pf=float(g/b) if b>0 else np.inf)

def qualifies(L,bot):
    s=stats(L);return s['n']>=N_MIN[bot] and s['meanR']>0 and s['pf']>=PF_MIN,s

def pick(legs,period):
    """period 'train' -> legs before 2025 only; 'full' -> all legs. Returns disjoint lists + per-coin scores."""
    cut=(lambda l:l['em']<LG.SPLIT_MIN) if period=='train' else (lambda l:True)
    score={}
    for bot,C in legs.items():
        for s,L in C.items():
            ok,st=qualifies([l for l in L if cut(l)],bot)
            if ok:score.setdefault(s,{})[bot]=st['meanR']*WEIGHT[bot]
    lists={b:[] for b in legs}
    for s,sc in score.items():lists[max(sc,key=sc.get)].append(s)
    return {b:sorted(v) for b,v in lists.items()},score

def carry_over(legs):
    """Validation legs of train-qualified vs train-rejected coins, per bot (no disjointness)."""
    out={}
    for bot,C in legs.items():
        sel,rej,new=[],[],[]
        for s,L in C.items():
            tr=[l for l in L if l['em']<LG.SPLIT_MIN];va=[l for l in L if l['em']>=LG.SPLIT_MIN]
            if len(tr)<N_MIN[bot]:new+=va;continue
            (sel if qualifies(tr,bot)[0] else rej).extend(va)
        out[bot]=dict(selected=stats(sel),rejected=stats(rej),no_train_history=stats(new))
    return out

def slot_limit(L,k=SLOTS):
    """Shahin's live cap: at most k roots open at once (adds follow their root); first come first served by entry minute."""
    roots=sorted([l for l in L if not l['is_add']],key=lambda l:(l['em'],l['coin']));open_=[];keep=set()
    for l in roots:
        open_=[x for x in open_ if x>l['em']]
        if len(open_)<k:keep.add(l['root']);open_.append(l['xm'])
    return [l for l in L if l['root'] in keep]

def account(legs,lists):
    L=[]
    for bot,coins in lists.items():
        x=[l for s in coins for l in legs[bot].get(s,[])]
        L+=slot_limit(x) if bot=='main' else x
    r=E.replay_legs(L);st=E.account_stats(r);t=r['trades'];st['by_bot']={b:dict(trades=int(len(g)),win=float((g.pnl>0).mean()*100)) for b,g in t.groupby('bot')}
    return st,r['daily']

def main():
    legs={b:U.legs(b) for b in ('main','c3','pa')};res=dict(universe=U.coins(),carry_over=carry_over(legs))
    print('CARRY-OVER (validation legs of coins picked on train vs rejected):')
    for b,v in res['carry_over'].items():print(' ',b,{k:{m:round(x,2) for m,x in s.items()} for k,s in v.items()})
    tr,score_tr=pick(legs,'train');fu,score_fu=pick(legs,'full')
    cur={b:[s for s in v if s in legs[b]] for b,v in CURRENT.items()}
    allc={b:[] for b in legs}
    for s in U.coins():   # every eligible coin, to the bot with the best full-period score even if negative
        sc={b:stats(legs[b].get(s,[]))['meanR']*WEIGHT[b] for b in legs if legs[b].get(s)}
        if sc:allc[max(sc,key=sc.get)].append(s)
    res.update(lists=dict(CURRENT=cur,TRAIN_PICK=tr,FULL_PICK=fu,ALL=allc),score_train=score_tr,score_full=score_fu,accounts={})
    for name,lists in res['lists'].items():
        st,daily=account(legs,lists);res['accounts'][name]=st;np.save(U.OUT/f'daily_{name}.npy',daily)
        print(name,{b:len(v) for b,v in lists.items()},f"WR {st['win_rate']['all']:.1f} (tr {st['win_rate']['train']:.1f} va {st['win_rate']['valid']:.1f}) | Calmar tr {st['train'][0]:.2f} va {st['valid'][0]:.2f} | CAGR {st['cagr']:.1f} (va {st['valid'][1]:.1f}) DD {st['dd']:.1f} | final {st['final']:,.0f}",flush=True)
        print('   ',lists,flush=True)
    (U.OUT/'selection.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
