"""Frozen bench for the SECOND Ghoghnous (PA sleeve) meeting. DO NOT EDIT from an agent.

Baseline = deployed Ghoghnous C1: 4h KEYREV, buy/sell-stop at the signal extreme valid 1 bar, stop beyond the signal bar,
skip signal bars with range < 1.1 ATR, NO target, 30-bar time stop (pabench.run(target_r=0) with that side mask).
Engine, costs, data and periods are pabench's (minute fills, taker 0.06%/side + 2 bps + funding, risk 0.5% of a fixed
1e4 base per trade, notional <= 1x, stops < 0.4% skipped; TRAIN < 2025-01-01, VALID 2025-01-01..2026-10-04).

Unlike the first meeting, the target is a BETTER GHOGHNOUS (stand-alone) that still helps the account:
GATES (pre-declared, vs the C1 baseline; all must hold):
  Q1 PA alone on OTHER20: TRAIN Calmar >= baseline + 0.15
  Q2 PA alone on OTHER20: VALID Calmar >= baseline VALID Calmar
  Q3 PA alone on IN15 (coins never used to design Ghoghnous): FULL Calmar >= baseline IN15 FULL Calmar
  Q4 Account: THREE = TWO + PA x (r/0.5%) with r chosen on TRAIN from RISKS (max THREE train Calmar subject to THREE train
     DD <= baseline's THREE train DD at its own chosen r + 1 pp); THREE FULL Calmar >= baseline's
  Q5 Costs: PA alone on OTHER20 at 5 bps slippage per fill, FULL CAGR > 0 and FULL Calmar >= 0.5 x its 2 bps value
  Q6 causal (pabench.check_causal)
A candidate is fn(d, variant) -> trades (pabench row format). Helpers: c1_side(d) (baseline signal mask),
run (= pabench.run on 4h), run_tf(d, bm, sig, ...) for any timeframe (bm minutes: 60, 120, 240, 480, 720, 1440) with your
own signal arrays, bars(d, bm) -> o,h,l,c from minute data, atr14(h,l,c), ema(x,n).
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pabench as PB, pa_bot as PBOT, xuni as X, ltf_search as L
OUT=X.OUT/'pa_opt2';RISKS=[.001,.0015,.0025,.004,.005,.0075];OTHER20,IN15=PB.OTHER20,PB.IN15
ema,atr14=PBOT.ema,PBOT.atr14

def c1_side(d):
    n=d['n'];side=d['sig']['side'][:n].copy();side[(d['h'][:n]-d['l'][:n])<1.1*d['atr'][:n]]=0;return side
def base_fn(d,variant=None):return PB.run(d,side=c1_side(d),target_r=0.)
run=PB.run

@functools.lru_cache(None)
def _tfbars(name,bm):
    p=PB._px(name);o,h,l,c=L.bars(p,bm);return o,h,l,c
def bars(d,bm):
    """OHLC on bm-minute bars built from the coin's minute data (respects truncation in check_causal)."""
    n=len(d['P'])//bm
    if len(d['P'])==len(PB._px(d['name'])):return tuple(x[:n] for x in _tfbars(d['name'],bm))
    o,h,l,c=L.bars(np.asarray(d['P']),bm);return o,h,l,c

def run_tf(d,bm,side,kind,lev,stp,val,atr,mult=None,target_r=0.,hold=30,partial_frac=0.,partial_r=1.,be_r=0.,trail_after_r=0.,trail_atr=3.,
           early_bars=0,early_r=0.,warm=None,risk=None):
    """pabench.engine2 on any timeframe. side/kind/lev/stp/val/atr are per bm-bar arrays (signal on bar t, orders from t+1);
    kind 1 = stop entry at lev valid val bars, 2 = market at next bar open. hold/early_bars count bm-bars."""
    n=len(side);mu=np.ones(n) if mult is None else np.asarray(mult,np.float64)
    w=warm if warm is not None else min(250,max(60,int(250*240/bm)))
    return PB.engine2(d['P'],d['fc'],bm,np.asarray(side,np.int8),np.asarray(kind,np.int8),np.asarray(lev,np.float64),np.asarray(stp,np.float64),
                      np.asarray(val,np.int64),np.asarray(atr,np.float64),mu,float(target_r),int(hold),float(partial_frac),float(partial_r),float(be_r),
                      float(trail_after_r),float(trail_atr),int(early_bars),float(early_r),PB.FEE,PB.SLIP,PB.RISK if risk is None else risk,PB.CAP,PB.MINSTOP,int(w))

