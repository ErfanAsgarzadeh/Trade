"""pa_opt_trendfilt: trend / regime filters on the KEYREV signal bar.

HYPOTHESIS. The 4h key reversal is an exhaustion/liquidity-sweep pattern. It should work as a COUNTER-trend reversal (against the
daily trend / EMA50 slope) more than as a with-trend pullback, and it should work better when the market is directional
(high ADX) and when BTC's regime supports the trade side (BTC close above EMA200 for longs, below for shorts), because the
other 20 coins are beta to BTC.

MECHANISM. Reversal bar after a push = trapped traders; with BTC regime in the trade direction the squeeze has fuel; in
a chop (low ADX) there is no follow-through to reach 2R.

TRAIN-only diagnostic (not used to pick parameters beyond choosing which filters to declare; 1104 baseline TRAIN trades, OTHER20):
 mean net bp per trade: htf against side 1.2 (n623) vs with side -1.1 (n472); e50 slope against 1.6 (n775) vs with -3.0 (n329);
 BTC>EMA200 on trade side 3.1 (n538) vs against -2.5 (n566); ADX top third (>=29) 4.3 vs mid -2.6 vs low -1.2; longs 1.8, shorts -1.2.

VARIANTS (fixed before the run; side = signal side, sgn = +1 long / -1 short, t = signal bar):
 counter_htf : keep only if sgn*htf[t] <= 0 (daily trend against or neutral)
 with_htf    : keep only if sgn*htf[t] >= 0 (mirror check)
 e50_against : keep only if sgn*(e50[t]-e50[t-6]) < 0 (EMA50 slope opposes the trade)
 btc_with    : keep only if sgn*(btc.c[t]-btc.e200[t]) > 0
 adx_hi      : keep only if adx[t] >= 29
 adx_btc     : adx[t] >= 29 AND btc_with
 counter_btc : counter_htf AND btc_with
 size_btc    : no drop; risk multiplier 1.5 if btc_with else 0.5
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr.ideas import pabench as PB

VARIANTS={k:k for k in ['counter_htf','with_htf','e50_against','btc_with','adx_hi','adx_btc','counter_btc','size_btc']}

def fn(d,v):
    sd=d['sig']['side'].astype(np.int64);n=len(sd);sg=np.sign(sd).astype(float)
    htf=d['htf'][:n];e50=d['e50'][:n];adx=d['adx'][:n];b=d['btc']
    slope=np.zeros(n);slope[6:]=e50[6:]-e50[:-6]
    bw=sg*(b['c'][:n]-b['e200'][:n])>0
    ch=sg*htf<=0
    keep={'counter_htf':ch,'with_htf':sg*htf>=0,'e50_against':sg*slope<0,'btc_with':bw,'adx_hi':adx>=29,
          'adx_btc':(adx>=29)&bw,'counter_btc':ch&bw,'size_btc':np.ones(n,bool)}[v]
    side=np.where(keep,sd,0).astype(np.int8)
    mult=np.where(bw,1.5,0.5) if v=='size_btc' else None
    return PB.run(d,side=side,mult=mult)

def main():PB.run_idea('trendfilt',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
