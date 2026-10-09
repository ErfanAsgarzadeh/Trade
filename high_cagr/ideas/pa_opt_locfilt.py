"""pa_opt_locfilt: location / structure / time filters on the KEYREV signal bar.

HYPOTHESIS. A 4h key reversal is a stop-run/exhaustion signal. It should be better when it sweeps a REAL level (prior
confirmed swing, 50-bar extreme, prior-week extreme) than in the middle of a range, and some times of the week
(weekend liquidity, Fri/Sat) should be worse because thin books give false sweeps without follow-through.

MECHANISM. Resting stops sit beyond obvious levels; a sweep + close back inside traps those traders and fuels the 2R move.
Mid-range reversals have no trapped inventory. Weekend / late-UTC bars have thin liquidity: moves mean-revert or drift.

TRAIN-only diagnostic (OTHER20, 1104 baseline TRAIN trades, mean net bp per trade; used only to choose WHICH filters to declare):
 weekday of signal bar open (0=Mon): Mon 5.3, Tue -2.7, Wed 3.4, Thu 7.8, Fri -5.9 (n175), Sat -17.1 (n112), Sun 5.5.
 UTC hour of signal bar close: 0h 6.0 (n129), 4h 2.6, 8h 2.8, 12h -1.2, 16h -2.7, 20h -3.0.
 new 50-bar extreme: yes 1.8 (n362) vs no -0.5; new 20-bar extreme: yes 0.9 vs no -1.1 (n382).
 prior-week extreme swept (diag used Friday-start weeks): yes 5.0 (n367) vs no -2.2.
 prior-day extreme swept: ~always true (21 vs -0.2, n23) -> useless, not declared.
 depth beyond last 3-bar pivot (ATR): <=-0.5 3.0, (-0.5,0] -1.6, (0,0.5] -2.3, >0.5 1.1 -> non-monotone, noise-like.

VARIANTS (fixed before the run; wd = UTC weekday of signal bar open, Mon=0, hc = UTC hour of signal bar close; t = signal bar):
 no_sat     : drop if wd==5
 no_frisat  : drop if wd in (4,5)
 early_hrs  : keep only if hc in (0,4,8)
 ext50      : keep only if signal bar makes a new 50-bar extreme (low<=min low[t-50:t] long / high>=max high short)
 wk_sweep   : keep only if bar sweeps prior Monday-based week's low (long) / high (short)
 piv_sweep  : keep only if bar sweeps beyond the last confirmed 3-bar pivot (pivot p<=t-3, pivot low is lower than 3 bars each side)
 loc_time   : (ext50 OR wk_sweep) AND wd not in (4,5)
 size_loc   : no drop; risk multiplier 1.5 if (ext50 OR wk_sweep) else 0.5
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from high_cagr.ideas import pabench as PB
from high_cagr import run_suite as rs

VARIANTS={k:k for k in ['no_sat','no_frisat','early_hrs','ext50','wk_sweep','piv_sweep','loc_time','size_loc']}

def feats(d,sg):
    h,l,n=d['h'],d['l'],d['n'];n=len(sg)
    ts=rs.START+np.arange(n)*240*60000;day=(ts-rs.START)//86400000
    wd=((pd_day:=ts//86400000)+3)%7                       # 1970-01-01 was Thursday -> Mon=0
    hc=((ts//3600000)%24+4)%24
    ext50=np.zeros(n,bool);wk=np.zeros(n,bool);piv=np.zeros(n,bool)
    wid=(ts//86400000+3)//7
    for t in np.nonzero(sg!=0)[0]:
        if t<60:continue
        g=sg[t]
        if g>0:
            ext50[t]=l[t]<=l[t-50:t].min();m=wid[:n]==wid[t]-1
            wk[t]=m.any() and l[t]<l[:n][m].min()
            pv=[p for p in range(max(3,t-60),t-2) if l[p]<min(l[p-3:p].min(),l[p+1:p+4].min())]
            piv[t]=bool(pv) and l[t]<l[pv[-1]]
        else:
            ext50[t]=h[t]>=h[t-50:t].max();m=wid[:n]==wid[t]-1
            wk[t]=m.any() and h[t]>h[:n][m].max()
            pv=[p for p in range(max(3,t-60),t-2) if h[p]>max(h[p-3:p].max(),h[p+1:p+4].max())]
            piv[t]=bool(pv) and h[t]>h[pv[-1]]
    return wd,hc,ext50,wk,piv

def fn(d,v):
    sd=d['sig']['side'].astype(np.int64);sg=np.sign(sd)
    wd,hc,e50,wk,pv=feats(d,sg)
    loc=e50|wk
    keep={'no_sat':wd!=5,'no_frisat':~np.isin(wd,(4,5)),'early_hrs':np.isin(hc,(0,4,8)),'ext50':e50,'wk_sweep':wk,'piv_sweep':pv,
          'loc_time':loc&~np.isin(wd,(4,5)),'size_loc':np.ones(len(sd),bool)}[v]
    side=np.where(keep,d['sig']['side'],0).astype(np.int8)
    mult=np.where(loc,1.5,0.5) if v=='size_loc' else None
    return PB.run(d,side=side,mult=mult)

def main():PB.run_idea('locfilt',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
