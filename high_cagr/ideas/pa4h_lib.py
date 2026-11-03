"""4h feature library for the expanded universe (35 traded + up to 69 training-only coins), built from Binance 4h klines,
funding and 5-min metrics only (so every coin gets identical features). Causal: values at bar t use bars <= t; a metrics
record stamped T covers T..T+5min and is used only after T+5min.
Families: technical (trend, momentum, volatility, trend quality, volume, candle), market (BTC, breadth, relative strength,
correlation), sentiment/positioning (taker buy share, open interest, long/short ratios, taker long/short ratio, funding,
Fear & Greed, stablecoin supply, market open interest) and PRICE ACTION:
  candle patterns  pin bar, engulfing, inside bar, key reversal, fakey, NR7, climax bar, EMA20 rejection
  structure        2/2 fractal swings (confirmed 2 bars later): break of structure (BOS), change of character (CHoCH),
                   swing-failure pattern (SFP, liquidity sweep), double top/bottom, fair-value gap (FVG), box breakout
                   (10-bar range < 1.5 ATR broken), swing structure score (higher highs/lows minus lower highs/lows over the
                   last 4 swings), distance to the last swing high / low and to the previous day's high / low (ATR units)
Signed pattern arrays are +1 bullish / -1 bearish at the bar where the pattern completes.
"""
import sys,json,glob,zipfile,functools
import numpy as np,pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import criteria_lib as CL, pa2_confluence as CF
U=ROOT/'high_cagr/cache_universe';SC=ROOT/'high_cagr/cache_sentiment';BAR=240*60000;N=(rs.END-rs.START)//BAR
PA=['pin','engulf','inside','keyrev','fakey','climax','emarej','bos','choch','sfp','dbl','fvg','boxbrk']

def universe():
    sel=json.loads((U/'selected.json').read_text())['chosen']
    return list(CL.COINS)+[s for s in sel if s not in CL.COINS]

def _zips(pat):
    out=[]
    for z in sorted(glob.glob(str(U/pat))):
        try:
            with zipfile.ZipFile(z) as zz:out.append(pd.read_csv(zz.open(zz.namelist()[0]),header=None,low_memory=False))
        except Exception:pass
    return out

@functools.lru_cache(None)
def raw(s):
    f=U/f'k4_{s}.npz'
    if f.exists():return dict(np.load(f))
    parts=_zips(f'data/futures/um/monthly/klines/{s}/4h/*.zip')+_zips(f'data/futures/um/daily/klines/{s}/4h/*.zip')
    d=pd.concat(parts,ignore_index=True);d=d[pd.to_numeric(d[0],errors='coerce').notna()].astype(float);d[0]=np.where(d[0]>1e14,d[0]/1000,d[0])
    d=d.drop_duplicates(0).set_index(0).sort_index();idx=rs.START+np.arange(N)*BAR;d=d.reindex(idx)
    c=d[4].ffill().to_numpy();o=d[1].fillna(pd.Series(c,index=d.index)).to_numpy();h=np.fmax(d[2].to_numpy(),np.fmax(o,c));l=np.fmin(d[3].to_numpy(),np.fmin(o,c))
    h=np.where(np.isfinite(h),h,c);l=np.where(np.isfinite(l),l,c);v=d[5].fillna(0).to_numpy();tb=d[9].fillna(0).to_numpy()
    fr=_zips(f'data/futures/um/monthly/fundingRate/{s}/*.zip');fund=np.zeros(N)
    if fr:
        F=pd.concat(fr,ignore_index=True);F=F[pd.to_numeric(F[0],errors='coerce').notna()].astype(float);b=((F[0].to_numpy()-rs.START)//BAR).astype(int);m=(b>=0)&(b<N);np.add.at(fund,b[m],F[2].to_numpy()[m])
    met=np.full((4,N),np.nan);mp=[]
    for z in sorted(glob.glob(str(U/f'data/futures/um/daily/metrics/{s}/*.zip'))):
        try:
            with zipfile.ZipFile(z) as zz:mp.append(pd.read_csv(zz.open(zz.namelist()[0]),usecols=['create_time','sum_open_interest','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']))
        except Exception:pass
    if not mp:   # traded coins: metrics were downloaded earlier into the sentiment cache
        for z in sorted(glob.glob(str(SC/'metrics'/s/'*.zip'))):
            try:
                with zipfile.ZipFile(z) as zz:mp.append(pd.read_csv(zz.open(zz.namelist()[0]),usecols=['create_time','sum_open_interest','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']))
            except Exception:pass
    if mp:
        M=pd.concat(mp,ignore_index=True);t=pd.to_datetime(M.create_time).astype('int64')//10**6;M=M.assign(t=t).sort_values('t').drop_duplicates('t')
        closes=rs.START+(np.arange(N)+1)*BAR;ix=np.searchsorted(M.t.to_numpy(),closes-300000,side='right')-1;ok=ix>=0;age=np.full(N,1e18);age[ok]=closes[ok]-300000-M.t.to_numpy()[ix[ok]]
        for i,cn in enumerate(['sum_open_interest','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']):
            x=pd.to_numeric(M[cn],errors='coerce').to_numpy();y=np.full(N,np.nan);y[ok]=x[ix[ok]];y[age>3600000]=np.nan;met[i]=y
    out=dict(o=o,h=h,l=l,c=c,v=v,tb=tb,fund=fund,oi=met[0],lst=met[1],lsg=met[2],tls=met[3]);np.savez(f,**out);return out

def atr14(h,l,c):
    pc=np.concatenate([[c[0]],c[:-1]]);tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)));return pd.Series(tr).ewm(alpha=1/14,adjust=False).mean().to_numpy()
