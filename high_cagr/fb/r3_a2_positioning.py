"""R3 A2 positioning/crowding on false breakouts. VARIANTS declared before running:
 A funding_abs3d : block long if mean of last 9 funding prints (3d) >= 1.5e-4 (1.5x the 1e-4 default interest level = crowded longs);
                   block short if mean <= 0.5e-4 (shorts paying less than base = crowded shorts). First-principles absolute levels.
 B funding_pct7d : 7d (21 prints) mean funding vs symbol's OWN past 180d distribution of that mean: block long if > 80th pct, short if < 20th pct.
 C rs_btc_7d     : alt long only if alt 42-bar return > BTC 42-bar return; alt short only if alt return < BTC (BTCUSDT itself exempt).
 D rs_btc_3d     : same with 18-bar (3d) window.
Funding uses only prints with minute < b*step (strictly before signal bar start)."""
import numpy as np, pandas as pd
from high_cagr import r3_harness as h
VARIANTS={'A_funding_abs3d':dict(kind='abs',n=9,hi=1.5e-4,lo=0.5e-4),
          'B_funding_pct7d':dict(kind='pct',n=21,q=.2,win=1080),
          'C_rs_btc_7d':dict(kind='rs',n=42),
          'D_rs_btc_3d':dict(kind='rs',n=18)}
def fund_avg(U,k,n):
    x=np.asarray(U['funding'][k]);nz=np.flatnonzero(~np.isnan(x));v=x[nz]
    nb=U['sig'].shape[1];t=np.arange(nb)*U['step']          # prints with minute < t
    cnt=np.searchsorted(nz,t,side='left')                    # number of prints strictly before
    cs=np.concatenate([[0.],np.cumsum(v)]);m=np.minimum(cnt,n)
    out=np.where(cnt>=n,(cs[cnt]-cs[np.maximum(cnt-n,0)])/n,np.nan);return out
def build_fn(U,var):
    sig=U['sig'].copy();nb=sig.shape[1]
    for k,s in enumerate(U['symbols']):
        side=sig[k,:,0]
        if var['kind']=='abs':
            a=fund_avg(U,k,var['n']);bad=((side>0)&~(a<var['hi']))|((side<0)&~(a>var['lo']))
        elif var['kind']=='pct':
            a=fund_avg(U,k,var['n']);sr=pd.Series(a);lo=sr.rolling(var['win'],min_periods=360).quantile(var['q']).shift(1).to_numpy()
            hi=sr.rolling(var['win'],min_periods=360).quantile(1-var['q']).shift(1).to_numpy()
            bad=((side>0)&~(a<=hi))|((side<0)&~(a>=lo))
        else:
            if s=='BTCUSDT':continue
            n=var['n'];j=np.asarray(U['ix'][s]);jb=np.asarray(U['ix']['BTCUSDT'])
            ca=U['frames'][s].close.to_numpy(float);cb=U['frames']['BTCUSDT'].close.to_numpy(float)
            ok=(j>=n)&(jb>=n);jj=np.where(ok,j,n);kk=np.where(ok,jb,n)
            ra=ca[jj]/ca[jj-n]-1;rb=cb[kk]/cb[kk-n]-1
            bad=~ok|((side>0)&~(ra>rb))|((side<0)&~(ra<rb))
        sig[k,bad&(side!=0),0]=0
    return dict(sig=sig)
if __name__=='__main__':
    h.run_method('r3_a2_positioning','fb',VARIANTS,build_fn,notes='funding crowding + relative strength vs BTC; blocks signals')
