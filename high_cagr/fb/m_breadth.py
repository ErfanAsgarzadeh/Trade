"""breadth: allow a breakout only if >= N OTHER symbols had a same-direction signal in the last 6 signal bars (incl. current)."""
import numpy as np
VARIANTS={'A':{'min_others':2,'window':6},'B':{'min_others':3,'window':6}}

def _recent_any(x,w):
    # x bool (n,), True if any in [b-w+1, b]
    c=np.concatenate([[0],np.cumsum(x.astype(np.int64))])
    n=len(x);i=np.arange(n);lo=np.maximum(i-w+1,0)
    return (c[i+1]-c[lo])>0

def mask_fn(frames,ix,side,variant):
    syms=list(side);w=variant['window'];k=variant['min_others']
    cnt={}
    for d in (1,-1):
        rec=np.stack([_recent_any(np.asarray(side[s])==d,w) for s in syms]).astype(int)
        tot=rec.sum(0)
        cnt[d]={s:tot-rec[j] for j,s in enumerate(syms)}
    out={}
    for s in syms:
        sd=np.asarray(side[s]);c=np.where(sd==1,cnt[1][s],np.where(sd==-1,cnt[-1][s],0))
        out[s]=(c>=k)|(sd==0)
    return out

if __name__=='__main__':
    from high_cagr import fb_harness as h
    h.run_method('breadth',VARIANTS,mask_fn,notes='count of other symbols with same-direction signal in last 6 bars >= 2 (A) / 3 (B)')
