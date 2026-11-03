"""Feature library for the trade-scoring studies: ~50 causal criteria computed on the closed 4h bars of every coin.
Everything at bar b uses data of bars <= b only. 'signed' features are multiplied by the trade side (+ = with the trade).
Families: trend (EMA distances/slopes, MACD, Ichimoku, daily trend), momentum/oscillators (RSI, Stochastic, CCI, MFI, returns,
Bollinger %B, Donchian position), volatility (ATR rank, Parkinson ratio, Bollinger width, ATR change), trend quality (ADX,
Kaufman efficiency, variance ratio), volume (relative volume, OBV slope), candle shape (body, rejection wick, range, gap),
market (BTC trend/momentum/ADX/volatility, breadth, breadth change, relative strength, correlation with BTC),
carry (funding), calendar (weekend), trade (stop distance, bot).
"""
import sys,functools
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pabench as PB, pa2_confluence as CF
COINS=sorted(set(PB.ALL35))
SIGNED=['trend20','trend50','trend200','slope20','slope50','slope200','macd','rsi','stoch','cci20','bbpos','don20','don60','ret5','ret20','ret60','ret120',
        'obv_slope','mfi','body','wick_rej','gap','ichi_cloud','kijun_dist','htf','funding','btc_trend200','btc_ret6','breadth','breadth_chg','rs60']
UNSIGNED=['adx','er20','vratio','vol','volrank','volpk','bbwidth','atr_chg','relvol','range_atr','btc_adx','btc_volrank','corr_btc','weekend','stop','bot_c3','bot_pa']
ALL=SIGNED+UNSIGNED
FAMILY={**{k:'trend' for k in ('trend20','trend50','trend200','slope20','slope50','slope200','macd','ichi_cloud','kijun_dist','htf')},
 **{k:'momentum' for k in ('rsi','stoch','cci20','mfi','ret5','ret20','ret60','ret120','bbpos','don20','don60','rs60')},
 **{k:'volatility' for k in ('vol','volrank','volpk','bbwidth','atr_chg','range_atr')},
 **{k:'trend quality' for k in ('adx','er20','vratio')},**{k:'volume' for k in ('obv_slope','relvol')},**{k:'candle' for k in ('body','wick_rej','gap')},
 **{k:'market' for k in ('btc_trend200','btc_ret6','btc_adx','btc_volrank','breadth','breadth_chg','corr_btc')},
 **{k:'carry/calendar' for k in ('funding','weekend')},**{k:'trade' for k in ('stop','bot_c3','bot_pa')}}

def ema(x,n):return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()
def roll(x,n,f):return getattr(pd.Series(x).rolling(n),f)().to_numpy()

