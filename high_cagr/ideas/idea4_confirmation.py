"""Idea 4_confirmation (pre-declared in predeclared.json).
A: wait one bar - enter at b+1 only if bar b had a raw baseline signal (side d) and close_{b+1} is still beyond bar b's
   breakout level (max/min of Donchian10 and Kumo edge) and still outside the Kumo on that side; stop = close_{b+1} -/+ 2 ATR.
B: keep a baseline signal only if the signal close penetrates the breakout level by >= 0.25 ATR.
Everything is recomputed from ctx['frames'] rows <= ix[b+1] (A) / ix[b] (B)."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import bench

def _raw(f,ix):
    g=lambda c:f[c].to_numpy(np.float64)[ix]
    close=g('close');top=g('kumo_top');bot=g('kumo_bottom');hi=g('donchian_high_10');lo=g('donchian_low_10');atr=g('atr')
    side=((close>top)&(close>hi)).astype(np.int64)-((close<bot)&(close<lo)).astype(np.int64)
    return dict(close=close,top=top,bot=bot,atr=atr,side=side,lvl_l=np.maximum(hi,top),lvl_s=np.minimum(lo,bot))

def build(ctx,variant):
    base=bench.base_sig();ns,nb,_=base.shape;sig=np.zeros((ns,nb,4));sig[:,:,3]=-np.inf
    for j,s in enumerate(ctx['symbols']):
        ix=np.asarray(ctx['ix'][s])[:nb];r=_raw(ctx['frames'][s],ix);d=r['side'];c=r['close']
        lvl=np.where(d==1,r['lvl_l'],np.where(d==-1,r['lvl_s'],np.nan))
        if variant['mode']=='wait':
            dp=d[:-1];lv=lvl[:-1];c1=c[1:];newbar=ix[1:]>ix[:-1]
            outside=np.where(dp==1,c1>r['top'][1:],c1<r['bot'][1:])
            ok=(dp!=0)&newbar&(dp*(c1-lv)>0)&outside
            k=np.where(ok)[0]+1;dd=d[k-1].astype(float)
            sig[j,k,0]=dd;sig[j,k,1]=c[k];sig[j,k,2]=c[k]-dd*2*r['atr'][k];sig[j,k,3]=dd*(c[k]-lvl[k-1])/c[k]
            sig[j,:,1]=np.where(sig[j,:,0]!=0,sig[j,:,1],base[j,:,1]);sig[j,:,2]=np.where(sig[j,:,0]!=0,sig[j,:,2],base[j,:,2])
        else:
            pen=np.where(d!=0,d*(c-np.nan_to_num(lvl)),-np.inf)
            keep=(d!=0)&(pen>=variant['pen_atr']*r['atr'])
            sig[j,:,1:3]=base[j,:,1:3]
            sig[j,:,0]=np.where(keep,d,0);sig[j,:,3]=np.where(keep,base[j,:,3],-np.inf)
    return dict(sig=sig)

if __name__=='__main__':
    ctx=bench.load();b=ctx['sig']
    # sanity: recomputed raw side matches baseline side
    for j,s in enumerate(ctx['symbols']):
        r=_raw(ctx['frames'][s],np.asarray(ctx['ix'][s])[:b.shape[1]]);assert np.array_equal(r['side'],b[j,:,0].astype(np.int64)),s
    bench.run_idea('idea4_confirmation',{'A':dict(mode='wait'),'B':dict(mode='penetration',pen_atr=.25)},build,
        notes='A: confirmed entry at b+1 (close_{b+1} beyond level_b and outside Kumo; stop close_{b+1}-d*2ATR_{b+1}; score d*(close_{b+1}-level_b)/close_{b+1}); '
              'no confirmation when ix[b+1]==ix[b]. B: keep baseline signal iff d*(close-level)>=0.25*ATR at signal bar.')
