"""Run every pre-declared variant (PREDECLARED.md) through ALONE / ACCOUNT / OTHER30 and apply the gates S1-S3."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.shahin2 import lab as LB

def variants():
    v={'baseline (shipped)':{},'late: none':dict(late=(0,0,'skip')),'late: 60 bars, half size':dict(late=(60,.1521,'half'))}
    for L in (30,60,120):
        th=LB.thresholds(L)
        for q,t in th.items():v[f'late: {L} bars q{int(q*100)} ({t:.3f})']=dict(late=(L,t,'skip'))
    for k,kw in {'same-side cap 2':dict(same_side_cap=2),'same-side cap 3':dict(same_side_cap=3),'max 1 new per bar':dict(max_new_per_bar=1),
                 'shorts x0.5':dict(short_risk_mult=.5),'pyramid risk x0.3':dict(pyr_risk_mult=.3),'pyramid risk x0.75':dict(pyr_risk_mult=.75),
                 'pilot half, rest at +0.5R':dict(pilot_frac=.5,pilot_trigger=.5),
                 'floor 0.75R->0.1R':dict(floor_trigger=.75,floor_lock=.1),'floor 1R->0.3R':dict(floor_trigger=1.,floor_lock=.3),
                 'floor 1.5R->0.3R':dict(floor_trigger=1.5,floor_lock=.3),'floor 2R->0.5R':dict(floor_trigger=2.,floor_lock=.5),
                 'partial 1/3 at 2R':dict(partial_frac=1/3,partial_r=2.),'partial 1/2 at 3R':dict(partial_frac=.5,partial_r=3.),
                 'time stop 3 bars MFE<0.5R':dict(time_stop_bars=3,time_stop_mfe=.5),'time stop 6 bars MFE<0.5R':dict(time_stop_bars=6,time_stop_mfe=.5),
                 'tight trail after 2R':dict(tight_after_r=2.,tight_cols=6),'tight trail after 3R':dict(tight_after_r=3.,tight_cols=6),
                 'stale guard 6 bars':dict(stale_bars=6,stale_mfe=.4,stale_cols=6),
                 'failed breakout exit (level)':dict(fail_exit_mode=1),'failed breakout exit (Kumo)':dict(fail_exit_mode=2)}.items():
        v[k]=dict(kw=kw)
    for n in (3,5,6):v[f'slots {n}']=dict(slots=n)
    v['no pyramid']=dict(pyramid=False);v['ATR-regime filter off']=dict(atr_filter=False)
    return v

def main():
    LB.OUT.mkdir(parents=True,exist_ok=True);res={};V=variants()
    for name,v in V.items():
        legs,alone=LB.run(LB.MAIN5,v);_,o30=LB.run(LB.OTHER30,v);acc=LB.account(legs)
        res[name]=dict(variant={k:(list(x) if isinstance(x,tuple) else x) for k,x in v.items()},alone=alone,account=acc,other30=o30)
        a,c,o=alone,acc,o30
        print(f"{name:34s} ALONE CAGR {a['full'][1]:5.1f} DD {a['full'][2]:4.1f} Cal tr {a['train'][0]:.2f} va {a['valid'][0]:.2f} WR {a['win']:.1f} | ACCOUNT CAGR {c['full'][1]:5.1f} DD {c['full'][2]:4.1f} Cal tr {c['train'][0]:.2f} va {c['valid'][0]:.2f} | OTHER30 Cal {o['full'][0]:.2f} CAGR {o['full'][1]:.1f} DD {o['full'][2]:.1f}",flush=True)
    b=res['baseline (shipped)']
    for name,r in res.items():
        a,c,o=r['alone'],r['account'],r['other30']
        g=dict(S1=a['train'][0]>=1.05*b['alone']['train'][0] and a['valid'][0]>=1.05*b['alone']['valid'][0],
               S2=c['train'][0]>=b['account']['train'][0] and c['valid'][0]>=b['account']['valid'][0] and c['full'][2]<=b['account']['full'][2]+1,
               S3=o['full'][0]>=b['other30']['full'][0])
        r['gates']=g;r['passed']=bool(all(g.values()) and name!='baseline (shipped)')
    print('PASSED:',[n for n,r in res.items() if r['passed']]);(LB.OUT/'variants.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
