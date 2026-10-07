"""Fast re-entry after a profitable exit, on top of 2A+5A, 5 symbols.

Motivation (trend_audit.py, hindsight diagnosis): inside 111 trends >=30%, 57% of the trend move happened while the
bot was flat with no fresh 10-bar breakout, i.e. after the trail took it out it waited for a new 10-bar extreme.
PRE-DECLARED before running (kernel switch reentry_bars, causal: uses only the symbol's last closed root leg):
  if the symbol's last root leg closed IN PROFIT (direction d) at most 30 entry bars (5 days) ago and no position is
  open, a same-direction entry is also allowed when the closed 4h close breaks the prior N-bar high (low for shorts)
  and is outside the 4h Kumo on side d; stop = close -/+ 2 ATR as usual; sizing/slots/REJECT unchanged.
    RE3_2A    N=3, the ATR filter 2A also applies to these re-entries
    RE5_2A    N=5, 2A applies
    RE3_NO2A  N=3, re-entries exempt from 2A (trend continuation in calm bars)
Gates vs 2A+5A as htf_confirm.verdict.
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc, combo
VARIANTS={'RE3_2A':dict(n=3,atr=True),'RE5_2A':dict(n=5,atr=True),'RE3_NO2A':dict(n=3,atr=False)}
K=30

def build(ctx,v):
    c=hc.build(ctx,None);sig=c['sig']
    if not v:return c
    _,atr_rel=combo.features(ctx);extra=np.zeros(sig.shape[:2]+(2,))
    for j,s in enumerate(bench.SYMBOLS):
        f=ctx['frames'][s];ix=ctx['ix'][s];cl=f.close.to_numpy()[ix];atr=f.atr.to_numpy()[ix]
        hi=f.high.rolling(v['n']).max().shift(1).to_numpy()[ix];lo=f.low.rolling(v['n']).min().shift(1).to_numpy()[ix]
        side=((cl>hi)&(cl>f.kumo_top.to_numpy()[ix])).astype(float)-((cl<lo)&(cl<f.kumo_bottom.to_numpy()[ix])).astype(float)
        if v['atr']:side[atr_rel[s]<1.0]=0
        extra[j,:,0]=side;extra[j,:,1]=cl-side*2*atr
    kw=dict(c['kwargs'],reentry_bars=K,reentry_col=sig.shape[2])
    return dict(sig=np.concatenate([sig,extra],axis=2),kwargs=kw)

if __name__=='__main__':
    ctx=bench.load();out=dict(notes=__doc__,variants={});b=json.loads((bench.OUT/'htf_confirm.json').read_text())['baseline_2A5A']['results']
    for name,v in VARIANTS.items():
        c=build(ctx,v);cz=bench.check_causal(build,v);r=bench.evaluate(c,keep=True);ex=r.pop('_extra');vd=hc.verdict(r,b);f=r['full|2']
        out['variants'][name]=dict(variant=v,causal=cz,results=r,verdict=vd,passed=bool(vd['passed'] and cz['causal']),curve=ex['curve'])
        print(f"{name}: roots {f['roots']} CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} net {f['net']:.0f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} @5 {r['full|5']['calmar']:.3f} | causal={cz['causal']} PASS={out['variants'][name]['passed']} {[k for k,x in vd['checks'].items() if not x]}",flush=True)
    (bench.OUT/'reentry_test.json').write_text(json.dumps(out,indent=1,default=float))
