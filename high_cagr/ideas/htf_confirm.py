"""Higher-timeframe confirmation on top of the bot default (2A+5A), 5 symbols only.

PRE-DECLARED (written before any result of this script was seen):
  baseline : 2A (skip entry/add when ATR < median ATR of prior 60 closed 4h bars) + 5A (floor 1R -> +0.1R)
  variants : an entry (root or pyramid add) is allowed only when the LAST COMPLETED higher-timeframe bar agrees
    D_KUMO   daily close outside the daily Ichimoku Kumo (9/26/52/26) on the signal side
    D_KIJUN  daily close beyond the daily Kijun(26) on the signal side
    D_STRICT D_KUMO and daily Tenkan beyond Kijun on the signal side
    H12_KUMO 12h close outside the 12h Kumo on the signal side
  HTF bars are built from closed 4h bars (UTC days; 12h = 00-12/12-24). Missing HTF history (first weeks) -> allowed.
  gates (vs the 2A+5A baseline): G1 train and oos net > 0; G2 full Calmar >= base+0.05 at 2bps and >= base at 5bps;
  G3 full maxDD <= base; G4 Calmar not worse in train and in oos.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, combo
H4=4*3600*1000
FIVE_A=dict(floor_on=True,floor_trigger=1.0,floor_lock=0.1)
VARIANTS={'D_KUMO':dict(hours=24,rule='kumo'),'D_KIJUN':dict(hours=24,rule='kijun'),'D_STRICT':dict(hours=24,rule='strict'),'H12_KUMO':dict(hours=12,rule='kumo')}

def htf_state(f,hours):
    """Per closed 4h row: (last completed HTF close, kumo top/bottom, tenkan, kijun) known at that row."""
    n=hours//4;ts=f.timestamp.to_numpy(np.int64);period=hours*3600*1000
    g=pd.DataFrame({'k':ts//period,'high':f.high.to_numpy(),'low':f.low.to_numpy(),'close':f.close.to_numpy(),'cnt':1})
    h=g.groupby('k').agg(high=('high','max'),low=('low','min'),close=('close','last'),cnt=('cnt','sum'))
    mid=lambda w:(h.high.rolling(w).max()+h.low.rolling(w).min())/2
    tenkan,kijun,sb=mid(9),mid(26),mid(52);sa=(tenkan+kijun)/2
    h['top']=np.maximum(sa.shift(26),sb.shift(26));h['bot']=np.minimum(sa.shift(26),sb.shift(26));h['tenkan']=tenkan;h['kijun']=kijun
    h.loc[h.cnt<n,['close','top','bot','tenkan','kijun']]=np.nan     # incomplete HTF bar is never used
    # HTF bar k is complete at the 4h row whose open is the last slot of k
    done=np.where((ts%period)==period-H4)[0];keys=ts[done]//period
    cols=h.reindex(keys)[['close','top','bot','tenkan','kijun']].to_numpy()
    return done,cols

def allow(f,ix,side,v):
    done,cols=htf_state(f,v['hours']);k=np.searchsorted(done,np.asarray(ix),side='right')-1
    c=np.where(k[:,None]>=0,cols[np.clip(k,0,None)],np.nan);close,top,bot,ten,kij=c.T
    if v['rule']=='kijun':up,dn=close>kij,close<kij
    else:
        up,dn=close>top,close<bot
        if v['rule']=='strict':up,dn=up&(ten>kij),dn&(ten<kij)
    unknown=~np.isfinite(close)|~np.isfinite(kij if v['rule']=='kijun' else top)
    return unknown|((side>0)&up)|((side<0)&dn)

def build(ctx,v):
    sig=combo.apply_filters(ctx,bench.base_sig(),{'idea2_atr_regime':('A',None)})
    if v:
        for j,s in enumerate(bench.SYMBOLS):
            ok=allow(ctx['frames'][s],ctx['ix'][s],sig[j,:,0],v);on=sig[j,:,0]!=0
            sig[j,on&~ok,0]=0;sig[j,on&~ok,3]=-np.inf
    return dict(sig=sig,kwargs=dict(FIVE_A))

def verdict(r,b):
    ck={'G1_train_oos_positive':r['train|2']['net']>0 and r['oos|2']['net']>0,
        'G2_calmar_up':r['full|2']['calmar']>=b['full|2']['calmar']+.05 and r['full|5']['calmar']>=b['full|5']['calmar'],
        'G3_dd_not_worse':r['full|2']['dd']<=b['full|2']['dd'],
        'G4_calmar_both_slices':r['train|2']['calmar']>=b['train|2']['calmar'] and r['oos|2']['calmar']>=b['oos|2']['calmar']}
    return dict(checks=ck,passed=all(ck.values()))

if __name__=='__main__':
    ctx=bench.load();out=dict(notes=__doc__,variants={})
    base=bench.evaluate(build(ctx,None),keep=True);bex=base.pop('_extra');out['baseline_2A5A']=dict(results=base,curve=bex['curve'])
    f=base['full|2'];print(f"2A+5A base: CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} | train {base['train|2']['calmar']:.2f} oos {base['oos|2']['calmar']:.2f} @5 {base['full|5']['calmar']:.3f}",flush=True)
    for name,v in VARIANTS.items():
        c=build(ctx,v);cz=bench.check_causal(build,v);r=bench.evaluate(c,keep=True);ex=r.pop('_extra');vd=verdict(r,base)
        kept=float((c['sig'][:,:,0]!=0).sum()/(build(ctx,None)['sig'][:,:,0]!=0).sum()*100)
        out['variants'][name]=dict(variant=v,causal=cz,signals_kept_pct=kept,results=r,verdict=vd,passed=bool(vd['passed'] and cz['causal']),curve=ex['curve'])
        f=r['full|2'];print(f"{name}: kept {kept:.0f}% CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} @5 {r['full|5']['calmar']:.3f} | NFT {f['no_follow_through']['n']} {f['no_follow_through']['loss']:.0f} | causal={cz['causal']} PASS={out['variants'][name]['passed']} {vd['checks']}",flush=True)
    (bench.OUT/'htf_confirm.json').write_text(json.dumps(out,indent=1,default=float))
