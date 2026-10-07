"""Round-2 part A: AND-combinations of verified single filters, exactly as declared in predeclared_round2.json."""
from pathlib import Path
import sys,json,itertools,importlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import fb_harness as h
TOP=[('confirmation','B'),('volume','A'),('htf_trend','B'),('squeeze','A'),('breadth','A'),('adx','A')]
COMBOS=[list(c) for c in itertools.combinations(TOP,2)]+[[('confirmation','B'),('volume','A'),('htf_trend','B')],[('confirmation','B'),('volume','A'),('squeeze','A')]]
def mask_of(parts,ctx):
    out={s:np.ones(len(ctx['side'][s]),bool) for s in h.SYMBOLS}
    for m,v in parts:
        mod=importlib.import_module(f'high_cagr.fb.m_{m}');mk=mod.mask_fn(ctx['frames'],ctx['ix'],ctx['side'],mod.VARIANTS[v])
        for s in h.SYMBOLS:out[s]&=np.asarray(mk[s],bool)
    return out
def fb_cost(t):
    roots=t[t[:,18]==0];cost=0.;n=0
    for r in roots:
        net=t[t[:,17]==r[17],12].sum()
        if net<0 and r[19]<.3:cost+=net/r[14];n+=1
    return n,cost*100
def evaluate(mask):
    ctx=h.load();res={}
    for bps in (2,5):
        for per in h.PERIODS:
            row,t=h._run(ctx,mask,h.SYMBOLS,6,bps,per);res[f'{per}|{bps}']=row
            if per=='full' and bps==2:res['fb_n'],res['fb_cost_pct']=fb_cost(t)
    for name,syms in (('OLD5',h.OLD),('NEW10',h.NEW)):res[name]=h._run(ctx,mask,syms,4,2,'full')[0]
    return res
def verdict(r,b):
    c={}
    for bps in (2,5):
        c[f'positive|{bps}']=all(r[f'{p}|{bps}']['net']>0 for p in ('H1','H2','Y2026'))
        c[f'calmar+0.05|{bps}']=r[f'full|{bps}']['calmar']>=b[f'full|{bps}']['calmar']+.05
        c[f'dd_not_worse|{bps}']=r[f'full|{bps}']['dd']<=b[f'full|{bps}']['dd']
        c[f'both_halves|{bps}']=all(r[f'{p}|{bps}']['calmar']>=b[f'{p}|{bps}']['calmar'] for p in ('H1','H2'))
    c['fb_cost_cut_15pct']=r['fb_cost_pct']>=.85*b['fb_cost_pct'];c['subsets']=r['OLD5']['calmar']>=b['OLD5']['calmar'] and r['NEW10']['calmar']>=b['NEW10']['calmar']
    return dict(checks=c,passed=all(c.values()))
def main():
    ctx=h.load();b=evaluate(None);out=dict(baseline=b,combos={})
    print(f"BASE Calmar {b['full|2']['calmar']:.3f} FB cost {b['fb_cost_pct']:.1f}%eq",flush=True)
    for parts in COMBOS:
        name='+'.join(f'{m}.{v}' for m,v in parts);m=mask_of(parts,ctx)
        kept=sum(int(((ctx['side'][s]!=0)&m[s]).sum()) for s in h.SYMBOLS)/sum(int((ctx['side'][s]!=0).sum()) for s in h.SYMBOLS)*100
        r=evaluate(m);v=verdict(r,b);out['combos'][name]=dict(kept_pct=kept,results=r,verdict=v);f=r['full|2']
        print(f"{name:45} kept {kept:4.1f}% | CAGR {f['cagr']:6.2f} DD {f['dd']:5.2f} Calmar {f['calmar']:.3f} @5 {r['full|5']['calmar']:.3f} | H1 {r['H1|2']['calmar']:.2f} H2 {r['H2|2']['calmar']:.2f} | OLD5 {r['OLD5']['calmar']:.2f} NEW10 {r['NEW10']['calmar']:.2f} | FB {r['fb_cost_pct']:.0f}%eq | {'PASS' if v['passed'] else 'FAIL '+','.join(k for k,x in v['checks'].items() if not x)}",flush=True)
        (h.OUT/'combos_results.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
