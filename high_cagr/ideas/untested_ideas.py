"""Never-tested ideas on top of the bot default (2A+5A), 5 symbols.

PRE-DECLARED after a TRAIN-only look (explore_untested.py; 9 features inspected, validation not looked at),
before running this file:
  F4        exactly the HOLD2-validated rule: no new short when the mean of the last 9 funding prints before the
            entry boundary is < 0 (crowded shorts). Fewer than 9 prints -> not applied. Never run on 2A+5A.
  F4_SYM    F4 plus its mirror for longs: no new long when that mean is > 0.0001 (above the 0.01%/8h base rate).
  KUMO_CLR  breakout must clear the 4h Kumo edge by >= 1.0 ATR (close - kumo_top for longs, mirror for shorts).
  ROOM60    skip when the 60-bar extreme in the trade direction (prior 60 closed 4h bars) is > 2.0 ATR away
            (a 10-bar breakout deep inside a larger counter-move).
All block root entries and pyramid adds at that bar. Gates vs 2A+5A as in htf_confirm.verdict.
Hour-of-day / weekday buckets were also inspected on train but are NOT tested (no mechanism, data-mining risk).
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc
VARIANTS={'F4':dict(kind='funding',short_below=0.0,long_above=None),'F4_SYM':dict(kind='funding',short_below=0.0,long_above=1e-4),
          'KUMO_CLR':dict(kind='kumo',atr=1.0),'ROOM60':dict(kind='room',bars=60,atr=2.0)}

def funding_mean(ctx,j,nb):
    """Mean of the last 9 observed funding prints strictly before each entry boundary b*240 (NaN if < 9)."""
    fr=np.asarray(ctx['funding'][j]);idx=np.where(np.isfinite(fr))[0];vals=fr[idx];cs=np.concatenate([[0.],np.cumsum(vals)])
    k=np.searchsorted(idx,np.arange(nb)*240,side='left')     # number of prints before the boundary
    out=np.full(nb,np.nan);ok=k>=9;out[ok]=(cs[k[ok]]-cs[k[ok]-9])/9;return out

def allow(ctx,j,s,side,v):
    f=ctx['frames'][s];ix=ctx['ix'][s];nb=len(side)
    if v['kind']=='funding':
        m=funding_mean(ctx,j,nb);bad=(side<0)&(m<v['short_below'])
        if v['long_above'] is not None:bad|=(side>0)&(m>v['long_above'])
        return ~(bad&np.isfinite(m))
    atr=f.atr.to_numpy()[ix];c=f.close.to_numpy()[ix]
    if v['kind']=='kumo':
        clr=np.where(side>0,c-f.kumo_top.to_numpy()[ix],f.kumo_bottom.to_numpy()[ix]-c)/atr
        return clr>=v['atr']
    hi=f.high.rolling(v['bars']).max().shift(1).to_numpy()[ix];lo=f.low.rolling(v['bars']).min().shift(1).to_numpy()[ix]
    room=np.where(side>0,hi-c,c-lo)/atr
    return ~(room>v['atr'])

def build(ctx,v):
    c=hc.build(ctx,None);sig=c['sig']
    if v:
        for j,s in enumerate(bench.SYMBOLS):
            on=sig[j,:,0]!=0;ok=allow(ctx,j,s,sig[j,:,0],v);sig[j,on&~ok,0]=0;sig[j,on&~ok,3]=-np.inf
    return dict(sig=sig,kwargs=c['kwargs'])

if __name__=='__main__':
    ctx=bench.load();out=dict(notes=__doc__,variants={})
    base=json.loads((bench.OUT/'htf_confirm.json').read_text())['baseline_2A5A'];b=base['results'];out['baseline_2A5A']=base
    chk=bench.evaluate(build(ctx,None));assert abs(chk['full|2']['net']-b['full|2']['net'])<1e-6
    n0=(build(ctx,None)['sig'][:,:,0]!=0).sum()
    for name,v in VARIANTS.items():
        c=build(ctx,v);cz=bench.check_causal(build,v);r=bench.evaluate(c,keep=True);ex=r.pop('_extra');vd=hc.verdict(r,b)
        kept=float((c['sig'][:,:,0]!=0).sum()/n0*100);f=r['full|2']
        out['variants'][name]=dict(variant=v,causal=cz,signals_kept_pct=kept,results=r,verdict=vd,passed=bool(vd['passed'] and cz['causal']),curve=ex['curve'])
        print(f"{name}: kept {kept:.0f}% CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} win {f['win']:.1f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} @5 {r['full|5']['calmar']:.3f} | losses {f['losses']} {f['loss_sum']:.0f} NFT {f['no_follow_through']['n']} {f['no_follow_through']['loss']:.0f} | causal={cz['causal']} PASS={out['variants'][name]['passed']} {[k for k,x in vd['checks'].items() if not x]}",flush=True)
    (bench.OUT/'untested_ideas.json').write_text(json.dumps(out,indent=1,default=float))
