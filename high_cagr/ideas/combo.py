"""Pre-declared combo: for each idea the variant with the highest full|2 Calmar, all five together.
Entry features are recomputed here for whatever signal set results (needed when the confirmation idea moves
entries to b+1); on the baseline signal set they are checked against each idea's own build()."""
from pathlib import Path
import sys,json,importlib
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench
IDEAS=['idea1_volume','idea2_atr_regime','idea3_time_stop','idea4_confirmation','idea5_giveback']

def best():
    pick={}
    for n in IDEAS:
        d=json.loads((bench.OUT/f'{n}.json').read_text());v=max(d['variants'],key=lambda k:d['variants'][k]['results']['full|2']['calmar']);pick[n]=(v,d['variants'][v]['variant'])
    return pick

def features(ctx):
    vol={};atr={}
    for s in bench.SYMBOLS:
        f=ctx['frames'][s];ix=ctx['ix'][s]
        m=f.volume.rolling(20).mean().shift(1).to_numpy()[ix];v=f.volume.to_numpy()[ix]
        vol[s]=np.where(np.isfinite(m)&(m>0),v/np.where(m>0,m,1),0.)
        md=f.atr.rolling(60).median().shift(1).to_numpy()[ix];a=f.atr.to_numpy()[ix]
        atr[s]=np.where(np.isfinite(md)&(md>0),a/np.where(md>0,md,1),0.)
    return vol,atr

def apply_filters(ctx,sig,pick):
    vol,atr=features(ctx);sig=np.asarray(sig,dtype=float).copy()
    if sig.shape[2]<5:sig=np.concatenate([sig,np.ones(sig.shape[:2]+(1,))],axis=2)
    for j,s in enumerate(bench.SYMBOLS):
        on=sig[j,:,0]!=0
        for name,low in (('idea1_volume',vol[s]<1.5),('idea2_atr_regime',atr[s]<1.0)):
            if name not in pick:continue
            v=pick[name][0]
            if v=='A':sig[j,on&low,0]=0;sig[j,on&low,3]=-np.inf
            else:sig[j,on&low,4]*=.5
    return sig

def build(ctx,pick):
    mods={n:importlib.import_module(f'high_cagr.ideas.{n}') for n in IDEAS};kw={}
    for n in ('idea3_time_stop','idea5_giveback'):kw.update(mods[n].build(ctx,pick[n][1]).get('kwargs',{}))
    sig=mods['idea4_confirmation'].build(ctx,pick['idea4_confirmation'][1])['sig']
    return dict(sig=apply_filters(ctx,sig,pick),kwargs=kw)

def consistency(pick):
    """Our filter on the BASELINE signals must equal the idea agents' own build output."""
    ctx=bench.load();mods={n:importlib.import_module(f'high_cagr.ideas.{n}') for n in ('idea1_volume','idea2_atr_regime')}
    for n,m in mods.items():
        own=np.asarray(m.build(ctx,pick[n][1])['sig'],float);p={n:pick[n]}
        mine=apply_filters(ctx,bench.base_sig(),p)
        if pick[n][0]=='A':assert np.array_equal(own[:,:,0],mine[:,:,0]),n
        else:
            r=own[:,:,4] if own.shape[2]>4 else np.ones(own.shape[:2]);on=own[:,:,0]!=0;assert np.allclose(r[on],mine[:,:,4][on]),n
    return True

if __name__=='__main__':
    pick=best();print('picked',pick,flush=True);consistency(pick)
    bench.run_idea('combo_all5',{'BEST':pick},lambda ctx,p:build(ctx,p),notes='pre-declared combo: best-Calmar variant of every idea together')
