"""Frozen bench for the CHOP study (output/fb/predeclared_chop.json). DO NOT EDIT from an agent.

Baseline = validated package: 15 symbols, 6 slots, R=0.75%, 4B + V2 + BTC gate + initial stop 2.5 ATR.
A candidate is build_fn(ctx, variant) -> dict with any of 'sig', 'bb', 'kwargs' that REPLACE/extend the
baseline ones. Start from base_sig()/base_bb() copies. bb has 12 columns: 0 low line, 1 atr, 2 close,
3 high line, 4/5 3-bar low/high, 6/7 4-bar low/high, 8/9 breakout level long/short (max(donchian_high_10,
kumo_top) / min(donchian_low_10, kumo_bottom)), 10/11 Kumo edge long/short (kumo_top / kumo_bottom).
"""
from pathlib import Path
import sys,json,functools
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import fb_harness as fh, imp_harness as ih, run_suite as rs
from high_cagr.kernel_fixes import simulate
SYM=fh.SYMBOLS;OUT=fh.OUT
@functools.lru_cache(1)
def _base():
    ctx=fh.load();sig=ctx['sig'].copy();extra=[]
    for j,s in enumerate(SYM):
        f=ctx['frames'][s];ix=ctx['ix'][s];atr=f.atr.to_numpy()[ix];sd=sig[j,:,0];sig[j,:,2]=np.where(sd!=0,sig[j,:,1]-sd*2.5*atr,sig[j,:,2])
        g=lambda c:f[c].to_numpy()[ix]
        extra.append(np.column_stack([np.maximum(g('donchian_high_10'),g('kumo_top')),np.minimum(g('donchian_low_10'),g('kumo_bottom')),g('kumo_top'),g('kumo_bottom')]))
    bb=np.concatenate([ctx['bb'],np.stack(extra)],axis=2);return sig,bb
def base_sig():return _base()[0].copy()
def base_bb():return _base()[1].copy()
def _merge(c):
    sig,bb=_base();return {'sig':c.get('sig',sig),'bb':c.get('bb',bb),'kwargs':c.get('kwargs',{}),'slots':c.get('slots',6),'risk':c.get('risk',fh.RISK)}
def _ledger(c):
    """CHOP/FB cost (% of equity at entry) on the full period @2bps."""
    ctx=fh.load();kw={**fh.POLICY,**c['kwargs']};pyr=kw.pop('pyramid',True);b,e=fh.PERIODS['full']
    a,t,_=simulate(ctx['prices'],ctx['funding'],np.ascontiguousarray(c['sig']),np.ascontiguousarray(c['bb']),rs.START,b,e,c['risk'],c['slots'],ctx['step'],pyr,slip=2e-4,**kw)
    chop=fb=0.;nc=nf=0
    for r in t[t[:,18]==0]:
        legs=t[t[:,17]==r[17]];net=legs[:,12].sum()
        if net<0 and legs[:,9].sum()<0 and r[19]<1:
            if r[19]<.3:fb+=net/r[14];nf+=1
            else:chop+=net/r[14];nc+=1
    return dict(chop_n=nc,chop_cost_pct=chop*100,fb_n=nf,fb_cost_pct=fb*100,chop_exits=int(a[20]),partials=int(a[21]))
def evaluate(c):
    m=_merge(c);r=ih.evaluate(m);r['ledger']=_ledger(m);return r
@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline_chop.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate({});p.write_text(json.dumps(r,indent=1));return r
def verdict(r):
    b=baseline();v=ih.verdict(r,b);v['checks']['chop_cost_cut_15pct']=r['ledger']['chop_cost_pct']>=.85*b['ledger']['chop_cost_pct'];v['passed']=all(v['checks'].values());return v
def run_idea(name,variants,build_fn,notes=''):
    b=baseline();ctx=fh.load();out=dict(idea=name,notes=notes,baseline=b,variants={})
    for v,var in variants.items():
        r=evaluate(build_fn(ctx,var));vd=verdict(r);out['variants'][v]=dict(variant=var,results=r,verdict=vd);f=r['full|2'];L=r['ledger']
        print(f"{name}/{v}: CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} | @5 {r['full|5']['calmar']:.3f} | H1 {r['H1|2']['calmar']:.2f} H2 {r['H2|2']['calmar']:.2f} | OLD5 {r['OLD5']['calmar']:.3f} NEW10 {r['NEW10']['calmar']:.3f} | CHOP {L['chop_n']} {L['chop_cost_pct']:.1f}%eq | PASS={vd['passed']}",flush=True)
    (OUT/f'chop_{name}.json').write_text(json.dumps(out,indent=1,default=float));return out
