import sys;sys.path.insert(0,'/home/user/Trade')
from high_cagr import r3_harness as h
import numpy as np, pandas as pd
def outcomes(U,sym_k,s):
    f=U['frames'][s];ix=U['ix'][s];sg=U['sig'][sym_k];hi=f.high.to_numpy();lo=f.low.to_numpy()
    rows=[]
    for b in np.where(sg[:,0]!=0)[0]:
        i=ix[b]
        if i<0:continue
        side,e,st=sg[b,0],sg[b,1],sg[b,2];R=abs(e-st);fb=1;
        for j in range(i+1,min(i+200,len(f))):
            # use bar j
            up=(hi[j]-e)*side if side>0 else (e-lo[j]);
            fav=(hi[j]-e) if side>0 else (e-lo[j]);adv=(e-lo[j]) if side>0 else (hi[j]-e)
            if adv>=R: break
            if fav>=0.3*R: fb=0;break
        rows.append((b,s,side,fb,pd.Timestamp(f.timestamp.iloc[i],unit='ms')))
    return rows
if __name__=='__main__':
    U=h.universe('OLD5');R=[]
    for k,s in enumerate(U['symbols']):R+=outcomes(U,k,s)
    d=pd.DataFrame(R,columns=['b','s','side','fb','t']);d=d[d.b<4908]
    d['hr']=d.t.dt.hour;d['wd']=d.t.dt.weekday
    print(len(d),d.fb.mean());print(d.groupby('hr').fb.agg(['mean','count']));print(d.groupby('wd').fb.agg(['mean','count']))
    d['we']=d.wd>=5;print(d.groupby('we').fb.agg(['mean','count']))
