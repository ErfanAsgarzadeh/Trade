"""Pilot-entry experiment exactly as declared in output/fb/predeclared_pilot.json."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import fb_harness as h, run_suite as rs
from high_cagr.kernel_fixes import simulate
D=json.loads((h.OUT/'predeclared_pilot.json').read_text());VARIANTS={'BASE':{},**D['variants']}
def run(ctx,extra,symbols,slots,bps,period):
    g,k=h._apply(ctx,None,symbols);name='ALL15' if len(k)==len(h.SYMBOLS) else ('OLD5' if symbols==h.OLD else 'NEW10')
    b,e=h.PERIODS[period];a,t,curve=simulate(h._stacked('prices',name,symbols),h._stacked('funding',name,symbols),g,np.ascontiguousarray(ctx['bb'][k]),rs.START,b,e,h.RISK,slots,ctx['step'],True,slip=bps/1e4,**h.POLICY,**extra)
    r=rs.summarize(a,t,curve,b,e,symbols);return dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'],win=r['win_rate_pct'],completions=int(a[19])),t
def ledger(t,extra):
    roots=t[t[:,18]==0];rows=[]
    for r in roots:
        legs=t[t[:,17]==r[17]];rows.append(dict(net=legs[:,12].sum(),eq0=r[14],mfe=r[19],sym=int(r[0]),ts=int(r[1]),completed=bool((legs[:,18]==2).any())))
    p=pd.DataFrame(rows);fb=p[(p.net<0)&(p.mfe<.3)]
    if extra:   # invariants of the pilot mechanism
        comp=t[t[:,18]==2]
        for c in comp:
            root=t[int(c[17])];assert root[19]>=extra['pilot_trigger']-1e-9 and c[1]>root[1],'completion before trigger'
            assert root[15]/root[14]<=extra['pilot_frac']*h.RISK*(1+1e-9),'pilot risk too large'
            assert (root[15]+c[15])<=root[14]*h.RISK*(1+1e-6),'total risk above budget'
    return dict(fb_n=int(len(fb)),fb_cost_pct_equity=float((fb.net/fb.eq0).sum()*100),positions=len(p),completed_pct=float(p.completed.mean()*100),win_rate=float((p.net>0).mean()*100)),p
def main():
    ctx=h.load();res={};base_top=None
    for name,extra in VARIANTS.items():
        row={}
        for bps in (2,5):
            for per in h.PERIODS:
                r,t=run(ctx,extra,h.SYMBOLS,6,bps,per);row[f'{per}|{bps}']=r
                if per=='full' and bps==2:
                    L,p=ledger(t,extra);row['ledger']=L
                    if name=='BASE':base_top=p.sort_values('net',ascending=False).head(25)
                    keys={(a,b):n for a,b,n in zip(p.sym,p.ts,p.net)};row['top25_ratio']=float(sum(keys.get((a,b),0.) for a,b in zip(base_top.sym,base_top.ts))/base_top.net.sum())
        for sub,syms in (('OLD5',h.OLD),('NEW10',h.NEW)):row[sub]=run(ctx,extra,syms,4,2,'full')[0]
        res[name]=row;f=row['full|2']
        print(f"{name:5} CAGR {f['cagr']:6.2f} DD {f['dd']:6.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} | @5 Calmar {row['full|5']['calmar']:.3f} DD {row['full|5']['dd']:.2f} | H1 {row['H1|2']['calmar']:.2f} H2 {row['H2|2']['calmar']:.2f} 26 {row['Y2026|2']['calmar']:.2f} | OLD5 {row['OLD5']['calmar']:.3f} NEW10 {row['NEW10']['calmar']:.3f} | FB {row['ledger']['fb_n']} cost {row['ledger']['fb_cost_pct_equity']:.1f}%eq | completed {row['ledger']['completed_pct']:.0f}% win {row['ledger']['win_rate']:.1f}% top25 {row['top25_ratio']:.2f}",flush=True)
    B=res['BASE'];verd={}
    for name in D['variants']:
        x=res[name];c={}
        for bps in (2,5):
            c[f'positive|{bps}']=all(x[f'{p}|{bps}']['net']>0 for p in ('H1','H2','Y2026'))
            c[f'calmar+0.05|{bps}']=x[f'full|{bps}']['calmar']>=B[f'full|{bps}']['calmar']+.05
            c[f'dd_not_worse|{bps}']=x[f'full|{bps}']['dd']<=B[f'full|{bps}']['dd']
            c[f'both_halves|{bps}']=all(x[f'{p}|{bps}']['calmar']>=B[f'{p}|{bps}']['calmar'] for p in ('H1','H2'))
        c['fb_cost_cut_25pct']=x['ledger']['fb_cost_pct_equity']>=.75*B['ledger']['fb_cost_pct_equity']
        c['subsets']=x['OLD5']['calmar']>=B['OLD5']['calmar'] and x['NEW10']['calmar']>=B['NEW10']['calmar']
        verd[name]=dict(checks=c,passed=all(c.values()));print(name,'PASS' if verd[name]['passed'] else 'FAIL '+', '.join(k for k,v in c.items() if not v))
    (h.OUT/'pilot_results.json').write_text(json.dumps(dict(results=res,verdicts=verd),indent=1,default=float))
if __name__=='__main__':main()