def ema(x,n):return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()
def sh(x,k):return np.concatenate([np.full(k,np.nan),x[:-k]]) if k>0 else x

def swings(h,l):
    """confirmed 2/2 fractals: arrays of last confirmed swing high/low value and the one before, known at each bar."""
    n=len(h);ph=np.zeros(n,bool);pl=np.zeros(n,bool)
    ph[2:-2]=(h[2:-2]>h[1:-3])&(h[2:-2]>h[:-4])&(h[2:-2]>=h[3:-1])&(h[2:-2]>=h[4:])
    pl[2:-2]=(l[2:-2]<l[1:-3])&(l[2:-2]<l[:-4])&(l[2:-2]<=l[3:-1])&(l[2:-2]<=l[4:])
    out={k:np.full(n,np.nan) for k in ('sh1','sh2','sl1','sl2','sh3','sl3')};H=[];Lw=[]
    for t in range(n):
        i=t-2
        if i>=2:
            if ph[i]:H.append(h[i])
            if pl[i]:Lw.append(l[i])
        if H:out['sh1'][t]=H[-1]
        if len(H)>1:out['sh2'][t]=H[-2]
        if len(H)>2:out['sh3'][t]=H[-3]
        if Lw:out['sl1'][t]=Lw[-1]
        if len(Lw)>1:out['sl2'][t]=Lw[-2]
        if len(Lw)>2:out['sl3'][t]=Lw[-3]
    return out

def price_action(o,h,l,c,v,a,e20):
    rg=np.maximum(h-l,1e-12);body=c-o;lw=np.minimum(o,c)-l;uw=h-np.maximum(o,c);P={}
    P['pin']=np.where((lw>=2/3*rg)&(c>=l+2/3*rg),1,np.where((uw>=2/3*rg)&(c<=l+1/3*rg),-1,0))
    pb=sh(body,1);po,pc=sh(o,1),sh(c,1)
    P['engulf']=np.where((pb<0)&(body>0)&(c>=po)&(o<=pc),1,np.where((pb>0)&(body<0)&(c<=po)&(o>=pc),-1,0))
    ins=(h<sh(h,1))&(l>sh(l,1));P['inside']=np.where(ins,np.sign(body),0)
    P['keyrev']=np.where((l<sh(l,1))&(c>sh(c,1))&(c>o),1,np.where((h>sh(h,1))&(c<sh(c,1))&(c<o),-1,0))
    ins1=sh(ins.astype(float),1)==1;ih,il=sh(h,1),sh(l,1)
    P['fakey']=np.where(ins1&(l<il)&(c>il),1,np.where(ins1&(h>ih)&(c<ih),-1,0))
    vavg=pd.Series(v).rolling(20).mean().to_numpy();P['climax']=np.where((rg>2*a)&(v>2*vavg),np.sign(body),0)
    P['emarej']=np.where((l<=e20)&(c>e20)&(body>0),1,np.where((h>=e20)&(c<e20)&(body<0),-1,0))
    S=swings(h,l);up_brk=(c>S['sh1'])&(sh(c,1)<=sh(S['sh1'],1));dn_brk=(c<S['sl1'])&(sh(c,1)>=sh(S['sl1'],1))
    P['bos']=np.where(up_brk,1,np.where(dn_brk,-1,0))
    bear_struct=(S['sh1']<S['sh2'])&(S['sl1']<S['sl2']);bull_struct=(S['sh1']>S['sh2'])&(S['sl1']>S['sl2'])
    P['choch']=np.where(up_brk&bear_struct,1,np.where(dn_brk&bull_struct,-1,0))
    P['sfp']=np.where((l<S['sl1'])&(c>S['sl1']),1,np.where((h>S['sh1'])&(c<S['sh1']),-1,0))
    P['dbl']=np.where(np.abs(S['sl1']-S['sl2'])<.3*a,1,0)-np.where(np.abs(S['sh1']-S['sh2'])<.3*a,1,0)
    P['fvg']=np.where(l>sh(h,2),1,np.where(h<sh(l,2),-1,0))
    bh=pd.Series(h).shift(1).rolling(10).max().to_numpy();bl=pd.Series(l).shift(1).rolling(10).min().to_numpy();tight=(bh-bl)<1.5*a
    P['boxbrk']=np.where(tight&(c>bh),1,np.where(tight&(c<bl),-1,0))
    struct=(np.sign(S['sh1']-S['sh2'])+np.sign(S['sl1']-S['sl2'])+np.sign(S['sh2']-S['sh3'])+np.sign(S['sl2']-S['sl3']))
    return {k:np.nan_to_num(v_).astype(np.int8) for k,v_ in P.items()},S,np.nan_to_num(struct)

