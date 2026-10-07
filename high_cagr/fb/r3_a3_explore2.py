import sys;sys.path.insert(0,'/home/user/Trade')
from high_cagr import r3_harness as h
import numpy as np, pandas as pd
def outc(U,k,s):
    f=U['frames'][s];ix=U['ix'][s];sg=U['sig'][k];hi=f.high.to_numpy();lo=f.low.to_numpy();out=[]
    for b in np.where(sg[:,0]!=0)[0]:
        i=ix[b]
        if i<0:continue
        side,e,st=sg[b,0],sg[b,1],sg[b,2];R=abs(e-st);fb=1;res=None
        for j in range(i+1,min(i+300,len(f))):
            fav=(hi[j]-e) if side>0 else (e-lo[j]);adv=(e-lo[j]) if side>0 else (hi[j]-e)
            if adv>=R:res=j;break
            if fav>=0.3*R:fb=0;res=j;break
        out.append((b,side,fb,b+(res-i if res else 300)))   # resolution in bar units (4h bars 1:1 rows)
    return out
if __name__=='__main__':
    U=h.universe('OLD5');rows=[]
    for k,s in enumerate(U['symbols']):
        o=outc(U,k,s);bs=np.array([x[0] for x in o]);fbs=np.array([x[2] for x in o]);rs_=np.array([x[3] for x in o])
        for n,(b,side,fb,r) in enumerate(o):
            prior=bs<b
            gap=b-bs[prior].max() if prior.any() else 9999
            first=gap>6   # fresh episode
            for N in (60,180):
                pass
            known=(rs_<=b)&(bs<b)   # resolved by now
            nfb30=(known&(fbs==1)&(bs>=b-180)).sum();nw30=(known&(fbs==0)&(bs>=b-180)).sum()
            lastres=fbs[known][-1] if known.any() else -1
            rows.append((s,b,fb,gap,nfb30,nw30,lastres))
    d=pd.DataFrame(rows,columns=['s','b','fb','gap','nfb30','nw30','last']);d=d[d.b<4908]
    print(len(d),d.fb.mean())
    d['gb']=pd.cut(d.gap,[0,1,2,6,18,60,200,1e5]);print(d.groupby('gb',observed=True).fb.agg(['mean','count']))
    d['kb']=d.nfb30.clip(upper=5);print(d.groupby('kb').fb.agg(['mean','count']))
    d['net']=(d.nfb30-d.nw30).clip(-3,4);print(d.groupby('net').fb.agg(['mean','count']))
    print(d.groupby('last').fb.agg(['mean','count']))
