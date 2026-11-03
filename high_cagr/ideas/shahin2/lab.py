"""Shahin review 2 (PREDECLARED.md): every variant on the verified kernel, three views (ALONE, ACCOUNT, OTHER30)."""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import xuni as X, holdout_test as H, bench
from high_cagr.ideas.winrate import ledger as LG, exits as EX, run_rules as RR
OUT=ROOT/'high_cagr/output/ideas/shahin2';MAIN5=list(rs.SYMBOLS);OTHER30=X.NEW+H.H10+H.H2
BASE_KW=dict(floor_on=True,floor_trigger=1.,floor_lock=.1);MIN0=lambda ts:int((ts-rs.START)//60000)
SPLIT=LG.SPLIT_MIN

@functools.lru_cache(None)
def ctx(symbols):
    symbols=list(symbols);frames={s:X.frame(s) for s in symbols};fk={(s,'4h','standard'):frames[s] for s in symbols}
    case=dict(next(c for c in rs.grid() if c['id']==bench.WINNER),symbols=symbols)
    ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;ix={};extra=[];atr=[];closes=[]
    for s in symbols:
        f=frames[s];ix[s]=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
        g=lambda c:f[c].to_numpy()[ix[s]]
        extra.append(np.column_stack([np.maximum(g('donchian_high_10'),g('kumo_top')),np.minimum(g('donchian_low_10'),g('kumo_bottom')),g('kumo_top'),g('kumo_bottom')]))
        atr.append((f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix[s]]);closes.append((f.close.to_numpy(),ix[s]))
    bb=np.concatenate([bb,np.stack(extra)],axis=2)
    prices=np.stack([np.load(X.PREP/s/'prices.npy',mmap_mode='r') for s in symbols]);funding=np.stack([np.load(X.PREP/s/'funding.npy',mmap_mode='r') for s in symbols])
    sig=np.concatenate([ss,np.ones(ss.shape[:2]+(1,))],axis=2)
    return dict(symbols=symbols,sig=sig,bb=np.ascontiguousarray(bb),step=step,prices=prices,funding=funding,atr=np.array(atr),closes=closes)

def move(c,L,s):
    """Side-signed log move of the last closed 4h close over L bars, on the entry grid."""
    cl,ix=c['closes'][s];r=np.log(cl/np.roll(cl,L));r[:L]=np.nan;return r[ix]

def thresholds(L):
    """TRAIN quantiles of the side-signed L-bar move on Shahin's signal bars (five coins, after the ATR-regime filter)."""
    c=ctx(tuple(MAIN5));v=[]
    for j in range(len(MAIN5)):
        sd=c['sig'][j,:,0];m=move(c,L,j);t=rs.START+np.arange(len(sd))*c['step']*60000
        ok=(sd!=0)&(c['atr'][j]>=1.)&np.isfinite(m)&((t-rs.START)//60000<SPLIT);v.append(sd[ok]*m[ok])
    v=np.concatenate(v);return {q:float(np.quantile(v,q)) for q in (.7,.8,.9)}

def run(symbols,v):
    c=ctx(tuple(symbols));sig=c['sig'].copy();kw=dict(BASE_KW);kw.update(v.get('kw',{}))
    for j in range(len(symbols)):
        sd=sig[j,:,0];on=sd!=0
        if v.get('atr_filter',True):
            low=on&~(c['atr'][j]>=1.);sig[j,low,0]=0;sig[j,low,3]=-np.inf
        L,thr,mode=v.get('late',(60,.1521,'skip'))
        if L:
            late=(sig[j,:,0]!=0)&(sig[j,:,0]*move(c,L,j)>thr)
            if mode=='skip':sig[j,late,0]=0;sig[j,late,3]=-np.inf
            else:sig[j,late,4]*=.5
    a,t,curve=simulate(c['prices'],c['funding'],np.ascontiguousarray(sig),c['bb'],rs.START,0,(rs.END-rs.START)//60000,v.get('risk',.01),v.get('slots',4),c['step'],
                       v.get('pyramid',True),slip=2e-4,legacy_cap=100.,risk_col=4,**kw)
    legs=[]
    for r in t:
        if r[2]<=0:continue
        legs.append(dict(bot='main',coin=symbols[int(r[0])],side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),
                         stop_frac=float(r[7]/r[4]),risk_scale=float(r[15]/r[14])/.01 if r[14] else 1.,root=('main',int(r[17])),is_add=int(r[18])!=0))
    days=len(c['prices'][0])//1440;st=X.stats(X.daily_from_curve(curve,days))
    R=np.array([l['unit']/l['entry']/l['stop_frac'] for l in legs]);g=R[R>0].sum();b=-R[R<0].sum()
    return legs,dict(full=st['full'],train=st['train'],valid=st['oos'],legs=len(legs),win=float((R>0).mean()*100),pf_R=float(g/b) if b>0 else np.inf)

@functools.lru_cache(1)
def others():
    df=LG.build();legs=LG.raw_legs();c3x,_=EX.modified_legs(legs,**RR.C3EXIT);return [l for l in c3x if l['bot']!='main']

def account(main_legs):
    st=EX.account_stats(EX.replay_legs(main_legs+others()));return dict(full=[st['calmar'],st['cagr'],st['dd']],train=st['train'],valid=st['valid'],win=st['win_rate']['all'])
