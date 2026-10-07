"""Frozen bench for C3 upgrades. DO NOT EDIT from an agent.

A candidate is trades_fn(d, variant) -> np.ndarray of trades in the engine format
  [entry_bar, exit_bar, side(+1/-1), net_frac, price_R, qty, entry_fill, exit_fill, cost]   (sizing base 1e4, 0.5% risk)
where d = coin dict from coin(): o h l c atr adx (4h bars from 2021-10-05), sig (dict family -> (le, se, lx, sx)),
wk (no-weekend mask on the signal bar), fb (cumulative funding at bar starts), e50 e200 r14 (EMA50/200, RSI14), n.
Use M.engine (high_cagr.ideas.mtf_search.engine) or your own copy of it; entries must use only bars <= signal bar
(check_causal reruns on truncated data). Baseline = C3: M.engine(PULL, mode 6 TRAILW, wk filter).

Universes: MAIN10 (the C3 coins), OTHER20 (the other 20 tested coins, never chosen for C3).
Portfolio: bot (2A+5A) + C3 at 0.15%/trade (= C3 series x 0.3), daily mark-to-market.
GATES (pre-declared, all must hold):
  G1 MAIN10 train Calmar >= 1.10 x baseline train Calmar
  G2 MAIN10 validation Calmar >= baseline validation Calmar
  G3 OTHER20 full-period Calmar >= baseline OTHER20 full Calmar  (generalisation)
  G4 portfolio full Calmar >= baseline portfolio full Calmar AND portfolio full max DD <= baseline + 1.0 pp
  G5 causal
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import ltf_search as L, mtf_search as M, xuni as X, holdout_test as H, orb_intraday as oi
MAIN10=['AAVEUSDT','UNIUSDT','AVAXUSDT','KSMUSDT','EGLDUSDT','DOTUSDT','DOGEUSDT','ONEUSDT','TRXUSDT','SUSHIUSDT']
OTHER20=[s for s in X.NEW+H.H10+H.H2 if s not in MAIN10];SPLIT=X.SPLIT;OUT=X.OUT/'c3'

@functools.lru_cache(None)
def coin(s):
    p=np.load(X.PREP/s/'prices.npy');f=np.load(X.PREP/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fc=np.concatenate([[0.],np.cumsum(f)])
    o,h,l,c=L.bars(p,240);sig,atr,adx=L.signals(o,h,l,c);sig=M.extra_signals(o,h,l,c,atr,adx,sig);n=len(c)
    wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    v=X.minute_volume(s,len(p))[:n*240].reshape(n,240).sum(1)
    return dict(name=s,o=o,h=h,l=l,c=c,v=v,atr=atr,adx=adx,sig=sig,wk=wk,fb=fc[np.minimum(np.arange(n)*240,len(fc)-1)],n=n,e50=L.ema(c,50),e200=L.ema(c,200),r14=L.rsi(c,14))

def baseline_trades(d,variant=None):
    le,se,_,_=d['sig']['PULL'];z=np.zeros(d['n'],bool)
    return M.engine(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,z,z,d['wk'],d['wk'],6,.0006,.0002,d['fb'],300)

@functools.lru_cache(1)
def days():return len(np.load(X.PREP/MAIN10[0]/'prices.npy',mmap_mode='r'))//1440
@functools.lru_cache(1)
def bot():return oi.bot_daily(days())

def series(fn,variant,coins):
    r=np.zeros(days());T=[]
    for s in coins:
        d=coin(s);t=fn(d,variant);T.append(t)
        if len(t):r+=M.m2m(np.asarray(t,float),d['c'],240,days())
    return r,T

def evaluate(fn,variant=None):
    m,Tm=series(fn,variant,MAIN10);o,_=series(fn,variant,OTHER20);port=bot()+m*.3
    t=np.concatenate([x for x in Tm if len(x)]) if any(len(x) for x in Tm) else np.zeros((0,9))
    return dict(main=X.stats(m),other=X.stats(o*10/20),port=X.stats(port),trades=int(len(t)),win=float((t[:,3]>0).mean()*100) if len(t) else 0.,mean_R=float(t[:,3].mean()/.005) if len(t) else 0.)

@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate(baseline_trades);OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r,indent=1,default=float));return json.loads(p.read_text())

def verdict(r):
    b=baseline();ck={'G1_main_train':r['main']['train'][0]>=1.10*b['main']['train'][0],'G2_main_valid':r['main']['oos'][0]>=b['main']['oos'][0],
        'G3_other20':r['other']['full'][0]>=b['other']['full'][0],'G4_portfolio':r['port']['full'][0]>=b['port']['full'][0] and r['port']['full'][2]<=b['port']['full'][2]+1.0}
    return dict(checks=ck,passed=all(ck.values()))

def check_causal(fn,variant,coins=('AVAXUSDT','DOGEUSDT'),cuts=(.4,.7)):
    """Trades entered and exited before the cut must be identical when the future bars are removed."""
    for s in coins:
        d=coin(s);full=np.asarray(fn(d,variant),float)
        for q in cuts:
            k=int(d['n']*q);dt={key:(val[:k] if isinstance(val,np.ndarray) and len(val)==d['n'] else val) for key,val in d.items()}
            dt['sig']={f:tuple(a[:k] for a in v) for f,v in d['sig'].items()};dt['n']=k;dt['fb']=d['fb'][:k]
            # indicators recomputed on the truncated history so nothing from the future leaks through them
            dt['atr']=d['atr'][:k];part=np.asarray(fn(dt,variant),float)
            a=full[(full[:,1]<k-1)] if len(full) else full;b_=part[(part[:,1]<k-1)] if len(part) else part
            if a.shape!=b_.shape or (len(a) and not np.allclose(a,b_)):return dict(causal=False,coin=s,cut=q)
    return dict(causal=True)

def run(name,variants,fn,notes=''):
    """Evaluate every declared variant; writes output/ideas/c3/<name>.json. Returns the dict."""
    b=baseline();out=dict(name=name,notes=notes,baseline=b,variants={})
    for v,var in variants.items():
        r=evaluate(fn,var);cz=check_causal(fn,var);vd=verdict(r);r['verdict']=vd;r['causal']=cz;r['passed']=bool(vd['passed'] and cz['causal']);out['variants'][v]=dict(variant=var,**r)
        mm,oo,pp=r['main'],r['other'],r['port']
        print(f"{name}/{v}: MAIN10 train {mm['train'][0]:.2f} valid {mm['oos'][0]:.2f} (CAGR {mm['full'][1]:.1f}% DD {mm['full'][2]:.1f}%) | OTHER20 {oo['full'][0]:.2f} | PORT CAGR {pp['full'][1]:.1f}% DD {pp['full'][2]:.1f}% Calmar {pp['full'][0]:.2f} | trades {r['trades']} win {r['win']:.1f}% | causal={cz['causal']} PASS={r['passed']} {[k for k,x in vd['checks'].items() if not x]}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{name}.json').write_text(json.dumps(out,indent=1,default=float));return out

if __name__=='__main__':
    b=baseline();print('baseline',{k:{p:[round(x,2) for x in v] for p,v in b[k].items()} for k in ('main','other','port')},b['trades'])
