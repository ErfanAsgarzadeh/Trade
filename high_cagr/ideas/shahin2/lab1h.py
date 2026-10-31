"""Shahin on 1h entries with the improvements (PREDECLARED_1H.md). Same kernel, sizing, costs and three views as lab.py.

Signal (run_suite.inputs, unchanged): 1h close beyond the Donchian-N high/low of the previous N 1h bars AND the last closed 4h
bar beyond its Kumo; stop = close -/+ 2 x ATR14(1h); trail = 1h Donchian10 opposite channel. Options per variant:
  trail4h  trail on the last closed 4h bar's Donchian10 opposite channel (managed like 4h Shahin)
  stop4h   stop = close -/+ 2 x ATR14 of the last closed 4h bar
  atr      ATR-regime filter on '1h' (ATR / median of the previous 60 1h bars) or '4h' (last closed 4h bar's ratio, as shipped)
  late     move of the last closed 1h close over L 1h bars (L=240 = 60 x 4h), threshold 0.1521 as shipped
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import xuni as X
from high_cagr.ideas.shahin2 import lab as LB
STEP=60;MIN0=LB.MIN0

def frame(s,tf):
    z=np.load(X.PREP/s/f'{tf}_standard.npz');return pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))

@functools.lru_cache(None)
def ctx(symbols,N):
    symbols=list(symbols);f1={s:frame(s,'1h') for s in symbols};f4={s:frame(s,'4h') for s in symbols}
    fk={**{(s,'1h','standard'):f1[s] for s in symbols},**{(s,'4h','standard'):f4[s] for s in symbols}}
    case=dict(symbols=symbols,entry_timeframe='1h',preset='standard',lookback=N,trail='DONCHIAN10')
    ss,bb,step=rs.inputs(case,fk);assert step==STEP;nb=ss.shape[1]
    bnd=rs.START+np.arange(nb)*STEP*60000;ex=[];m4=[];m1=[]
    for s in symbols:
        a=f1[s];b=f4[s]
        i1=np.searchsorted(a.timestamp.to_numpy(np.int64)+STEP*60000,bnd,side='right')-1;i4=np.searchsorted(b.timestamp.to_numpy(np.int64)+240*60000,bnd,side='right')-1
        ch=[a.low.rolling(n).min().to_numpy()[i1] if sd==0 else a.high.rolling(n).max().to_numpy()[i1] for n in (3,4) for sd in (0,1)]
        g=lambda f,c,i:f[c].to_numpy()[i]
        ex.append(np.column_stack(ch+[np.maximum(g(a,'donchian_high_10',i1),g(b,'kumo_top',i4)),np.minimum(g(a,'donchian_low_10',i1),g(b,'kumo_bottom',i4)),g(b,'kumo_top',i4),g(b,'kumo_bottom',i4)]))
        m4.append(dict(lo=g(b,'opposite_low_10',i4),hi=g(b,'opposite_high_10',i4),atr=g(b,'atr',i4),ratio=(b.atr/b.atr.rolling(60).median().shift(1)).to_numpy()[i4]))
        cl=a.close.to_numpy();m1.append(dict(ratio=(a.atr/a.atr.rolling(60).median().shift(1)).to_numpy()[i1],close=cl,i1=i1))
    bb=np.concatenate([bb,np.stack(ex)],axis=2)
    prices=np.stack([np.load(X.PREP/s/'prices.npy',mmap_mode='r') for s in symbols]);funding=np.stack([np.load(X.PREP/s/'funding.npy',mmap_mode='r') for s in symbols])
    return dict(symbols=symbols,sig=np.concatenate([ss,np.ones(ss.shape[:2]+(1,))],axis=2),bb=bb,prices=prices,funding=funding,m4=m4,m1=m1)

def run(symbols,v):
    c=ctx(tuple(symbols),v.get('N',10));sig=c['sig'].copy();bb=c['bb'].copy();kw=dict(LB.BASE_KW);kw.update(v.get('kw',{}))
    for j in range(len(symbols)):
        m4,m1=c['m4'][j],c['m1'][j];sd=sig[j,:,0]
        if v.get('stop4h'):sig[j,:,2]=np.where(sd!=0,sig[j,:,1]-sd*2*m4['atr'],sig[j,:,2])
        if v.get('trail4h'):bb[j,:,0]=m4['lo'];bb[j,:,3]=m4['hi']
        ratio=m4['ratio'] if v.get('atr','4h')=='4h' else m1['ratio']
        on=sig[j,:,0]!=0;low=on&~(ratio>=1.);sig[j,low,0]=0;sig[j,low,3]=-np.inf
        L=v.get('late',240)
        if L:
            cl=m1['close'];r=np.log(cl/np.roll(cl,L));r[:L]=np.nan;r=r[m1['i1']]
            late=(sig[j,:,0]!=0)&(sig[j,:,0]*r>.1521);sig[j,late,0]=0;sig[j,late,3]=-np.inf
    a,t,curve=simulate(c['prices'],c['funding'],np.ascontiguousarray(sig),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.01,4,STEP,True,
                       slip=2e-4,legacy_cap=100.,risk_col=4,**kw)
    legs=[]
    for r in t:
        if r[2]<=0:continue
        legs.append(dict(bot='main',coin=symbols[int(r[0])],side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),
                         stop_frac=float(r[7]/r[4]),risk_scale=float(r[15]/r[14])/.01 if r[14] else 1.,root=('main',int(r[17])),is_add=int(r[18])!=0))
    days=len(c['prices'][0])//1440;st=X.stats(X.daily_from_curve(curve,days))
    R=np.array([l['unit']/l['entry']/l['stop_frac'] for l in legs]) if legs else np.zeros(1);g=R[R>0].sum();b=-R[R<0].sum()
    return legs,dict(full=st['full'],train=st['train'],valid=st['oos'],legs=len(legs),win=float((R>0).mean()*100),pf_R=float(g/b) if b>0 else np.inf)
