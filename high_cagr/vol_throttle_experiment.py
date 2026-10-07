"""Runs the experiment exactly as declared in output/predeclared_vol_throttle.json (no variants added)."""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
D=json.loads((ab.OUT/'predeclared_vol_throttle.json').read_text())
def minute(date):return int((pd.Timestamp(date,tz='UTC').timestamp()*1000-rs.START)//60000)
PERIODS={k:(minute(a),minute(b)) for k,(a,b) in D['periods'].items()}
V={'0':{},'V1':{k:v for k,v in D['variants']['V1'].items() if k!='note'},'V2':{k:v for k,v in D['variants']['V2'].items() if k!='note'}}
T={'0':{},'T1':{k:v for k,v in D['variants']['T1'].items() if k!='note'},'T2':{k:v for k,v in D['variants']['T2'].items() if k!='note'}}
def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in rs.SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in rs.SYMBOLS]);frames=rs.load_frames()
    case,ss,bb,step=ab.build(.0075,frames);policies={}
    for v,t in itertools.product(V,T):policies['4B (reference)' if (v,t)==('0','0') else '+'.join(x for x in (v,t) if x!='0')]={**ab.FIX4['4B'],**V[v],**T[t]}
    res={}
    for bps in D['slippage_bps_per_fill']:
        for name,policy in policies.items():
            row={}
            for period,(b,e) in PERIODS.items():
                a,t,curve=simulate(prices,funding,ss,bb,rs.START,b,e,case['risk'],4,step,True,slip=bps/1e4,**policy);r=rs.summarize(a,t,curve,b,e,case['symbols'])
                row[period]=dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'],vol_rejects=int(a[17]),throttled_units=int(a[18]))
                if period=='full' and policy.get('vol_max_pct'):
                    roots=t[t[:,18]==0];assert (roots[:,7]/roots[:,4]<=policy['vol_max_pct']*1.05).all(),'stop width cap breached'
            res[f'{name}|{bps}']=row
    verdicts={}
    for bps in D['slippage_bps_per_fill']:
        ref=res[f'4B (reference)|{bps}']
        for name in policies:
            if name.startswith('4B'):continue
            r=res[f'{name}|{bps}'];f=r['full'];rf=ref['full']
            cagr_ok=f['cagr']>=30 if bps==2 else f['cagr']>=.9*rf['cagr']
            checks=dict(positive_H1_H2_2026=all(r[p]['net']>0 for p in ('H1','H2','Y2026')),calmar_up_0p05=f['calmar']>=rf['calmar']+.05,dd_lower=f['dd']<rf['dd'],cagr_floor=bool(cagr_ok),
                        both_halves=all(r[p]['calmar']>=ref[p]['calmar'] for p in ('H1','H2')))
            verdicts[f'{name}|{bps}']=dict(checks=checks,accepted=all(checks.values()))
    out=dict(results=res,verdicts=verdicts)
    (ab.OUT/'vol_throttle_results.json').write_text(json.dumps(out,indent=1,default=float))
    for bps in D['slippage_bps_per_fill']:
        print(f'--- slippage {bps}bps/fill: full CAGR / DD / Calmar | Calmar H1 / H2 / 2026 | net H1,H2,2026 | verdict')
        for name in policies:
            r=res[f'{name}|{bps}'];f=r['full'];v=verdicts.get(f'{name}|{bps}',{})
            print(f"{name:14} {f['cagr']:6.2f} {f['dd']:6.2f} {f['calmar']:.3f} | {r['H1']['calmar']:.2f} {r['H2']['calmar']:.2f} {r['Y2026']['calmar']:.2f} | {r['H1']['net']:7.0f} {r['H2']['net']:7.0f} {r['Y2026']['net']:7.0f} | {'ACCEPTED' if v.get('accepted') else ('REJECTED '+','.join(k for k,x in v['checks'].items() if not x)) if v else 'reference'} | skip{f['vol_rejects']} thr{f['throttled_units']}")
if __name__=='__main__':main()
