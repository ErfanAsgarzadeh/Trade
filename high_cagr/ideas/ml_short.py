"""ML-native short-horizon strategy on the 35 coins, timeframes 15m / 30m / 1h / 4h. Pre-declared before any result was seen.
DATA per coin on a 15m base grid (Binance USD-M, 2021-10-05 .. 2026-10-04): OHLC from 1-minute bars, volume and taker buy volume
(1m klines), open interest / top-trader and global long-short ratios / taker long-short volume ratio (5-min metrics, from
Dec-2021; value at the bar close), funding (cumulative), Fear & Greed (previous day). Coarser timeframes aggregate the 15m bars.
FEATURES at bar t (only data <= close of t): log returns over 1,2,4,8,16,32,96 bars; realised vol 16/96; range/vol; relative
volume; taker buy share 1/4/16 bars and its 96-bar z-score; OI change 1/4/16; log global and top long/short ratio and their 16-bar
change; taker long/short ratio; funding rate over the last 8h; distance to EMA20/EMA100 in vol units; BTC returns 1/4/16 and BTC
taker share; cross-sectional rank (across the 35 coins) of the 16-bar return and of the 4-bar taker share; hour of day (sin/cos);
Fear & Greed.
TARGET: log return from the close of t to the close of t+H, H = 4 bars (15m -> 1h, 30m -> 2h, 1h -> 4h, 4h -> 16h).
MODEL: gradient boosting regressor (depth 6, 300 trees, lr 0.05, min leaf 500), pooled over coins; ridge as a baseline.
WALK-FORWARD: test 2023, 2024, 2025-01..2026-10; train = all bars whose target window ended before the test start (purged);
training rows capped at 1.5M (random, seed 0).
TRADING (test windows): at each bar close, for every coin without an open position: long if prediction > k x cost, short if
< -k x cost (cost = 0.16% round trip: 0.06% fee per side + 2 bps slippage per side), k in {1, 2}; enter at that close, exit at
the close H bars later; funding charged; at most 10 open positions, ranked by |prediction|; each position notional = 20% of
equity at entry (gross <= 200%, i.e. <= 40% margin at 5x). Equity = $10,000 at each test start, realised P&L; also
marked-to-market daily for the drawdown.
"""
import sys,json,time,functools,warnings,glob,zipfile
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import pabench as PB, criteria_lib as C, sentiment_lib as SL
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from scipy.stats import spearmanr
OUT=ROOT/'high_cagr/output/ideas/ml_short';CACHE=ROOT/'high_cagr/cache_sentiment';B15=15*60000
COINS=C.COINS;COST=.0016;FEE=.0006;SLIP=.0002;H=4;MAXPOS=10;FRAC=.2
START=pd.Timestamp('2021-10-05')
def mn(d):return int((pd.Timestamp(d)-START).total_seconds()//60)
FOLDS={'2023':(mn('2023-01-01'),mn('2024-01-01')),'2024':(mn('2024-01-01'),mn('2025-01-01')),'2025-26':(mn('2025-01-01'),(rs.END-rs.START)//60000)}
TFS={'15m':1,'30m':2,'1h':4,'4h':16}

@functools.lru_cache(None)
def base15(s):
    f=CACHE/f'base15_{s}.npz'
    if f.exists():return dict(np.load(f))
    P=PB._px(s);n=len(P)//15;Q=P[:n*15].reshape(n,15,4);o=Q[:,0,0];h=Q[:,:,1].max(1);l=Q[:,:,2].min(1);c=Q[:,-1,3]
    tb=np.zeros(n);vv=np.zeros(n)
    for z in SL.kline_files(s):
        with zipfile.ZipFile(z) as zz:d=pd.read_csv(zz.open(zz.namelist()[0]),header=None,usecols=[0,5,9],names=['t','v','tb'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        b=((d.t.to_numpy()-rs.START)//B15).astype(np.int64);m=(b>=0)&(b<n);np.add.at(tb,b[m],d.tb.to_numpy()[m]);np.add.at(vv,b[m],d.v.to_numpy()[m])
    met=np.full((4,n),np.nan);parts=[]
    for z in sorted(glob.glob(str(CACHE/'metrics'/s/'*.zip'))):
        try:
            with zipfile.ZipFile(z) as zz:parts.append(pd.read_csv(zz.open(zz.namelist()[0]),usecols=['create_time','sum_open_interest','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']))
        except Exception:pass
    if parts:
        d=pd.concat(parts,ignore_index=True);t=pd.to_datetime(d.create_time).astype('int64')//10**6;d=d.assign(t=t).sort_values('t').drop_duplicates('t')
        closes=rs.START+(np.arange(n)+1)*B15;ix=np.searchsorted(d.t.to_numpy(),closes,side='right')-1;ok=ix>=0;age=np.full(n,1e18);age[ok]=closes[ok]-d.t.to_numpy()[ix[ok]]
        for i,cname in enumerate(['sum_open_interest','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']):
            v=pd.to_numeric(d[cname],errors='coerce').to_numpy();o_=np.full(n,np.nan);o_[ok]=v[ix[ok]];o_[age>3600000]=np.nan;met[i]=o_
    fc=PB.coin(s)['fc'];fcum=fc[np.minimum((np.arange(n)+1)*15,len(fc)-1)]
    out=dict(o=o,h=h,l=l,c=c,v=vv,tb=tb,oi=met[0],lst=met[1],lsg=met[2],tls=met[3],fcum=fcum);np.savez(f,**out);return out

def agg(s,k):
    b=base15(s)
    if k==1:return b
    n=len(b['c'])//k;r=lambda x:x[:n*k].reshape(n,k)
    return dict(o=r(b['o'])[:,0],h=r(b['h']).max(1),l=r(b['l']).min(1),c=r(b['c'])[:,-1],v=r(b['v']).sum(1),tb=r(b['tb']).sum(1),
                oi=r(b['oi'])[:,-1],lst=r(b['lst'])[:,-1],lsg=r(b['lsg'])[:,-1],tls=r(b['tls'])[:,-1],fcum=r(b['fcum'])[:,-1])

def feats(s,k,btc,fng):
    d=agg(s,k);c=d['c'];lc=np.log(c);n=len(c);S=pd.Series;F={}
    sh=lambda x,j:np.concatenate([np.full(j,np.nan),x[:-j]])
    for j in (1,2,4,8,16,32,96):F[f'r{j}']=lc-sh(lc,j)
    r1=F['r1'];F['vol16']=S(r1).rolling(16).std().to_numpy();F['vol96']=S(r1).rolling(96).std().to_numpy();vu=F['vol96']+1e-9
    for j in (1,4,16,96):F[f'r{j}']=F[f'r{j}']/vu
    F['range']=(np.log(d['h'])-np.log(d['l']))/vu;F['relvol']=np.log((d['v']+1)/(S(d['v']).rolling(96).mean().to_numpy()+1))
    ts=lambda j:S(d['tb']).rolling(j).sum().to_numpy()/np.maximum(S(d['v']).rolling(j).sum().to_numpy(),1e-12)-.5
    F['tb1'],F['tb4'],F['tb16']=ts(1),ts(4),ts(16);F['tbz']=(F['tb1']-S(F['tb1']).rolling(96).mean().to_numpy())/(S(F['tb1']).rolling(96).std().to_numpy()+1e-9)
    oi=d['oi'];F['oi1'],F['oi4'],F['oi16']=oi/sh(oi,1)-1,oi/sh(oi,4)-1,oi/sh(oi,16)-1
    F['lsg']=np.log(d['lsg']);F['lst']=np.log(d['lst']);F['lsg16']=F['lsg']-sh(F['lsg'],16);F['lst16']=F['lst']-sh(F['lst'],16);F['tls']=np.log(d['tls'])
    per8h=max(1,32//k);F['fund']=(d['fcum']-sh(d['fcum'],per8h))*1e3
    F['ema20']=(lc-np.log(S(c).ewm(span=20,adjust=False).mean().to_numpy()))/vu;F['ema100']=(lc-np.log(S(c).ewm(span=100,adjust=False).mean().to_numpy()))/vu
    for j in (1,4,16):F[f'btc{j}']=btc[f'r{j}'][:n]
    F['btc_tb4']=btc['tb4'][:n]
    hr=((np.arange(n)+1)*k*15/60)%24;F['hsin']=np.sin(2*np.pi*hr/24);F['hcos']=np.cos(2*np.pi*hr/24)
    F['fng']=fng[:n];F['y']=sh(lc,-H) if False else np.concatenate([lc[H:]-lc[:-H],np.full(H,np.nan)])
    return pd.DataFrame(F),d

def build(tf):
    k=TFS[tf];n0=None
    b=base15('BTCUSDT');bt,_=feats_btc(k);
    fd=json.loads((CACHE/'fng.json').read_text())['data'];fs=pd.Series({int(x['timestamp'])*1000:float(x['value']) for x in fd}).sort_index()
    frames=[];ext={}
    for s in COINS:
        nb=len(agg(s,k)['c']);closes=rs.START+(np.arange(nb)+1)*k*B15;ix=np.searchsorted(fs.index.to_numpy(),closes-86400000,side='right')-1
        fng=np.where(ix>=0,fs.to_numpy()[np.maximum(ix,0)],np.nan);F,d=feats(s,k,bt,fng);F['coin']=s;F['t']=np.arange(nb);frames.append(F);ext[s]=d
    D=pd.concat(frames,ignore_index=True)
    for col,src in (('xs_r16','r16'),('xs_tb4','tb4')):D[col]=D.groupby('t')[src].rank(pct=True)
    return D,ext

@functools.lru_cache(None)
def feats_btc(k):
    d=agg('BTCUSDT',k);lc=np.log(d['c']);sh=lambda x,j:np.concatenate([np.full(j,np.nan),x[:-j]]);o={}
    for j in (1,4,16):o[f'r{j}']=lc-sh(lc,j)
    o['tb4']=pd.Series(d['tb']).rolling(4).sum().to_numpy()/np.maximum(pd.Series(d['v']).rolling(4).sum().to_numpy(),1e-12)-.5
    return o,d

def backtest(T,ext,k,thr,a_bar,b_bar):
    """T: rows of the test window with columns coin,t,pred. Sequential portfolio simulation."""
    T=T[(T.t>=a_bar)&(T.t<b_bar-H)];T=T[np.abs(T.pred)>thr].sort_values(['t','pred'],key=lambda x:x if x.name=='t' else -np.abs(x))
    eq=10000.;busy={};open_=[];trades=[];daily={}
    nb=b_bar;bars_per_day=96//k
    byt={t:g for t,g in T.groupby('t')}
    for t in range(a_bar,b_bar):
        still=[]
        for p in open_:
            if p['x']==t:
                d=ext[p['coin']];xp=d['c'][t]*(1-p['side']*SLIP);ep=p['e']
                ret=p['side']*(xp/ep-1)-2*FEE-p['side']*(d['fcum'][t]-d['fcum'][p['t']]);pnl=p['notional']*ret;eq+=pnl;trades.append((p['coin'],p['t'],p['side'],ret,pnl));busy.pop(p['coin'],None)
            else:still.append(p)
        open_=still
        if t in byt and eq>0:
            for r in byt[t].itertuples():
                if len(open_)>=MAXPOS:break
                if r.coin in busy:continue
                s=1 if r.pred>0 else -1;d=ext[r.coin];ep=d['c'][t]*(1+s*SLIP)
                open_.append(dict(coin=r.coin,t=t,x=t+H,side=s,e=ep,notional=FRAC*eq));busy[r.coin]=1
        if (t+1)%bars_per_day==0:
            mtm=sum(p['notional']*(p['side']*(ext[p['coin']]['c'][t]/p['e']-1)) for p in open_);daily[t]=eq+mtm
    dv=np.array(list(daily.values()));days=len(dv);yrs=days/365.25
    dd=(dv/np.maximum.accumulate(np.maximum(dv,1e-9))-1).min()*100 if days else 0
    tr=pd.DataFrame(trades,columns=['coin','t','side','ret','pnl'])
    cagr=((dv[-1]/10000)**(1/yrs)-1)*100 if days and dv[-1]>0 else -100.
    return dict(final=float(dv[-1]) if days else 10000.,cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else 0.,trades=int(len(tr)),
                win=float((tr.ret>0).mean()*100) if len(tr) else 0.,avg_ret=float(tr.ret.mean()*100) if len(tr) else 0.,long_share=float((tr.side>0).mean()) if len(tr) else 0.),dv

def run(tf):
    t0=time.time();k=TFS[tf];D,ext=build(tf);feat=[c for c in D.columns if c not in ('coin','t','y')]
    print(f'[{tf}] rows {len(D):,} features {len(feat)} built in {time.time()-t0:.0f}s',flush=True);res={}
    bar_min=k*15
    for fn,(a,b) in FOLDS.items():
        ab,bb=a//bar_min,b//bar_min
        trm=(D.t+H<ab)&D.y.notna();te=(D.t>=ab)&(D.t<bb)
        Tr=D[trm];Tr=Tr.sample(min(len(Tr),1500000),random_state=0);lo,hi=Tr.y.quantile([.01,.99]);y=Tr.y.clip(lo,hi)
        X=Tr[feat].astype(np.float32);med=X.median();Xte=D.loc[te,feat].astype(np.float32).fillna(med)
        out={}
        for mname,mk in {'gbm':lambda:HistGradientBoostingRegressor(max_depth=6,max_iter=300,learning_rate=.05,min_samples_leaf=500,random_state=0),
                         'ridge':lambda:make_pipeline(StandardScaler(),Ridge(alpha=10.))}.items():
            m=mk().fit(X.fillna(med),y);p=m.predict(Xte);Te=D.loc[te,['coin','t','y']].copy();Te['pred']=p
            ok=Te.y.notna();ic=float(spearmanr(Te.pred[ok],Te.y[ok])[0]);icd=float(Te[ok].groupby('t').apply(lambda g:spearmanr(g.pred,g.y)[0] if len(g)>5 else np.nan).mean())
            hit=float((np.sign(Te.pred[ok])==np.sign(Te.y[ok])).mean());o={'ic':ic,'ic_xs':icd,'hit':hit}
            for kk in (1,2):
                r,dv=backtest(Te,ext,k,kk*COST,ab,bb);o[f'k{kk}']=r
                if mname=='gbm':np.save(OUT/f'daily_{tf}_{fn}_k{kk}.npy',dv)
                print(f'[{tf}] {fn:7s} {mname:5s} IC {ic:+.3f} xsIC {icd:+.3f} hit {hit:.3f} | thr {kk}xcost: trades {r["trades"]:6d} win {r["win"]:4.1f}% avg {r["avg_ret"]:+.3f}% final {r["final"]:>10,.0f} CAGR {r["cagr"]:7.1f}% DD {r["dd"]:6.1f}% long {r["long_share"]:.2f}',flush=True)
            out[mname]=o
        res[fn]=out
    (OUT/f'result_{tf}.json').write_text(json.dumps(res,indent=1,default=float));print(f'[{tf}] done in {time.time()-t0:.0f}s',flush=True)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    for tf in (sys.argv[1:] or ['4h','1h','30m','15m']):run(tf)