def _pick(pa):
    bot,c3=PB.two();tw=bot+c3;grid=[]
    for r in RISKS:t=X.stats(tw+pa*(r/PB.RISK));grid.append(dict(risk=r,train=t['train'],oos=t['oos'],full=t['full']))
    return grid

def evaluate(fn,variant=None,stress=True):
    o,To=PB.series(fn,variant,OTHER20);g,_=PB.series(fn,variant,IN15);res=dict(pa=X.stats(o),in15=X.stats(g),trades=PB.tstats(To),grid=_pick(o))
    res['yearly_pa']=pd.Series(o*100,index=pd.date_range('2021-10-05',periods=PB.days())).groupby(lambda x:x.year).sum().round(1).to_dict()
    if stress:
        old=PB.SLIP;PB.SLIP=.0005
        try:s,_=PB.series(fn,variant,OTHER20);res['pa_5bps']=X.stats(s)
        finally:PB.SLIP=old
    res['_o']=o;return res

def choose(grid,dd_cap):
    ok=[g for g in grid if g['train'][2]<=dd_cap];return max(ok,key=lambda g:g['train'][0]) if ok else min(grid,key=lambda g:g['train'][2])

@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate(base_fn);r.pop('_o');pick=max(r['grid'],key=lambda g:g['train'][0]);r['pick']=pick
    OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r,indent=1,default=float));return json.loads(p.read_text())

def verdict(r):
    b=baseline();pick=choose(r['grid'],b['pick']['train'][2]+1.);r['pick']=pick
    ck=dict(Q1=r['pa']['train'][0]>=b['pa']['train'][0]+.15,Q2=r['pa']['oos'][0]>=b['pa']['oos'][0],Q3=r['in15']['full'][0]>=b['in15']['full'][0],
            Q4=pick['full'][0]>=b['pick']['full'][0],Q5=r['pa_5bps']['full'][1]>0 and r['pa_5bps']['full'][0]>=.5*r['pa']['full'][0])
    return dict(checks={k:bool(v) for k,v in ck.items()},passed=bool(all(ck.values())))

def fmt(r):
    p,g,s=r['pa'],r['in15'],r.get('pick',{})
    return (f"PA train {p['train'][0]:.2f} valid {p['oos'][0]:.2f} full CAGR {p['full'][1]:.1f}% DD {p['full'][2]:.1f}% Calmar {p['full'][0]:.2f} | IN15 {g['full'][0]:.2f} | "
            f"5bps CAGR {r['pa_5bps']['full'][1]:.1f}% | THREE @{s.get('risk',0)*100:.2f}% full {s.get('full',[0])[0]:.2f} | roots {r['trades']['roots']}")

def run_idea(name,variants,fn,notes=''):
    b=baseline();out=dict(name=name,notes=notes,baseline=b,variants={})
    for v,var in variants.items():
        r=evaluate(fn,var);r.pop('_o');cz=PB.check_causal(fn,var);vd=verdict(r)
        out['variants'][v]=dict(variant=var,**r,causal=cz,verdict=vd,passed=bool(vd['passed'] and cz['causal']))
        print(f"{name}/{v}: {fmt(r)} | causal={cz['causal']} PASS={out['variants'][v]['passed']} fail={[k for k,x in vd['checks'].items() if not x]}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{name}.json').write_text(json.dumps(out,indent=1,default=float));return out

if __name__=='__main__':
    b=baseline();print('C1 BASELINE',fmt(b),'| yearly PA@0.5%',b['yearly_pa'],'| THREE pick',b['pick']['risk'],[round(x,2) for x in b['pick']['full']])
