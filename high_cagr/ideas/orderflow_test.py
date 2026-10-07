"""Order-flow (taker-buy) filters on top of 2A+5A, 5 symbols. NEW DATA: Binance kline taker_buy_volume / trade count.

PRE-DECLARED after the TRAIN-only look in explore_orderflow.py (5 features inspected; thresholds read from train
quintiles, so these are train-fitted and only the validation slice is a fair check), before running this file:
  CNT13    skip when the signal bar's trade count < 1.3 x mean count of the prior 20 closed 4h bars (thin participation)
  TBR_MID  skip when the side-adjusted taker share of the signal bar is in (0.51, 0.53] (mild crowd chasing)
  BOTH     CNT13 and TBR_MID
Root entries and pyramid adds at that bar are blocked. Gates vs 2A+5A as htf_confirm.verdict.
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
from high_cagr.ideas.explore_orderflow import flow
VARIANTS={'CNT13':dict(cnt=1.3,band=None),'TBR_MID':dict(cnt=None,band=(.51,.53)),'BOTH':dict(cnt=1.3,band=(.51,.53))}
def build(ctx,v):
    c=hc.build(ctx,None);sig=c['sig']
    if v:
        for j,s in enumerate(bench.SYMBOLS):
            f=ctx['frames'][s];x=flow(s,f).iloc[np.asarray(ctx['ix'][s])];side=sig[j,:,0];on=side!=0;bad=np.zeros(len(side),bool)
            if v['cnt']:bad|=~(x.cnt_rel.to_numpy()>=v['cnt'])
            if v['band']:t=np.where(side>0,x.tbr.to_numpy(),1-x.tbr.to_numpy());bad|=(t>v['band'][0])&(t<=v['band'][1])
            sig[j,on&bad,0]=0;sig[j,on&bad,3]=-np.inf
    return dict(sig=sig,kwargs=c['kwargs'])
if __name__=='__main__':
    ctx=bench.load();out=dict(notes=__doc__,variants={});b=json.loads((bench.OUT/'htf_confirm.json').read_text())['baseline_2A5A']['results'];n0=(build(ctx,None)['sig'][:,:,0]!=0).sum()
    for name,v in VARIANTS.items():
        c=build(ctx,v);r=bench.evaluate(c,keep=True);ex=r.pop('_extra');vd=hc.verdict(r,b);kept=float((c['sig'][:,:,0]!=0).sum()/n0*100);f=r['full|2']
        out['variants'][name]=dict(variant=v,signals_kept_pct=kept,results=r,verdict=vd,passed=vd['passed'],curve=ex['curve'])
        print(f"{name}: kept {kept:.0f}% CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} win {f['win']:.1f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} (base oos {b['oos|2']['calmar']:.2f}, oos CAGR {r['oos|2']['cagr']:.1f} vs {b['oos|2']['cagr']:.1f}, oos DD {r['oos|2']['dd']:.1f} vs {b['oos|2']['dd']:.1f}) @5 {f and r['full|5']['calmar']:.3f} | PASS={vd['passed']} {[k for k,x in vd['checks'].items() if not x]}",flush=True)
    (bench.OUT/'orderflow_test.json').write_text(json.dumps(out,indent=1,default=float))
