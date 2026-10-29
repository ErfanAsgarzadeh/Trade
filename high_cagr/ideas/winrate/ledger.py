"""Win-rate study, step 1: the shipped three-bot ledgers (Shahin, Mojsavar, Ghoghnous C_exhaustion_soft x1.5) with, for
every leg, its realised R, the minute-path MFE/MAE in R and a set of CAUSAL entry features.

Ledgers come unchanged from high_cagr/ideas/five_year_report.ledgers('soft') (the same legs the five-year report replays).
Features use only the 4h bar that CLOSED before the entry minute (b = em//240 - 1) and data before it; portfolio
features (open legs, recent results) use only legs that were open at / closed before the entry minute.
Cached to high_cagr/output/ideas/winrate/legs.pkl (research only; nothing here is imported by the bots).
"""
from pathlib import Path
import sys,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import five_year_report as FY, pabench as PB
OUT=ROOT/'high_cagr/output/ideas/winrate';CACHE=OUT/'legs.pkl';RAW=OUT/'raw_legs.pkl'
SPLIT_MIN=FY.X.SPLIT*1440   # 2025-01-01 (train | validation split used by every earlier study)
BM=240

@functools.lru_cache(None)
def coin(s):return PB.coin(s)

def _rank(x,b,n):
    w=x[max(0,b-n):b+1];w=w[np.isfinite(w)]
    return float((w<x[b]).mean()) if len(w)>10 and np.isfinite(x[b]) else np.nan

def path_stats(l):
    """MFE / MAE in R over the minutes the leg was open, and the minute (from entry) the MFE was reached."""
    P=coin(l['coin'])['P'];s=l['side'];e=l['entry'];em,xm=l['em'],l['xm']
    hi=P[em:xm+1,1];lo=P[em:xm+1,2];risk=e*l['stop_frac']
    fav=(hi-e) if s==1 else (e-lo);adv=(e-lo) if s==1 else (hi-e)
    fav=np.maximum.accumulate(fav)
    return float(fav[-1]/risk),float(adv.max()/risk),int(np.argmax(fav>=fav[-1]))

def entry_features(l):
    d=coin(l['coin']);s=l['side'];b=l['em']//BM-1
    o,h,lo,c,v,a=d['o'],d['h'],d['l'],d['c'],d['v'],d['atr']
    if b<60:return None
    bt=d['btc'];atrp=a/c
    f=dict(
        atrp=atrp[b],atr_rank=_rank(atrp,b,100),adx=d['adx'][b],rsi_s=s*(d['rsi'][b]-50),
        d_e20=s*(c[b]-d['e20'][b])/a[b],d_e50=s*(c[b]-d['e50'][b])/a[b],d_e200=s*(c[b]-d['e200'][b])/a[b],
        slope50=s*(d['e50'][b]-d['e50'][b-6])/a[b],slope200=s*(d['e200'][b]-d['e200'][b-12])/a[b],
        ret6=s*np.log(c[b]/c[b-6]),ret24=s*np.log(c[b]/c[b-24]),ret60=s*np.log(c[b]/c[b-60]),
        range_atr=(h[b]-lo[b])/a[b],body=s*(c[b]-o[b])/max(h[b]-lo[b],1e-12),
        vol_rel=v[b]/max(np.median(v[b-50:b]),1e-12) if v[b-50:b].any() else np.nan,
        don20=((c[b]-lo[b-19:b+1].min())/max(h[b-19:b+1].max()-lo[b-19:b+1].min(),1e-12)-.5)*s+.5,
        room60=s*((h[b-59:b+1].max() if s==1 else lo[b-59:b+1].min())-c[b])/a[b],
        htf=s*d['htf'][b],
        btc_e200=s*(bt['c'][b]/bt['e200'][b]-1),btc_e50=s*(bt['c'][b]/bt['e50'][b]-1),
        btc_ret6=s*np.log(bt['c'][b]/bt['c'][b-6]),btc_ret42=s*np.log(bt['c'][b]/bt['c'][b-42]),
        btc_atr_rank=_rank(bt['atr']/bt['c'],b,100),
        fund8h=s*(d['fc'][l['em']]-d['fc'][max(0,l['em']-480)]),fund3d=s*(d['fc'][l['em']]-d['fc'][max(0,l['em']-4320)]),
        hour=(l['em']//60)%24,dow=(l['em']//1440+1)%7,side=s,stop_frac=l['stop_frac'],
    )
    return f

def portfolio_features(df):
    """Open-leg counts at the entry minute and the bot's recent closed results (causal: exit minute < entry minute)."""
    em=df.em.to_numpy();xm=df.xm.to_numpy();side=df.side.to_numpy();bot=df.bot.to_numpy();coin_=df.coin.to_numpy();R=df.R.to_numpy()
    order=np.argsort(xm,kind='stable');xs=xm[order]
    n_open=np.zeros(len(df));n_same=np.zeros(len(df));coin_busy=np.zeros(len(df));wr10=np.full(len(df),np.nan);r20_all=np.full(len(df),np.nan)
    last_same_coin=np.full(len(df),np.nan)
    for i in range(len(df)):
        live=(em<em[i])&(xm>=em[i])
        n_open[i]=live.sum();n_same[i]=(live&(side==side[i])).sum();coin_busy[i]=(live&(coin_==coin_[i])).sum()
        k=np.searchsorted(xs,em[i],side='left');closed=order[:k]
        mine=closed[bot[closed]==bot[i]]
        if len(mine)>=10:wr10[i]=(R[mine[-10:]]>0).mean()
        if len(closed)>=20:r20_all[i]=R[closed[-20:]].mean()
        sc=mine[coin_[mine]==coin_[i]]
        if len(sc):last_same_coin[i]=R[sc[-1]]
    df['n_open']=n_open;df['n_same_side']=n_same;df['coin_busy']=coin_busy;df['bot_wr10']=wr10;df['all_r20']=r20_all;df['last_coin_R']=last_same_coin
    return df

@functools.lru_cache(1)
def raw_legs():
    """The shipped ledger (list of leg dicts), cached because rebuilding it takes ~10 minutes."""
    if RAW.exists():return pd.read_pickle(RAW)
    legs=FY.ledgers('soft');OUT.mkdir(parents=True,exist_ok=True);pd.to_pickle(legs,RAW);return legs

def build(force=False):
    if CACHE.exists() and not force:return pd.read_pickle(CACHE)
    legs=raw_legs();rows=[]
    for i,l in enumerate(legs):
        f=entry_features(l)
        if f is None:f={}
        mfe,mae,t_mfe=path_stats(l)
        rows.append(dict(i=i,bot=l['bot'],coin=l['coin'],side=l['side'],em=l['em'],xm=l['xm'],entry=l['entry'],unit=l['unit'],
                         stop_frac=l['stop_frac'],risk_scale=l['risk_scale'],root=str(l['root']),is_add=l['is_add'],
                         R=l['unit']/l['entry']/l['stop_frac'],mfe_R=mfe,mae_R=mae,mins_to_mfe=t_mfe,hours=(l['xm']-l['em'])/60,**{('f_'+k):v for k,v in f.items()}))
    df=pd.DataFrame(rows);df['win']=(df.R>0).astype(int);df['period']=np.where(df.em<SPLIT_MIN,'train','valid')
    df=portfolio_features(df);OUT.mkdir(parents=True,exist_ok=True);df.to_pickle(CACHE);return df

if __name__=='__main__':
    df=build(force='--force' in sys.argv)
    print(df.groupby('bot').agg(n=('R','size'),win=('win','mean'),R=('R','mean'),mfe=('mfe_R','median')))
