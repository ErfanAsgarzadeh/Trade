"""pa_opt_sizing: position sizing / risk on the PA sleeve (4h KEYREV, TP2, 30-bar stop).

HYPOTHESIS. The KEYREV edge is thin (mean ~0.05R/trade on TRAIN) and its P&L is lumpy (2023 -10%). Risk-weighting trades by
a quality proxy, throttling after the sleeve's own bad runs and capping correlated clusters of simultaneous positions could
raise risk-adjusted return (account Calmar) without touching the entries.
MECHANISM. (1) stronger rejection bar (close nearer the extreme) / bigger outside bar -> bigger size; (2) inverse-vol sizing
evens out risk across vol regimes; (3) equity-curve throttle halves risk while the sleeve is in a drawdown regime
(regime persistence); (4) a cap on concurrent positions limits crypto-wide cluster risk (signals on many coins fire together).

TRAIN-ONLY DIAGNOSTIC (baseline trades 2021-10..2024-12 on OTHER20, 1104 trades, mean R 0.046; quintiles of mean R):
 close position in range: -0.022, .093, -0.010, .100, .067 (weak upward, non-monotone)
 outside-bar range/ATR: -0.045, .022, .187, .044, .021 (only the bottom bucket is bad; peak in the middle)
 atr_rel (ATR/median prev 60): -0.067, .066, .091, .161, -0.023 (inverted-U)
 stop%: -.027, -.073, .206, -.024, .147 (noise)
 trailing-60d sleeve P&L < 0 at entry: 571 trades mean R 0.020 vs >=0: 533 trades 0.073 (mild support for the throttle)
 concurrent open at entry (others): <=1: .059 (465), 2-3: .036 (335), 4-5: -.016 (176), 6-8: .046 (81), >8: .216 (47)
   (no evidence that crowded entries are worse; median concurrency 3, p90 7, max 17)
 So no strong cue; variants below are mechanism-driven with round parameters, not fitted to these tables.

Features are causal (bar t = signal bar). Throttle/cap use a SHADOW pass: the unthrottled baseline trades of the sleeve
(OTHER20 group, or IN15 group for IN15 coins) - throttle looks only at trades whose exit minute < close of the signal bar;
the cap decides at the pending order's fill time using accepted positions open then. Approximations: shadow trades are
unthrottled/uncapped (second-order feedback ignored), cap is a single pass (a dropped trade can let a later signal of the
same coin trade, not counted against the cap).

VARIANTS (fixed):
 A strong_close  mult = 0.75 + 0.5*(pos-0.75)/0.25   (pos = close position in range toward the signal side, 0.75..1)
 B bar_size      mult = clip(range/ATR / 1.5, 0.5, 1.5)
 C inv_vol       mult = clip(1/atr_rel, 0.6, 1.4), atr_rel = ATR[t]/median(ATR[t-60..t-1])
 D throttle      mult 0.5 while shadow-sleeve trailing-60-day net P&L (closed trades) < 0
 E cap5          at most 5 concurrent PA positions (group-wide)
 F cap3          at most 3 concurrent PA positions
 G throttle_cap5 D and E
 H strong_invvol A x C
Also reported (not a variant, report only): risk level grid 0.10..0.30% on the deployed rules (scaled baseline series).
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import functools
import numpy as np,pandas as pd
from high_cagr.ideas import pabench as PB
from high_cagr.ideas import xuni as X

VARIANTS={'A_strong_close':dict(k='close'),'B_bar_size':dict(k='size'),'C_inv_vol':dict(k='ivol'),'D_throttle':dict(k='thr'),
    'E_cap5':dict(k='cap',cap=5),'F_cap3':dict(k='cap',cap=3),'G_throttle_cap5':dict(k='thr',cap=5),'H_strong_invvol':dict(k='close',iv=1)}

def group(name):return 'O20' if name in PB.OTHER20 else 'IN15'
def coins_of(g):return PB.OTHER20 if g=='O20' else PB.IN15

@functools.lru_cache(None)
def shadow(g):
    """Pass 1: unthrottled baseline trades of the group -> (all trades sorted by exit w/ cumulative net, accepted-by-cap sets)."""
    T=[];
    for s in coins_of(g):
        d=PB.coin(s);t=np.asarray(PB.run(d),float)
        for r in t:T.append((r[0],r[1],r[3],s,sigbar(d,r)))
    return T

def sigbar(d,r):
    gg=d['sig'];b=int(r[0])//240;raw=r[6]/(1+r[2]*PB.SLIP);best=None
    for t in range(b-1,max(b-1-60,0),-1):
        if gg['side'][t]!=0 and t+1<=b<=t+gg['val'][t] and gg['side'][t]==r[2]:
            e=abs(raw-gg['lev'][t])
            if best is None or e<=best[0]:best=(e,t)
    return -1 if best is None else best[1]

@functools.lru_cache(None)
def thr_tables(g):
    T=sorted(shadow(g),key=lambda x:x[1]);ex=np.array([x[1] for x in T]);cs=np.concatenate([[0.],np.cumsum([x[2] for x in T])]);return ex,cs

@functools.lru_cache(None)
def rejected(g,cap):
    T=sorted(shadow(g),key=lambda x:(x[0],x[1]));acc=[];rej={}
    for en,exm,net,s,t in T:
        if sum(1 for e in acc if e>en)<cap:acc.append(exm)
        else:rej.setdefault(s,set()).add(t)
    return rej

def fn(d,v):
    g=group(d['name']);n=len(d['sig']['side']);k=v['k'];mult=np.ones(n);side=d['sig']['side'].copy()
    h,l,c,a=d['h'][:n],d['l'][:n],d['c'][:n],d['atr'][:n];sd=side
    with np.errstate(all='ignore'):
        rng=np.maximum(h-l,1e-12);pos=np.where(sd==1,(c-l)/rng,(h-c)/rng)
        med=pd.Series(a).rolling(60).median().shift(1).to_numpy();rel=a/med;size=rng/a
    ivol=np.where(np.isfinite(rel)&(rel>0),np.clip(1/rel,.6,1.4),1.)
    close=np.where(np.isfinite(pos),.75+.5*(np.clip(pos,.75,1)-.75)/.25,1.)
    if k=='close':
        mult=close*(ivol if v.get('iv') else 1.)
    elif k=='size':mult=np.where(np.isfinite(size),np.clip(size/1.5,.5,1.5),1.)
    elif k=='ivol':mult=ivol
    if k=='thr':
        ex,cs=thr_tables(g);tcl=(np.arange(n)+1)*240
        i1=np.searchsorted(ex,tcl,side='left');i0=np.searchsorted(ex,tcl-60*1440,side='left')
        tr=cs[i1]-cs[i0];mult=np.where(tr<0,.5,1.)
    if 'cap' in v:
        for t in rejected(g,v['cap']).get(d['name'],()):
            if 0<=t<n:side[t]=0
    return PB.run(d,side=side.astype(np.int8),mult=mult)

def diag_sanity():
    for g in ('O20',):
        T=shadow(g);print('shadow',g,'trades',len(T),'unmapped signal bars',sum(1 for x in T if x[4]<0))
        for cap in (5,3):print('cap',cap,'rejected',sum(len(v) for v in rejected(g,cap).values()))

def risk_grid():
    o,_=PB.series(PB.base_fn,None,PB.OTHER20);bot,c3=PB.two();tw=bot+c3
    print('RISK GRID (report only; scaled baseline series; THREE = two + PA at risk r)')
    for r in (.0010,.0015,.0020,.0025,.0030):
        s=X.stats(tw+o*(r/PB.RISK));p=X.stats(o*(r/PB.RISK))
        print(f"  r={r*100:.2f}%: THREE train {s['train'][0]:.2f} valid {s['oos'][0]:.2f} full {s['full'][0]:.2f} CAGR {s['full'][1]:.1f}% DD {s['full'][2]:.1f}% | PA full CAGR {p['full'][1]:.1f}% DD {p['full'][2]:.1f}%",flush=True)

def main():
    diag_sanity();risk_grid();PB.run_idea('sizing',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
