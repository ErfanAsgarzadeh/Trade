"""r3_a3_timing: symbol-level failure memory (price-based, causal) + weekend control.
Proxy per past signal (any signal bar, blocked or not): resolved at first later 4h bar whose adverse excursion >= 2ATR-stop distance (FB) or favourable >= 0.3R (win-ish).
Known at bar b only if resolution frame row <= ix[b]. Variants declared before running.
 A mem_K5_30d : block if >=5 resolved FB proxies in last 30d (180 bars)   - explore (OLD5 H1) showed FB rate 0.25 at >=4 vs 0.20 base
 B mem_K3_15d : block if >=3 resolved FB proxies in last 15d (90 bars)   - shorter/stricter memory, first-principles
 C mem_net2   : block if (FB - wins) over last 30d >= 2 (winners reset memory)
 D weekend    : block signals on bars closing Sat/Sun UTC  - prior from folklore; H1 explore showed NO difference (control)
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np, pandas as pd
VARIANTS={'A':dict(kind='mem',K=5,N=180,net=False),'B':dict(kind='mem',K=3,N=90,net=False),'C':dict(kind='mem',K=2,N=180,net=True),'D':dict(kind='wk')}
def _proxy(f,ix,sg):
    hi=f.high.to_numpy();lo=f.low.to_numpy();n=len(f);bs=[];fbs=[];res=[]
    for b in np.where(sg[:,0]!=0)[0]:
        i=ix[b]
        if i<0:continue
        side,e,st=sg[b,0],sg[b,1],sg[b,2];R=abs(e-st);fb=-1;r=10**9
        for j in range(i+1,min(i+300,n)):
            fav=(hi[j]-e) if side>0 else (e-lo[j]);adv=(e-lo[j]) if side>0 else (hi[j]-e)
            if adv>=R:fb=1;r=j;break
            if fav>=0.3*R:fb=0;r=j;break
        bs.append(b);fbs.append(fb);res.append(r)
    return np.array(bs),np.array(fbs),np.array(res)
def build_fn(U,v):
    sig=U['sig'].copy()
    for k,s in enumerate(U['symbols']):
        if s=='BTCUSDT' and False:continue
        f=U['frames'][s];ix=np.asarray(U['ix'][s]);bs,fbs,res=_proxy(f,ix,U['sig'][k])
        if len(bs)==0:continue
        if v['kind']=='wk':
            ts=pd.to_datetime(f.timestamp.to_numpy()+U['step']*60000,unit='ms')   # bar close time
            for b in bs:
                if ix[b]>=0 and ts[ix[b]].weekday()>=5:sig[k,b,:]=0
            continue
        for b,i in zip(bs,ix[bs]):
            known=(res<=i)&(bs<b)&(bs>=b-v['N'])
            nfb=int((known&(fbs==1)).sum());nw=int((known&(fbs==0)).sum())
            if (nfb-nw if v['net'] else nfb)>=v['K']:sig[k,b,:]=0
    return dict(sig=sig)
if __name__=='__main__':
    from high_cagr import r3_harness as h
    h.run_method('r3_a3_timing','fb',VARIANTS,build_fn,notes='price-proxy failure memory A/B/C + weekend control D; see docstring')
