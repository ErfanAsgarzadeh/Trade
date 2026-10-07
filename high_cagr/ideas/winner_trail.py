"""Winner-side test on top of 2A+5A, 5 symbols: change the trail only after a trade has proven itself.

Context (full-period 2A+5A ledger, computed before this file was written): positions with peak >= 3R keep ~48% of
their peak on average (3-5R: peak 3.8R -> exit 1.4R; 5-10R: 6.8R -> 3.9R; >=10R: 15.5R -> 10.8R).
PRE-DECLARED before running (kernel switch tight_after_r: once root MFE >= X the trail/close line uses other bars):
  WIDE20_3R  after 3R trail on the 20-bar channel (lowest low / highest high incl. current closed 4h bar) instead of 10
  WIDE20_5R  same after 5R
  WIDE15_3R  15-bar channel after 3R
  TIGHT4_5R  opposite direction: 4-bar channel after 5R (lock in the giant runs; 2R version already failed as idea 5C)
Ratchet stays (a wider line never loosens the existing stop; it only stops tightening and moves the close-exit line).
Gates vs 2A+5A as htf_confirm.verdict (G1-G4).
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
VARIANTS={'WIDE20_3R':dict(r=3.,col=12),'WIDE20_5R':dict(r=5.,col=12),'WIDE15_3R':dict(r=3.,col=14),'TIGHT4_5R':dict(r=5.,col=6)}

def channels(ctx):
    cols=[]
    for s in bench.SYMBOLS:
        f=ctx['frames'][s];ix=ctx['ix'][s]
        cols.append(np.column_stack([f.low.rolling(20).min().to_numpy()[ix],f.high.rolling(20).max().to_numpy()[ix],
                                     f.low.rolling(15).min().to_numpy()[ix],f.high.rolling(15).max().to_numpy()[ix]]))
    return np.stack(cols)

def build(ctx,v):
    c=hc.build(ctx,None);bb=np.concatenate([bench.base_bb(),channels(ctx)],axis=2)
    kw=dict(c['kwargs'])
    if v:kw.update(tight_after_r=v['r'],tight_cols=v['col'])
    return dict(sig=c['sig'],bb=bb,kwargs=kw)

if __name__=='__main__':
    ctx=bench.load();out=dict(notes=__doc__,variants={});b=json.loads((bench.OUT/'htf_confirm.json').read_text())['baseline_2A5A']['results']
    chk=bench.evaluate(build(ctx,None));assert abs(chk['full|2']['net']-b['full|2']['net'])<1e-6   # extra bb columns change nothing
    for name,v in VARIANTS.items():
        c=build(ctx,v);cz=bench.check_causal(build,v);r=bench.evaluate(c,keep=True);ex=r.pop('_extra');vd=hc.verdict(r,b);f=r['full|2']
        p=ex['positions'];p['R']=p.net/p.risk_usd;big=p[p.mfe_r>=3]
        out['variants'][name]=dict(variant=v,causal=cz,results=r,verdict=vd,passed=bool(vd['passed'] and cz['causal']),curve=ex['curve'],
                                   big=dict(n=int(len(big)),mean_peak=float(big.mfe_r.mean()),mean_exit_R=float(big.R.mean()),net=float(big.net.sum())))
        print(f"{name}: CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} net {f['net']:.0f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} @5 {r['full|5']['calmar']:.3f} | >=3R: n {len(big)} peak {big.mfe_r.mean():.2f} exitR {big.R.mean():.2f} | causal={cz['causal']} PASS={out['variants'][name]['passed']} {[k for k,x in vd['checks'].items() if not x]}",flush=True)
    (bench.OUT/'winner_trail.json').write_text(json.dumps(out,indent=1,default=float))
