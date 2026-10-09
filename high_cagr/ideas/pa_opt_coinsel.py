"""pa_opt_coinsel: train-chosen coin selection for the PA sleeve.

HYPOTHESIS. A subset of coins chosen on TRAIN only (before 2025-01-01) beats trading all 20 OTHER20 coins out of sample,
because KEYREV works better on some coin characteristics (liquid / volatile / historically profitable coins).
NULL: per-coin PF over ~60 trades is mostly noise (SE of PF ~0.25), so subsets chosen by train PF/net/win rate will look great on
TRAIN (by construction) and revert on VALIDATION; characteristic-based rules (liquidity, volatility) have a mechanism and
a chance to persist.

MECHANISM. Liquid coins: tighter stop-run structure, less slippage than the flat SLIP assumed. High-ATR% coins: bigger
stop distance relative to the fixed round-trip cost, so costs eat less of the 2R. Train-profitable coins: persistence of coin character.

TRAIN-only diagnostic (baseline KEYREV per OTHER20 coin, trades with entry < 2025-01-01; PF / net % of base / win% ):
 NEAR 1.63/9.44/46.7, AXS 1.41/5.03/48.0, IOST 1.30/5.90/43.7, LINK 1.23/3.83/43.9, FIL 1.22, ALICE 1.15, CVC 1.11 (n19; no volume data -> liq 0),
 LTC 1.10, ETC 1.09, VET 1.08, C98 1.01, BCH 0.95, ALGO 0.91, IOTA 0.89, 1000SHIB 0.87 (n26), XTZ 0.80, CELR 0.78, CRV 0.77, THETA 0.69, ATOM 0.66.
 11 of 20 coins have PF>1; median ATR% ranges 2.2-3.3 (narrow), liquidity 1.7M-38M per 4h bar median.
Decisions use only TRAIN trades / TRAIN bars of each coin (cached from a baseline run, trades entered before the split).
Thresholds for rank rules are medians over OTHER20 train values and are applied identically to IN15 coins (P4 check).

VARIANTS (fixed before the run; keep coin if):
 pf_gt1     : train PF > 1.0
 pf_gt1_n40 : train PF > 1.0 and train trades >= 40 (drops thin-sample coins)
 top_net    : train net >= median over OTHER20 (top 10 by net)
 top5_net   : train net >= 5th-highest OTHER20 train net (top 5)
 liquid     : median train 4h volume*close >= OTHER20 median
 high_atr   : median train ATR/close >= OTHER20 median (more volatile half)
 low_atr    : median train ATR/close <= OTHER20 median (calmer half)
 win_ge40   : train win rate (legs) >= 40%
"""
import sys,functools
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr.ideas import pabench as PB

SM=PB.SPLIT*1440

@functools.lru_cache(None)
def tstat(s):
    d=PB.coin(s);t=PB.run(d);t=t[t[:,0]<SM];nn=min(d['n'],SM//240);w=t[:,3]
    gp=w[w>0].sum();gl=-w[w<0].sum()
    return dict(n=len(t),pf=gp/gl if gl>0 else 9.,net=w.sum(),win=(w>0).mean() if len(w) else 0.,
                liq=float(np.median(d['v'][:nn]*d['c'][:nn])),atr=float(np.median(d['atr'][250:nn]/d['c'][250:nn])))

@functools.lru_cache(None)
def ref():
    S=[tstat(s) for s in PB.OTHER20]
    return dict(net_med=np.median([x['net'] for x in S]),net5=sorted([x['net'] for x in S])[-5],
                liq_med=np.median([x['liq'] for x in S]),atr_med=np.median([x['atr'] for x in S]))

def keep(s,v):
    x=tstat(s);r=ref()
    return {'pf_gt1':x['pf']>1,'pf_gt1_n40':x['pf']>1 and x['n']>=40,'top_net':x['net']>=r['net_med'],'top5_net':x['net']>=r['net5'],
            'liquid':x['liq']>=r['liq_med'],'high_atr':x['atr']>=r['atr_med'],'low_atr':x['atr']<=r['atr_med'],'win_ge40':x['win']>=.40}[v]

def fn(d,v):
    if not keep(d['name'],v):return np.zeros((0,10))
    return PB.run(d)

VARIANTS={k:k for k in ['pf_gt1','pf_gt1_n40','top_net','top5_net','liquid','high_atr','low_atr','win_ge40']}

def main():
    print('kept OTHER20 per variant:',{v:[s for s in PB.OTHER20 if keep(s,v)] for v in VARIANTS})
    PB.run_idea('coinsel',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
