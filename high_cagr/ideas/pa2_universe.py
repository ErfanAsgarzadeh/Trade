"""pa2_universe -- Ghoghnous (C1) universe and stand-alone potential (declared BEFORE any variant result was computed).

QUESTION. Ghoghnous trades OTHER20 only so that it never shares a coin with Shahin (MAIN5) or Mojsavar (MAIN10). Is that
coin set what limits it? Would a liquidity-ranked universe, a cleaned OTHER20, or the full 35-coin set (stand-alone
potential) give a better sleeve, and what is the realistic stand-alone CAGR/DD ceiling of the best one at 0.5/1/2% risk?
HYPOTHESIS. The C1 rules are unchanged; only the coin set changes. Data audit says C1's per-trade edge is larger in
thin coins, so a liquidity-ranked universe should have LOWER mean R per trade, while more coins (ALL35) should raise
Calmar mainly through diversification (more, weakly correlated trades). Prior: no universe beats C1 on train AND valid.
MECHANISM. Signals/fills/exits/costs exactly = pabench2.base_fn (C1). A variant is a coin-membership rule plus an optional
one-net-position rule. The rule is applied to every coin the bench evaluates (OTHER20 for Q1/Q2/Q4/Q5, IN15 for Q3), so
the gates see "the OTHER20 part" and "the IN15 part" of the universe. Because Q1-Q5 only see the OTHER20 part, the
PRIMARY READOUT is UNIVERSE-LEVEL, computed in this script after run_idea: daily series = sum over all coins of the
universe at 0.5% per trade on the fixed 1e4 base, reported raw AND scaled to a 20-coin risk budget (x 20/N), train /
valid / full Calmar, CAGR, DD, 5 bps CAGR, trade count.
LIQUIDITY (TRAIN-only, no P&L looked at): median daily dollar volume (4h volume x close, summed per day) over
2021-10-05..2024-12-31, rank of 35 coins:
  1 BTC 12742M, ETH 6343, SOL 1214, XRP 533, DOGE 442, ADA 296, AVAX 291, LINK 242, 1000SHIB 234, LTC 229 (top10) |
  NEAR 188, DOT 184, ETC 166, FIL 153, BCH 126, ATOM 125, CRV 110, AXS 87, AAVE 80, UNI 75 (top20) |
  TRX 66, SUSHI 48, ALGO 46, THETA 43, EGLD 31, VET 29 (top26) | bottom quartile: XTZ 27, C98 21, ALICE 18.4, KSM 18.3,
  ONE 17.6, IOTA 16.1, CELR 14.1, IOST 10.9, CVC 0 (dead 2022-11..2025-05, 64% zero-volume 4h bars in TRAIN).
ONE-NET-POSITION RULE (_NET): skip a Ghoghnous signal on bar t if Shahin or Mojsavar holds that coin at the order-bar
open, minute (t+1)*240 (their legs from three_bots/trades.csv, deployed risks; em <= m0 <= xm). This is what the live bot
could check at scan time. Overlaps that start AFTER our entry are not prevented and are counted. Only IN15 coins can be
affected (OTHER20 has no other-bot trades).
VARIANTS (fixed; 8):
  V1 O19         OTHER20 minus the dead coin CVC (IN15 part: IN15 unchanged)
  V2 O13_LIQ     OTHER20 coins in the liquidity top-26 of 35 (drops the bottom quartile: XTZ C98 ALICE IOTA CELR IOST CVC);
                 IN15 part = IN15 coins in the top-26 (so gates = V5; universe-level differs)
  V3 TOP10       liquidity top-10 of 35
  V4 TOP20       liquidity top-20 of 35
  V5 TOP26       liquidity top-26 of 35 (all minus the bottom quartile)
  V6 ALL35       all 35 coins (stand-alone potential, ignores the conflict with the other bots)
  V7 TOP26_NET   V5 + one-net-position rule
  V8 ALL35_NET   V6 + one-net-position rule (what Ghoghnous could do on ALL coins in the shared account)
PRE-DECLARED SELECTION for the stand-alone ladder: the variant with the highest universe-level TRAIN Calmar (20-coin
scaled); ties/near-ties are not re-judged. The ladder (compounding, three_bots_replay event replay: $10k seed, risk% x
equity sizing, isolated 5x, 80% shared margin cap, notional < $20 skipped) is run for that variant AND C1 at 0.25 / 0.5 /
1 / 2% risk. The THREE account replay (Shahin 1% + Mojsavar 0.4% + Ghoghnous 0.25%) is run with C1 and with the
_NET variant of the selected universe when one exists (an un-NET universe would double-hold coins in the account).
PREDICTION. TOP-N variants: lower mean R per trade than C1; ALL35 higher Calmar than OTHER20 through diversification.
Liquidity-cleaned O13_LIQ worse than C1 (data audit U2). Gates Q1/Q2 likely fail for O13_LIQ/TOP-N.
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import json,functools
import numpy as np,pandas as pd
from high_cagr.ideas import pabench2 as Q, pabench as PB, xuni as X, pa_bot as PBOT

LIQ=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','AVAXUSDT','LINKUSDT','1000SHIBUSDT','LTCUSDT',
     'NEARUSDT','DOTUSDT','ETCUSDT','FILUSDT','BCHUSDT','ATOMUSDT','CRVUSDT','AXSUSDT','AAVEUSDT','UNIUSDT',
     'TRXUSDT','SUSHIUSDT','ALGOUSDT','THETAUSDT','EGLDUSDT','VETUSDT',
     'XTZUSDT','C98USDT','ALICEUSDT','KSMUSDT','ONEUSDT','IOTAUSDT','CELRUSDT','IOSTUSDT','CVCUSDT']
assert sorted(LIQ)==sorted(PB.ALL35)
TOP=lambda k:frozenset(LIQ[:k])
ALL=frozenset(PB.ALL35);O20=frozenset(PB.OTHER20);I15=frozenset(PB.IN15)
# rule = set of coins allowed for the bench (both parts); uni = coins of the universe-level readout
VARIANTS={
 'V1_O19':      dict(rule=ALL-{'CVCUSDT'},uni=O20-{'CVCUSDT'},net=False),
 'V2_O13_LIQ':  dict(rule=TOP(26),uni=O20&TOP(26),net=False),
 'V3_TOP10':    dict(rule=TOP(10),uni=TOP(10),net=False),
 'V4_TOP20':    dict(rule=TOP(20),uni=TOP(20),net=False),
 'V5_TOP26':    dict(rule=TOP(26),uni=TOP(26),net=False),
 'V6_ALL35':    dict(rule=ALL,uni=ALL,net=False),
 'V7_TOP26_NET':dict(rule=TOP(26),uni=TOP(26),net=True),
 'V8_ALL35_NET':dict(rule=ALL,uni=ALL,net=True)}
TB=X.OUT/'three_bots'

@functools.lru_cache(1)
def other_legs():
    t=pd.read_csv(TB/'trades.csv');t=t[t.bot.isin(['main','c3'])]
    return {c:g[['entry_min','exit_min']].to_numpy(np.int64) for c,g in t.groupby('coin')}

def busy_mask(name,n):
    """1 where another bot holds the coin at the open of the order bar (t+1)*240."""
    L=other_legs().get(name);b=np.zeros(n,bool)
    if L is None:return b
    m0=(np.arange(n)+1)*240
    for e,x in L:
        b|=(m0>=e)&(m0<=x)
    return b

_C={}
def c1_trades(d,net):
    key=(d['name'],d['n'],len(d['P']),PB.SLIP,net)
    if key not in _C:
        n=d['n'];side=Q.c1_side(d)
        if net:side=side.copy();side[busy_mask(d['name'],n)]=0
        _C[key]=PB.run(d,side=side,target_r=0.)
    return _C[key]

def fn(d,v):
    if d['name'] not in v['rule']:return np.zeros((0,10))
    return c1_trades(d,v['net'])

# ------------------------------------------------------------------ universe-level readout
def uni_series(v,coins):
    r=np.zeros(PB.days());T={}
    for s in sorted(coins):
        d=PB.coin(s);t=np.asarray(fn(d,v),float);T[s]=t
        if len(t):r+=PBOT.m2m(np.ascontiguousarray(t[:,:9]),d['c1'],PB.days())
    return r,T

def overlaps(T):
    k=0
    for s,t in T.items():
        L=other_legs().get(s)
        if L is None or not len(t):continue
        for e,x in t[:,:2]:k+=int(((L[:,0]<=x)&(L[:,1]>=e)).any())
    return k

def uni_eval(v,coins):
    r,T=uni_series(v,coins);N=len(coins);t=np.concatenate([x for x in T.values() if len(x)])
    old=PB.SLIP;PB.SLIP=.0005
    try:r5,_=uni_series(v,coins)
    finally:PB.SLIP=old
    sm=X.SPLIT*1440;R=t[:,4];net=t[:,3]*1e4/50.  # net in R units at 0.5% of 1e4 = $50
    yr=pd.Series(r*20/N*100,index=pd.date_range('2021-10-05',periods=PB.days())).groupby(lambda x:x.year).sum().round(1).to_dict()
    return dict(N=N,raw=X.stats(r),s20=X.stats(r*20/N),s20_5bps=X.stats(r5*20/N),trades=int(len(t)),train_trades=int((t[:,0]<sm).sum()),
                meanR_train=float(net[t[:,0]<sm].mean()),meanR_valid=float(net[t[:,0]>=sm].mean()),yearly_s20=yr,overlap_other_bots=overlaps(T)),T

# ------------------------------------------------------------------ compounding ladder (three_bots_replay)
def pa_legs(T):
    legs=[]
    for s,t in T.items():
        for i,r in enumerate(t):
            dist=PB.RISK*1e4/r[5]-r[6]*(2*PB.FEE+2*PB.SLIP)
            legs.append(dict(bot='pa',coin=s,side=int(r[2]),em=int(r[0]),xm=int(r[1]),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                             stop_frac=float(dist/r[6]),risk_scale=1.,root=('pa',s,i),is_add=False))
    return legs

def ladder(T,others,risks=(.0025,.005,.01,.02)):
    from high_cagr.ideas import three_bots_replay as TR
    legs=pa_legs(T);orig=TR.ledgers
    TR.ledgers=lambda:legs+others
    try:
        out={f'{r*100:g}%':TR.replay(risk={'pa':r},bots=('pa',)) for r in risks}
        out['THREE@0.25%']=TR.replay(risk={'pa':.0025}) if others else None
    finally:TR.ledgers=orig
    return out

def lfmt(r):return (f"CAGR {r['cagr']:.1f}% DD {r['dd']:.1f}% Calmar {r['calmar']:.2f} | train {r['train'][0]:.2f} valid {r['valid'][0]:.2f} | "
                    f"entries {sum(r['entries'].values())} rej {sum(r['rejected'].values())} shrunk {sum(r['shrunk'].values())} | yearly {r['yearly']}")

if __name__=='__main__':
    res=Q.run_idea('universe',{k:dict(rule=sorted(v['rule']),uni=sorted(v['uni']),net=v['net']) for k,v in VARIANTS.items()},
                   lambda d,v:fn(d,dict(rule=set(v['rule']),net=v['net'])),notes=__doc__)
    U={};TT={}
    base=dict(rule=ALL,uni=O20,net=False)
    for k,v in [('C1_OTHER20',base)]+list(VARIANTS.items()):
        U[k],TT[k]=uni_eval(v,v['uni']);u=U[k];s,s5=u['s20'],u['s20_5bps']
        print(f"UNI {k:13s} N={u['N']:2d} trades {u['trades']} | 20-scaled Calmar train {s['train'][0]:.2f} valid {s['oos'][0]:.2f} full {s['full'][0]:.2f} "
              f"CAGR {s['full'][1]:.1f}% DD {s['full'][2]:.1f}% | raw full CAGR {u['raw']['full'][1]:.1f}% DD {u['raw']['full'][2]:.1f}% Calmar {u['raw']['full'][0]:.2f} | "
              f"5bps CAGR {s5['full'][1]:.1f}% Calmar {s5['full'][0]:.2f} | meanR train {u['meanR_train']:.3f} valid {u['meanR_valid']:.3f} | overlap {u['overlap_other_bots']} | yearly {u['yearly_s20']}",flush=True)
    best=max(VARIANTS,key=lambda k:U[k]['s20']['train'][0]);print('SELECTED (max universe TRAIN Calmar):',best,flush=True)
    from high_cagr.ideas import three_bots_replay as TR
    others=[l for l in TR.ledgers() if l['bot']!='pa']
    LAD={'C1_OTHER20':ladder(TT['C1_OTHER20'],others)}
    netk=best if VARIANTS[best]['net'] or best.startswith('V1') or best.startswith('V2') else {'V5_TOP26':'V7_TOP26_NET','V6_ALL35':'V8_ALL35_NET'}.get(best)
    LAD[best]=ladder(TT[best],others if netk==best else [])
    if netk and netk!=best:LAD[netk]=ladder(TT[netk],others,risks=(.0025,))
    for k,lad in LAD.items():
        for r,x in lad.items():
            if x:print(f"LADDER {k:13s} {r:12s} {lfmt(x)}",flush=True)
    res['universe_level']=U;res['selected']=best;res['ladder']=LAD
    (Q.OUT/'universe.json').write_text(json.dumps(res,indent=1,default=lambda o:sorted(o) if isinstance(o,(set,frozenset)) else float(o)))