@functools.lru_cache(None)
def coin(s):
    r=raw(s);o,h,l,c,v,tb=r['o'],r['h'],r['l'],r['c'],r['v'],r['tb'];a=atr14(h,l,c);e20,e50,e200=ema(c,20),ema(c,50),ema(c,200);F={}
    F['trend20']=c/e20-1;F['trend50']=c/e50-1;F['trend200']=c/e200-1;F['slope20']=(e20-sh(e20,6))/a;F['slope50']=(e50-sh(e50,6))/a;F['slope200']=(e200-sh(e200,12))/a
    m=ema(c,12)-ema(c,26);F['macd']=(m-ema(m,9))/a
    d=np.diff(c,prepend=c[0]);up=pd.Series(np.maximum(d,0)).ewm(alpha=1/14,adjust=False).mean();dn=pd.Series(np.maximum(-d,0)).ewm(alpha=1/14,adjust=False).mean();F['rsi']=((100-100/(1+up/(dn+1e-12)))-50).to_numpy()/50
    lo14=pd.Series(l).rolling(14).min().to_numpy();hi14=pd.Series(h).rolling(14).max().to_numpy();F['stoch']=(c-lo14)/np.where(hi14>lo14,hi14-lo14,np.nan)*2-1
    tp=(h+l+c)/3;ma=pd.Series(tp).rolling(20).mean().to_numpy();md=pd.Series(np.abs(tp-ma)).rolling(20).mean().to_numpy();F['cci20']=(tp-ma)/(.015*md+1e-12)/200
    m20=pd.Series(c).rolling(20).mean().to_numpy();s20=pd.Series(c).rolling(20).std().to_numpy();F['bbpos']=(c-m20)/(2*s20+1e-12);F['bbwidth']=s20/m20
    for n_ in (20,60):
        hh=pd.Series(h).rolling(n_).max().to_numpy();ll=pd.Series(l).rolling(n_).min().to_numpy();F[f'don{n_}']=(c-ll)/np.where(hh>ll,hh-ll,np.nan)*2-1
    for k in (5,20,60,120):F[f'ret{k}']=c/sh(c,k)-1
    pdm=np.maximum(h-sh(h,1),0);ndm=np.maximum(sh(l,1)-l,0);pdm,ndm=np.where(pdm>ndm,pdm,0),np.where(ndm>pdm,ndm,0)
    pdi=pd.Series(np.nan_to_num(pdm)).ewm(alpha=1/14,adjust=False).mean().to_numpy()/a;ndi=pd.Series(np.nan_to_num(ndm)).ewm(alpha=1/14,adjust=False).mean().to_numpy()/a
    F['adx']=pd.Series(np.abs(pdi-ndi)/(pdi+ndi+1e-12)*100).ewm(alpha=1/14,adjust=False).mean().to_numpy()
    F['er20']=np.abs(c-sh(c,20))/(pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(20).sum().to_numpy()+1e-12)
    r1=np.diff(np.log(c),prepend=np.nan);r4=np.log(c)-np.log(sh(c,4));F['vratio']=pd.Series(r4).rolling(100).var().to_numpy()/(4*pd.Series(r1).rolling(100).var().to_numpy()+1e-18)
    F['vol']=a/c;F['volrank']=CF.prank(np.ascontiguousarray(a/c),500);pk=np.log(h/np.maximum(l,1e-12))**2/(4*np.log(2));F['volpk']=np.sqrt(pd.Series(pk).rolling(5).mean().to_numpy())/(np.sqrt(pd.Series(pk).rolling(50).mean().to_numpy())+1e-12)
    F['atr_chg']=a/sh(a,20)-1;F['relvol']=v/(pd.Series(v).rolling(20).mean().to_numpy()+1e-12);obv=np.cumsum(np.sign(np.diff(c,prepend=c[0]))*v);F['obv_slope']=(obv-sh(obv,10))/(pd.Series(v).rolling(20).mean().to_numpy()*10+1e-12)
    rg=np.where(h>l,h-l,np.nan);F['body']=(c-o)/rg;F['range_atr']=(h-l)/a;F['gap']=(o-sh(c,1))/a;F['_lw']=(np.minimum(o,c)-l)/rg;F['_uw']=(h-np.maximum(o,c))/rg
    th=(pd.Series(h).rolling(9).max()+pd.Series(l).rolling(9).min()).to_numpy()/2;kj=(pd.Series(h).rolling(26).max()+pd.Series(l).rolling(26).min()).to_numpy()/2
    ssa=sh((th+kj)/2,26);ssb=sh((pd.Series(h).rolling(52).max()+pd.Series(l).rolling(52).min()).to_numpy()/2,26);F['ichi_cloud']=(c-(ssa+ssb)/2)/a;F['kijun_dist']=(c-kj)/a
    dc=c[5::6];de=ema(dc,50);hd=np.full(len(c),np.nan);idx=np.arange(len(c));k=(idx+1)//6-1;ok=k>=0;hd[ok]=np.sign(dc[k[ok]]-de[k[ok]]);F['htf']=hd
    dh=pd.Series(h).rolling(6).max().to_numpy()[5::6];dl=pd.Series(l).rolling(6).min().to_numpy()[5::6];pdh=np.full(len(c),np.nan);pdl=np.full(len(c),np.nan);pdh[ok]=dh[k[ok]];pdl[ok]=dl[k[ok]]
    F['funding8h']=pd.Series(r['fund']).rolling(2).sum().to_numpy()*1e3
    F['tbr6']=pd.Series(tb).rolling(6).sum().to_numpy()/np.maximum(pd.Series(v).rolling(6).sum().to_numpy(),1e-12)-.5
    ratio=np.where(v>0,tb/np.maximum(v,1e-12),np.nan);F['tbr_z']=(ratio-pd.Series(ratio).rolling(60).mean().to_numpy())/(pd.Series(ratio).rolling(60).std().to_numpy()+1e-12)
    oi=np.where(r['oi']>0,r['oi'],np.nan);F['oi_chg6']=oi/sh(oi,6)-1;F['oi_chg42']=oi/sh(oi,42)-1;F['oi_price']=np.sign(F['ret5'])*F['oi_chg6']
    lg=np.log(np.where(r['lsg']>0,r['lsg'],np.nan));lt=np.log(np.where(r['lst']>0,r['lst'],np.nan));F['ls_global']=lg;F['ls_global_z']=(lg-pd.Series(lg).rolling(180,min_periods=60).mean().to_numpy())/(pd.Series(lg).rolling(180,min_periods=60).std().to_numpy()+1e-12)
    F['ls_top']=lt;F['smart_vs_crowd']=lt-lg;F['taker_ls6']=pd.Series(np.log(np.where(r['tls']>0,r['tls'],np.nan))).rolling(6,min_periods=3).mean().to_numpy()
    P,S,struct=price_action(o,h,l,c,v,a,e20);F['struct']=struct;F['_sh1']=S['sh1'];F['_sl1']=S['sl1'];F['_pdh']=pdh;F['_pdl']=pdl
    return dict(F=F,P=P,o=o,h=h,l=l,c=c,a=a,e20=e20,e50=e50,e200=e200,fund=r['fund'],oiv=np.nan_to_num(oi)*c,ret1=r1)

