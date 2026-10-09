"""pa_opt_momfilt: momentum / oscillator / volume (exhaustion) filters on the PA sleeve (4h KEYREV, TP2, 30-bar stop).

HYPOTHESIS. A key reversal is a counter-trend entry; it should pay best when the prior move was exhausted / capitulating
(oversold RSI, price stretched far from EMA20, bar pierces the Bollinger band, volume spike, long steep decline into the
signal) and worst when it fires in a mild, neutral pullback (no exhaustion, so no snap-back fuel).
MECHANISM. Exhaustion = stretched price + forced sellers; the reversal bar then mean-reverts toward the EMA, giving the 2R
target a good chance. Neutral-context signals are ordinary noise. Either skip non-exhaustion signals or size up exhaustion.

Features (causal; bar t = signal bar, direction s=+1 long / -1 short, everything mirrored for shorts):
 rsi_dir  = rsi[t] for long, 100-rsi[t] for short (low = oversold)
 stretch  = s*(e20[t]-c[t])/atr[t]  (close below EMA20 in ATR for long)
 bb       = signal bar low < SMA20-2*sd20 of closes (long) / high > SMA20+2*sd20 (short), bands over closes t-19..t
 volr     = v[t]/mean(v[t-20..t-1])
 move10   = s*(c[t-10]-c[t])/atr[t]  (decline into the signal, in ATR)
Cut points are standard textbook values fixed in advance (not tuned): RSI 40, stretch 1.5 ATR, band 20/2, volume 1.5x, move 4 ATR.
A diagnostic (TRAIN only, baseline trades, mean R by bucket) is run separately and only REPORTED; it does not set parameters.
VARIANTS (fixed, 8):
 A rsi_oversold   skip unless rsi_dir <= 40
 B stretch        skip unless stretch >= 1.5
 C bollinger      skip unless bb
 D volspike       skip unless volr >= 1.5
 E steep_move     skip unless move10 >= 4
 F not_exhausted  inverse: skip if rsi_dir<=40 (keep only neutral/non-oversold context)
 G boost          risk x1.5 if (A or B or C or D or E conditions count >= 2), else x1.0
 H half_neutral   risk x0.5 if none of the A..E conditions is true, else x1.0
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np,pandas as pd
from high_cagr.ideas import pabench as PB

VARIANTS={'A_rsi_oversold':dict(m='skip',c=['A']),'B_stretch':dict(m='skip',c=['B']),'C_bollinger':dict(m='skip',c=['C']),
    'D_volspike':dict(m='skip',c=['D']),'E_steep_move':dict(m='skip',c=['E']),'F_not_exhausted':dict(m='skipif',c=['A']),
    'G_boost2':dict(m='boost'),'H_half_neutral':dict(m='halfnone')}

def feats(d):
    n=len(d['c']);c=d['c'];a=d['atr'];s=np.asarray(d['sig']['side'][:n],float);S=pd.Series(c)
    sm=S.rolling(20).mean().to_numpy();sd=S.rolling(20).std(ddof=0).to_numpy()
    vm=pd.Series(d['v']).rolling(20).mean().shift(1).to_numpy();c10=np.r_[np.full(10,np.nan),c[:-10]]
    with np.errstate(all='ignore'):
        rsi_dir=np.where(s>0,d['rsi'],100-d['rsi']);stretch=s*(d['e20']-c)/a
        bb=np.where(s>0,d['l']<sm-2*sd,d['h']>sm+2*sd);volr=d['v']/vm;mv=s*(c10-c)/a
    return dict(A=rsi_dir<=40,B=stretch>=1.5,C=bb,D=volr>=1.5,E=mv>=4),dict(rsi=rsi_dir,stretch=stretch,volr=volr,move=mv)

def fn(d,v):
    n=len(d['c']);cd,_=feats(d);sd=d['sig']['side'][:n]
    cnt=sum(np.nan_to_num(cd[k]).astype(int) for k in 'ABCDE')
    if v['m']=='skip':
        ok=np.ones(n,bool)
        for k in v['c']:ok&=np.nan_to_num(cd[k]).astype(bool)
        return PB.run(d,side=np.where(ok,sd,0).astype(np.int8))
    if v['m']=='skipif':
        bad=np.nan_to_num(cd[v['c'][0]]).astype(bool);return PB.run(d,side=np.where(bad,0,sd).astype(np.int8))
    if v['m']=='boost':return PB.run(d,mult=np.where(cnt>=2,1.5,1.))
    return PB.run(d,mult=np.where(cnt==0,.5,1.))

def diag():
    """TRAIN-only: baseline trades (OTHER20), mean net R-ish (R column) by feature bucket. Not used for parameters."""
    rows=[]
    for s in PB.OTHER20:
        d=PB.coin(s);t=PB.base_fn(d)
        if not len(t):continue
        t=t[t[:,0]<PB.SPLIT*1440];_,f=feats(d);n=len(d['c'])
        for r in t:
            b=int(r[0])//240-1  # entry bar -1 = signal bar (entry normally the next bar)
            if 0<=b<n:rows.append(dict(R=r[4],net=r[3]*1e4,**{k:v[b] for k,v in f.items()}))
    df=pd.DataFrame(rows).dropna();print('TRAIN baseline trades',len(df),'meanR',round(df.R.mean(),3),'win',round((df.R>0).mean(),3))
    for k,edges in dict(rsi=[0,30,40,50,60,70,100],stretch=[-9,-0.5,0,0.5,1,1.5,2.5,99],volr=[0,.7,1,1.5,2.5,99],move=[-99,0,2,4,6,99]).items():
        g=df.groupby(pd.cut(df[k],edges),observed=True).R.agg(['count','mean']);print(k);print(g.round(3).to_string())

def main():PB.run_idea('momfilt',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