def _own(s):
    d=PB.coin(s);o,h,l,c,v,a=(d[k].astype(float) for k in ('o','h','l','c','v','atr'));n=len(c);f={}
    e20,e50,e200=d['e20'],d['e50'],d['e200'];sh=lambda x,k:np.concatenate([np.full(k,np.nan),x[:-k]])
    f['trend20']=c/e20-1;f['trend50']=c/e50-1;f['trend200']=c/e200-1
    f['slope20']=(e20-sh(e20,6))/a;f['slope50']=(e50-sh(e50,6))/a;f['slope200']=(e200-sh(e200,12))/a
    macd=ema(c,12)-ema(c,26);f['macd']=(macd-ema(macd,9))/a
    f['rsi']=(d['rsi']-50)/50
    lo14=roll(l,14,'min');hi14=roll(h,14,'max');f['stoch']=(c-lo14)/np.where(hi14>lo14,hi14-lo14,np.nan)*2-1
    tp=(h+l+c)/3;ma=roll(tp,20,'mean');md=pd.Series(tp).rolling(20).apply(lambda z:np.abs(z-z.mean()).mean(),raw=True).to_numpy();f['cci20']=(tp-ma)/(.015*md+1e-12)/200
    m20=roll(c,20,'mean');s20=roll(c,20,'std');f['bbpos']=(c-m20)/(2*s20+1e-12);f['bbwidth']=s20/m20
    h20=roll(h,20,'max');l20=roll(l,20,'min');f['don20']=(c-l20)/np.where(h20>l20,h20-l20,np.nan)*2-1
    h60=roll(h,60,'max');l60=roll(l,60,'min');f['don60']=(c-l60)/np.where(h60>l60,h60-l60,np.nan)*2-1
    for k in (5,20,60,120):f[f'ret{k}']=c/sh(c,k)-1
    f['adx']=d['adx']
    ch=np.abs(c-sh(c,20));path=roll(np.abs(np.diff(c,prepend=np.nan)),20,'sum');f['er20']=ch/(path+1e-12)
    r1=np.diff(np.log(c),prepend=np.nan);r4=np.log(c)-np.log(sh(c,4));f['vratio']=roll(r4,100,'var')/(4*roll(r1,100,'var')+1e-18)
    vol=a/c;f['vol']=vol;f['volrank']=CF.prank(np.ascontiguousarray(vol),500)
    pk=np.log(h/l)**2/(4*np.log(2));f['volpk']=np.sqrt(roll(pk,5,'mean'))/(np.sqrt(roll(pk,50,'mean'))+1e-12);f['atr_chg']=a/sh(a,20)-1
    f['relvol']=v/roll(v,20,'mean');obv=np.cumsum(np.sign(np.diff(c,prepend=c[0]))*v);f['obv_slope']=(obv-sh(obv,10))/(roll(v,20,'mean')*10+1e-12)
    pos=tp*v*(np.diff(tp,prepend=tp[0])>0);neg=tp*v*(np.diff(tp,prepend=tp[0])<0);f['mfi']=(roll(pos,14,'sum')/(roll(pos,14,'sum')+roll(neg,14,'sum')+1e-12)-.5)*2
    rg=np.where(h>l,h-l,np.nan);f['body']=(c-o)/rg;f['range_atr']=(h-l)/a;f['gap']=(o-sh(c,1))/a
    lw=(np.minimum(o,c)-l)/rg;uw=(h-np.maximum(o,c))/rg;f['_lw']=lw;f['_uw']=uw
    th=(roll(h,9,'max')+roll(l,9,'min'))/2;kj=(roll(h,26,'max')+roll(l,26,'min'))/2;ssa=sh((th+kj)/2,26);ssb=sh((roll(h,52,'max')+roll(l,52,'min'))/2,26)
    f['ichi_cloud']=(c-(ssa+ssb)/2)/a;f['kijun_dist']=(c-kj)/a;f['htf']=d['htf'].astype(float)
    fc=d['fc'];m=(np.arange(n)+1)*240;fm=np.clip(m,0,len(fc)-1);f['funding']=(fc[fm]-fc[np.clip(fm-480,0,None)])*1e3
    f['weekend']=(((np.arange(n)*240//1440+0)+ (pd.Timestamp('2021-10-05').dayofweek))%7>=5).astype(float)
    f['_ret1']=r1;return f

@functools.lru_cache(None)
def own(s):return _own(s)

@functools.lru_cache(1)
def market():
    n=min(len(own(s)['trend50']) for s in COINS);b=own('BTCUSDT');out={}
    out['btc_trend200']=b['trend200'][:n];out['btc_ret6']=(pd.Series(PB.coin('BTCUSDT')['c'][:n]).pct_change(6)).to_numpy();out['btc_adx']=b['adx'][:n];out['btc_volrank']=b['volrank'][:n]
    ab=np.array([own(s)['trend50'][:n]>0 for s in COINS]).astype(float);br=ab.mean(0);out['breadth']=br-.5;out['breadth_chg']=br-np.concatenate([np.full(12,np.nan),br[:-12]])
    r60=np.array([own(s)['ret60'][:n] for s in COINS]);rk=pd.DataFrame(r60.T).rank(axis=1,pct=True).to_numpy()*2-1;out['_rs']={s:rk[:,i] for i,s in enumerate(COINS)}
    rb=b['_ret1'][:n];out['_corr']={s:pd.Series(own(s)['_ret1'][:n]).rolling(60).corr(pd.Series(rb)).to_numpy() for s in COINS};out['n']=n;return out

def at(coin,b,side,stop=np.nan,bot=None):
    """feature dict for a trade/state on `coin`, at closed bar index b, with trade side +1/-1."""
    f=own(coin);M=market();s=side;r={}
    for k in SIGNED:
        if k in f:r[k]=s*f[k][b]
    r['wick_rej']=f['_lw'][b] if s>0 else f['_uw'][b]
    for k in ('btc_trend200','btc_ret6','breadth','breadth_chg'):r[k]=s*(M[k][b] if b<M['n'] else np.nan)
    r['rs60']=s*(M['_rs'][coin][b] if b<M['n'] else np.nan)
    for k in ('adx','er20','vratio','vol','volrank','volpk','bbwidth','atr_chg','relvol','range_atr','weekend'):r[k]=f[k][b]
    for k in ('btc_adx','btc_volrank'):r[k]=M[k][b] if b<M['n'] else np.nan
    r['corr_btc']=M['_corr'][coin][b] if b<M['n'] else np.nan
    r['stop']=stop;r['bot_c3']=float(bot=='c3');r['bot_pa']=float(bot=='pa');return r
