"""C3 agent 6 - cause NO SIGNAL: continuation entries inside C3's own trend regime.

Diagnosis (C3_DIAGNOSIS.md): in big trends 17.8% of the move happens while C3 is flat although its trend filter
(EMA50 vs EMA200) agrees - the trend runs without an RSI14 pullback to 40/60, or C3 was stopped/trailed out and no new
pullback came. Mechanism: a trend that does not pull back expresses itself as fresh range extremes or as only shallow
RSI dips; adding such triggers, strictly gated by the SAME regime (long only if EMA50>EMA200, short only if EMA50<EMA200),
lets C3 participate in pullback-less legs. Exit/stop/sizing unchanged (engine mode 6, 2 ATR initial stop, 4.5 ATR
chandelier), weekend mask d['wk'] unchanged, one position per coin (engine). Extra signals are OR'ed with PULL.

PRE-DECLARED variants (fixed round parameters, declared before any run, no post-hoc changes):
  DON55     regime & 55-bar Donchian breakout (close > prior 55-bar high / < prior 55-bar low, ~9 days).
            Slow breakout -> few trades, aims at the big pullback-less legs only.
  DON20_NP  regime & 20-bar Donchian breakout, only if NO PULL entry signal in the same direction during the last
            60 bars (10 days): the "trend without pullback" case explicitly; avoids doubling up where PULL works.
  SHALLOW   regime & ADX14 >= 25 & RSI14 re-crosses 50 (up for longs / down for shorts): a shallower pullback
            threshold only when the trend is strong.
All inputs use bars <= signal bar (rolling windows shifted by one, EMA/RSI/ADX causal). Gates G1-G5 as c3bench.
"""
from pathlib import Path
import sys
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B, mtf_search as M, ltf_search as L

VARIANTS={'DON55':dict(kind='don',N=55,np_bars=0),
          'DON20_NP':dict(kind='don',N=20,np_bars=60),
          'SHALLOW':dict(kind='shallow',adx=25,lvl=50)}

def _recent(x,k):
    """True if x fired in any of the last k bars including the current one (causal)."""
    s=pd.Series(x.astype(float)).rolling(k,min_periods=1).max().to_numpy()
    return s>0

def trades_fn(d,v):
    ple,pse,_,_=d['sig']['PULL'];h,l,c=d['h'],d['l'],d['c']
    up=d['e50']>d['e200'];dn=d['e50']<d['e200']
    if v['kind']=='don':
        N=v['N'];hh=pd.Series(h).rolling(N).max().shift(1).to_numpy();ll=pd.Series(l).rolling(N).min().shift(1).to_numpy()
        xl=np.nan_to_num(c>hh)&up;xs=np.nan_to_num(c<ll)&dn
        if v['np_bars']:
            xl&=~_recent(ple,v['np_bars']);xs&=~_recent(pse,v['np_bars'])
    else:
        r=d['r14'];f=np.full_like(r,v['lvl']);strong=np.nan_to_num(d['adx'])>=v['adx']
        xl=L.cross_up(r,f)&up&strong;xs=L.cross_dn(r,f)&dn&strong
    le=(ple|np.asarray(xl,bool));se=(pse|np.asarray(xs,bool));z=np.zeros(d['n'],bool)
    return M.engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,z,z,d['wk'],d['wk'],6,.0006,.0002,d['fb'],300)

if __name__=='__main__':
    B.run('a6_continuation',VARIANTS,trades_fn,notes=__doc__)
