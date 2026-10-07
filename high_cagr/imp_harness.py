"""Frozen bench for NON-filter improvements (see output/fb/predeclared_round2.json). DO NOT EDIT from an agent.

A candidate is  build_fn(ctx, variant) -> dict with any of:
  sig    : signals array like ctx['sig'] (ns, nbars, 4) [side, entry price, initial stop, rank score]
  bb     : trail/bar array like ctx['bb'] (ns, nbars, 8) [low line, atr, close, high line, low3, high3, low4, high4]
  kwargs : extra keyword arguments for high_cagr.kernel_fixes.simulate (overrides the baseline policy keys)
  slots, risk, subset_slots (slots used on the OLD5/NEW10 subset runs, default 4)
ctx = fb_harness.load(): frames, ix (signal bar -> frame row), side, sig, bb, step.  Build arrays causally:
for signal bar b only use frame rows <= ix[sym][b].
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import fb_harness as fh, run_suite as rs
from high_cagr.kernel_fixes import simulate
SYM=fh.SYMBOLS
def _one(c,symbols,slots,bps,period):
    ctx=fh.load();k=[SYM.index(s) for s in symbols];name='ALL15' if len(k)==len(SYM) else ('OLD5' if symbols==fh.OLD else 'NEW10')
    sig=np.ascontiguousarray(c.get('sig',ctx['sig'])[k]);bb=np.ascontiguousarray(c.get('bb',ctx['bb'])[k])
    kw={**fh.POLICY,**c.get('kwargs',{})};b,e=fh.PERIODS[period]
    a,t,curve=simulate(fh._stacked('prices',name,symbols),fh._stacked('funding',name,symbols),sig,bb,rs.START,b,e,c.get('risk',fh.RISK),slots,ctx['step'],kw.pop('pyramid',True),slip=bps/1e4,**kw)
    r=rs.summarize(a,t,curve,b,e,symbols);return dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'],win=r['win_rate_pct'])
def evaluate(c):
    out={}
    for bps in (2,5):
        for per in fh.PERIODS:out[f'{per}|{bps}']=_one(c,SYM,c.get('slots',6),bps,per)
    for name,syms in (('OLD5',fh.OLD),('NEW10',fh.NEW)):out[name]=_one(c,syms,c.get('subset_slots',4),2,'full')
    return out
def verdict(r,b):
    c={}
    for bps in (2,5):
        c[f'positive|{bps}']=all(r[f'{p}|{bps}']['net']>0 for p in ('H1','H2','Y2026'))
        c[f'calmar+0.05|{bps}']=r[f'full|{bps}']['calmar']>=b[f'full|{bps}']['calmar']+.05
        c[f'dd_not_worse|{bps}']=r[f'full|{bps}']['dd']<=b[f'full|{bps}']['dd']
        c[f'both_halves|{bps}']=all(r[f'{p}|{bps}']['calmar']>=b[f'{p}|{bps}']['calmar'] for p in ('H1','H2'))
    c['subsets']=r['OLD5']['calmar']>=b['OLD5']['calmar'] and r['NEW10']['calmar']>=b['NEW10']['calmar']
    return dict(checks=c,passed=all(c.values()))
def baseline():
    p=fh.OUT/'baseline_round2.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate({});p.write_text(json.dumps(r,indent=1));return r
def run_idea(name,variants,build_fn,notes=''):
    b=baseline();ctx=fh.load();out=dict(idea=name,notes=notes,baseline=b,variants={})
    for v,var in variants.items():
        r=evaluate(build_fn(ctx,var));vd=verdict(r,b);out['variants'][v]=dict(variant=var,results=r,verdict=vd)
        f=r['full|2'];print(f"{name}/{v}: CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} | @5 {r['full|5']['calmar']:.3f} | H1 {r['H1|2']['calmar']:.2f} H2 {r['H2|2']['calmar']:.2f} | OLD5 {r['OLD5']['calmar']:.3f} NEW10 {r['NEW10']['calmar']:.3f} | PASS={vd['passed']}",flush=True)
    (fh.OUT/f'idea_{name}.json').write_text(json.dumps(out,indent=1,default=float));return out