@functools.lru_cache(1)
def market():
    U_=universe();b=coin('BTCUSDT');M={}
    M['btc_trend200']=b['F']['trend200'];M['btc_ret6']=b['c']/sh(b['c'],6)-1;M['btc_adx']=b['F']['adx'];M['btc_volrank']=b['F']['volrank']
    above=np.array([coin(s)['F']['trend50']>0 for s in U_]).astype(float);br=np.nanmean(above,0);M['breadth']=br-.5;M['breadth_chg']=br-sh(br,12)
    r60=pd.DataFrame({s:coin(s)['F']['ret60'] for s in U_});M['_rs']=r60.rank(axis=1,pct=True)*2-1
    oiv=np.nansum([np.nan_to_num(coin(s)['oiv']) for s in U_],0);oiv[oiv==0]=np.nan;M['mkt_oi_chg42']=oiv/sh(oiv,42)-1
    rb=b['ret1'];M['_corr']={s:pd.Series(coin(s)['ret1']).rolling(60).corr(pd.Series(rb)).to_numpy() for s in U_}
    closes=rs.START+(np.arange(N)+1)*BAR
    fd=json.loads((SC/'fng.json').read_text())['data'];fs=pd.Series({int(x['timestamp'])*1000:float(x['value']) for x in fd}).sort_index()
    st=json.loads((SC/'stablecoins.json').read_text());ss=pd.Series({int(x['date'])*1000:float(x['totalCirculatingUSD']['peggedUSD']) for x in st}).sort_index()
    asof=lambda ser:np.where((ix:=np.searchsorted(ser.index.to_numpy(),closes-86400000,side='right')-1)>=0,ser.to_numpy()[np.maximum(ix,0)],np.nan)
    f=asof(fs);s_=asof(ss);M['fng']=f;M['fng_chg7']=f-sh(f,42);M['stable_g30']=s_/sh(s_,180)-1
    mom=pd.DataFrame({s:coin(s)['c']/sh(coin(s)['c'],180)-1 for s in U_}).rank(axis=1,pct=True);M['_mom30']=mom
    return M

