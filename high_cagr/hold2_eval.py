"""Confirmatory HOLD2 test of F4 (output/r3/predeclared_hold2.json). Same engine as r3_harness; universe added at runtime."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import r3_harness as h, run_suite as rs, fb_harness as fh
from high_cagr.fb.r3_lead_funding_b2 import VARIANTS,build_fn
from high_cagr.r3_thinning_null import thin
HOLD2=[c['symbol'] for c in json.loads((ROOT/'high_cagr/output/stage4_selection.json').read_text())['chosen']]
h.UNIVERSES['HOLD2']=HOLD2

def stats(U,c,per,bps):
    a,t,curve=h._sim(U,c,per,bps);s=rs.summarize(a,t,curve,*fh.PERIODS[per],U['symbols'])
    return dict(cagr=s['cagr_pct'],dd=s['max_dd_pct'],calmar=s['cagr_pct']/s['max_dd_pct'],roots=s['root_entries'],net=s['net_profit'])

def run(U,c):
    r={f'{p}|2':stats(U,c,p,2) for p in h.PER};r['full|5']=stats(U,c,'full',5);return r

def main():
    assert len(HOLD2)==10;U=h.universe('HOLD2');print('HOLD2',HOLD2,flush=True)
    res=dict(symbols=HOLD2,baseline=run(U,{}))
    cz=h.check_causal(build_fn,VARIANTS['F4_short_neg'])
    for v in ('F4_short_neg','F1_pct80_fix'):res[v]=run(U,build_fn(U,VARIANTS[v]))
    b=res['baseline'];f=res['F4_short_neg'];cut=1-f['full|2']['roots']/b['full|2']['roots'];p=max(.05,round(cut/.05)*.05)
    null=[]
    for sd in range(30):
        rng=np.random.default_rng(5000+sd);null.append(stats(U,{'sig':thin(U,p,rng)},'full',2)['calmar'])
    p90=float(np.percentile(null,90))
    checks={'calmar_2bps_up':f['full|2']['calmar']>b['full|2']['calmar'],'calmar_5bps_up':f['full|5']['calmar']>b['full|5']['calmar'],
            'dd_not_worse_1pt':f['full|2']['dd']<=b['full|2']['dd']+1.,
            'subperiods_2of3':sum(f[f'{q}|2']['calmar']>=b[f'{q}|2']['calmar'] for q in ('H1','H2','Y2026'))>=2,
            'above_thinning_p90':f['full|2']['calmar']>p90}
    res.update(causal=cz,root_cut=cut,null_p=p,null=dict(p10=float(np.percentile(null,10)),p50=float(np.median(null)),p90=p90),
               checks={k:bool(x) for k,x in checks.items()},passed=bool(all(checks.values()) and cz['causal']))
    (h.OUT/'hold2_results.json').write_text(json.dumps(res,indent=1,default=float))
    for k in ('baseline','F4_short_neg','F1_pct80_fix'):
        x=res[k];print(f"{k:14s} full@2 Calmar {x['full|2']['calmar']:.2f} CAGR {x['full|2']['cagr']:.1f} DD {x['full|2']['dd']:.1f} roots {x['full|2']['roots']} | @5 {x['full|5']['calmar']:.2f} | H1 {x['H1|2']['calmar']:.2f} H2 {x['H2|2']['calmar']:.2f} 2026 {x['Y2026|2']['calmar']:.2f}")
    print('root cut',round(cut,3),'null',res['null'],'causal',cz,'checks',res['checks'],'PASS',res['passed'])

if __name__=='__main__':main()