TECH=['trend20','trend50','trend200','slope20','slope50','slope200','macd','rsi','stoch','cci20','bbpos','don20','don60','ret5','ret20','ret60','ret120','obv_slope','body','gap','ichi_cloud','kijun_dist','htf',
      'adx','er20','vratio','vol','volrank','volpk','bbwidth','atr_chg','relvol','range_atr','wick_rej','btc_trend200','btc_ret6','btc_adx','btc_volrank','breadth','breadth_chg','rs60','corr_btc','mom30']
SENT=['funding8h','tbr6','tbr_z','oi_chg6','oi_chg42','oi_price','ls_global','ls_global_z','ls_top','smart_vs_crowd','taker_ls6','fng','fng_chg7','fng_extreme','stable_g30','mkt_oi_chg42']
PAF=[f'pa_{p}_{w}' for p in PA for w in ('with','against')]+['pa_count_with','pa_count_against','struct','dist_swing_hi','dist_swing_lo','dist_pdh','dist_pdl']
SIGNED=set(['trend20','trend50','trend200','slope20','slope50','slope200','macd','rsi','stoch','cci20','bbpos','don20','don60','ret5','ret20','ret60','ret120','obv_slope','body','gap','ichi_cloud','kijun_dist','htf',
      'btc_trend200','btc_ret6','breadth','breadth_chg','rs60','funding8h','tbr6','tbr_z','oi_price','ls_global','ls_global_z','ls_top','smart_vs_crowd','taker_ls6','stable_g30','mkt_oi_chg42','struct'])

def at(s,t,side):
    C=coin(s);F=C['F'];M=market();r={}
    for k in TECH+SENT:
        if k in F:x=F[k][t]
        elif k=='wick_rej':x=F['_lw'][t] if side>0 else F['_uw'][t]
        elif k=='rs60':x=M['_rs'][s].iloc[t]
        elif k=='corr_btc':x=M['_corr'][s][t]
        elif k=='mom30':m=M['_mom30'][s].iloc[t];x=m if side>0 else 1-m
        elif k=='fng':x=(M['fng'][t]-50)/50
        elif k=='fng_extreme':x=abs(M['fng'][t]-50)/50
        elif k=='fng_chg7':x=M['fng_chg7'][t]/50
        else:x=M[k][t]
        r[k]=side*x if k in SIGNED else x
    P=C['P'];w=a_=0
    for p in PA:
        win=P[p][max(t-2,0):t+1];r[f'pa_{p}_with']=float((win==side).any());r[f'pa_{p}_against']=float((win==-side).any());w+=r[f'pa_{p}_with'];a_+=r[f'pa_{p}_against']
    r['pa_count_with']=w;r['pa_count_against']=a_;c=C['c'][t];at_=C['a'][t]
    r['dist_swing_hi']=(F['_sh1'][t]-c)/at_*side if side>0 else (c-F['_sl1'][t])/at_
    r['dist_swing_lo']=(c-F['_sl1'][t])/at_ if side>0 else (F['_sh1'][t]-c)/at_
    r['dist_pdh']=side*(F['_pdh'][t]-c)/at_ if side>0 else (c-F['_pdl'][t])/at_
    r['dist_pdl']=(c-F['_pdl'][t])/at_ if side>0 else (F['_pdh'][t]-c)/at_
    return r
