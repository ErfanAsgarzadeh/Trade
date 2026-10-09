"""How certain is the three-bot profit? Stress tests of the joint account (three_bots_replay.py, defaults 1% / 0.4% / 0.25%,
80% margin cap, $10k compounding on live equity). Every test changes ONE thing and replays the same account.

U1 LUCK (sampling): stationary block bootstrap of the account's daily returns (mean block 20 days, 4000 paths) for a
   5-year and a 1-year horizon -> spread of CAGR / max drawdown that the same edge could have produced.
U2 CONCENTRATION: remove the K best legs (by realised P&L in the base run) and replay: how much rests on a few trades.
U3 COSTS: extra slippage per fill on top of the 2 bps already in the ledgers (total 5 / 10 / 20 bps per fill).
U4 LIQUIDITY: square-root market impact per fill = 0.7 x daily volatility x sqrt(order notional / daily dollar volume),
   daily volume = 30-day causal mean of Binance futures 4h volume x close, scaled by a venue factor (1.0 = Binance,
   0.2 = a venue with 20% of Binance volume, the assumption for LBank). Also the FIX: cap each order at a share of that
   daily volume (1% / 0.5%).
U5 SELECTION (were the coins lucky?): replace each bot's coin list by coins it was NOT chosen on, using the same rules:
   Shahin -> NEW10 (AVAX DOT ATOM FIL DOGE LTC AXS LINK XTZ ALGO), Mojsavar -> OTHER20 (the 20 tested coins not picked
   for C3), Ghoghnous -> IN15 (the main and C3 coins). One bot at a time, and all three together. Coin overlap between
   bots is ignored here (scenario only).
U6 TIME: rolling 12-month returns of the base account (worst / share of negative windows).
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import three_bots_replay as T, pabench as PB, xuni as X, c3bench_d as BD, c3r2_a4_sizing as S
OUT=T.OUT;DAYS=T.DAYS;MIN0=T.MIN0

# ------------------------------------------------------------------ ledgers on other coin lists
def main_legs(symbols):
    F={s:X.frame(s,PB.prep_dir(s)) for s in symbols};case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.01,max_open_positions=4)
    fk={(s,'4h','standard'):F[s] for s in symbols};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    for j,s in enumerate(symbols):
        f=F[s];ix=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
        ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix];low=~(ar>=1.)&(ss[j,:,0]!=0);ss[j,low,0]=0;ss[j,low,3]=-np.inf
    prices=np.stack([np.load(PB.prep_dir(s)/s/'prices.npy') for s in symbols]);funding=np.stack([np.load(PB.prep_dir(s)/s/'funding.npy') for s in symbols])
    a,t,curve=simulate(prices,funding,np.ascontiguousarray(ss),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.01,4,step,True,slip=2e-4,floor_on=True,floor_trigger=1.,floor_lock=.1,legacy_cap=100.)
    return [dict(bot='main',coin=symbols[int(r[0])],side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),stop_frac=float(r[7]/r[4]),
                 risk_scale=float(r[15]/r[14])/.01,root=('main',int(r[17])),is_add=int(r[18])!=0) for r in t if r[2]>0]

def c3_legs(coins):
    out=[]
    for s in coins:
        d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n'])
        Tt=S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
        for i,r in enumerate(Tt):
            e,x=int(r[0]),int(r[1])
            out.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('c3',s,i),is_add=False))
    return out

def pa_legs(coins):
    out=[]
    for s in coins:
        d=PB.coin(s);n=d['n'];side=d['sig']['side'][:n].copy();side[(d['h'][:n]-d['l'][:n])<1.1*d['atr'][:n]]=0;Tt=PB.run(d,side=side,target_r=0.)
        for i,r in enumerate(Tt):
            dist=PB.RISK*1e4/r[5]-r[6]*(2*PB.FEE+2*PB.SLIP)
            out.append(dict(bot='pa',coin=s,side=int(r[2]),em=int(r[0]),xm=int(r[1]),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),stop_frac=float(dist/r[6]),risk_scale=1.,root=('pa',s,i),is_add=False))
    return out

# ------------------------------------------------------------------ liquidity
@functools.lru_cache(None)
def liquidity(coin):
    """Per day: causal 30-day mean daily dollar volume and 30-day daily-return volatility (both known before the day)."""
    b=PB._bars(coin);n=len(b['c'])//6*6;dv=(b['v'][:n]*b['c'][:n]).reshape(-1,6).sum(1);cl=b['c'][:n].reshape(-1,6)[:,-1]
    adv=pd.Series(dv).replace(0,np.nan).rolling(30,min_periods=10).mean().shift(1).bfill().to_numpy()
    vol=pd.Series(cl).pct_change().rolling(30,min_periods=10).std().shift(1).bfill().to_numpy()
    zero=pd.Series(dv).rolling(3).sum().shift(1).fillna(1).to_numpy()==0   # no trading on that venue recently
    return adv,vol,zero

# ------------------------------------------------------------------ generalised replay
def replay(legs,risk=None,margin_cap=.8,extra_bps=0.,impact_venue=None,liq_cap=None,exclude=frozenset()):
    risk={**T.DEFAULT,**(risk or {})};L=[l for l in legs if (l['bot'],l['coin'],l['em']) not in exclude]
    ev=[(l['em'],1,i) for i,l in enumerate(L)]+[(l['xm'],0,i) for i,l in enumerate(L)]+[((d+1)*1440-1,2,d) for d in range(DAYS)];ev.sort(key=lambda e:(e[0],e[1]))
    realized=0.;open_={};qty={};cost={};skipped=set();daily=np.zeros(DAYS);pnl={};impact_paid=0.;capped=0
    def equity(m):return T.SEED+realized+sum(qty[i]*L[i]['side']*(T.closes(L[i]['coin'])[m]-L[i]['entry']) for i in open_)
    def used():return sum(qty[i]*L[i]['entry']/T.LEV for i in open_)
    for m,typ,i in ev:
        if typ==0:
            if i in open_:
                l=L[i];p=qty[i]*l['unit']-cost[i];realized+=p;pnl[l['bot']]=pnl.get(l['bot'],0.)+p;del open_[i]
        elif typ==1:
            l=L[i]
            if l['is_add'] and l['root'] in skipped:continue
            eq=equity(m)
            if eq<=0:skipped.add(l['root']);continue
            notional=risk[l['bot']]*l['risk_scale']*eq/(l['stop_frac']+T.FEE_RT+T.SLIP_ALLOW)
            free=max(0.,margin_cap*eq-used())/(1+margin_cap*T.LEV*T.FEE_RT)*T.LEV;notional=min(notional,free)
            day=min(m//1440,DAYS-1);adv,vol,zero=liquidity(l['coin']) if (impact_venue or liq_cap) else (None,None,None)
            if liq_cap:
                lim=liq_cap*adv[day]*(impact_venue or 1.)
                if notional>lim:notional=lim;capped+=1
            if notional<20:skipped.add(l['root']);continue
            c=notional*2*extra_bps/1e4
            if impact_venue:
                imp=.7*vol[day]*np.sqrt(notional/max(adv[day]*impact_venue,1.));c+=notional*2*imp;impact_paid+=notional*2*imp
            qty[i]=notional/l['entry'];cost[i]=c;open_[i]=1
        else:daily[i]=equity(m)
    r=np.diff(np.concatenate([[T.SEED],daily]))/np.concatenate([[T.SEED],daily[:-1]]);st=X.stats(r)
    return dict(final=float(daily[-1]),cagr=st['full'][1],dd=st['full'][2],calmar=st['full'][0],train=st['train'],valid=st['oos'],pnl=pnl,impact_paid=impact_paid,capped=capped,_r=r)

def bootstrap(r,horizon,n=4000,block=20,seed=7):
    rng=np.random.default_rng(seed);N=len(r);cagr=np.empty(n);dd=np.empty(n);tot=np.empty(n)
    for k in range(n):
        idx=np.empty(horizon,int);i=rng.integers(N)
        for t in range(horizon):
            idx[t]=i;i=rng.integers(N) if rng.random()<1/block else (i+1)%N
        eq=np.cumprod(1+r[idx]);tot[k]=eq[-1]-1;cagr[k]=eq[-1]**(365.25/horizon)-1;dd[k]=(1-eq/np.maximum.accumulate(np.maximum(eq,1.))).max()
    q=lambda a:{p:round(float(np.percentile(a,p))*100,1) for p in (5,25,50,75,95)}
    return dict(cagr=q(cagr),dd=q(dd),total=q(tot),p_loss=float((tot<0).mean()*100),p_dd30=float((dd>.30).mean()*100),p_dd40=float((dd>.40).mean()*100),p_dd50=float((dd>.50).mean()*100))

def brief(r):return {k:(round(v,2) if isinstance(v,float) else v) for k,v in r.items() if k not in ('_r','pnl')}|{'pnl':{k:round(v) for k,v in r['pnl'].items()}}

def main():
    res={};base_legs=T.ledgers();b=replay(base_legs);res['base']=brief(b)
    chk=T.replay();assert abs(chk['final_equity']-b['final'])<1e-6*b['final'],'generalised replay must reproduce three_bots_replay'
    print('BASE',res['base'],flush=True)
    res['U1_5y']=bootstrap(b['_r'],len(b['_r']));res['U1_1y']=bootstrap(b['_r'],365);print('U1 5y',res['U1_5y']);print('U1 1y',res['U1_1y'],flush=True)
    t=pd.read_csv(OUT/'trades.csv').sort_values('pnl',ascending=False);res['U2']={}
    for K in (10,25,50,100):
        ex=frozenset((r.bot,r.coin,int(r.entry_min)) for r in t.head(K).itertuples());x=replay(base_legs,exclude=ex);res['U2'][K]=brief(x);print('U2 drop top',K,res['U2'][K],flush=True)
    res['U3']={}
    for tot in (5,10,20):x=replay(base_legs,extra_bps=tot-2);res['U3'][tot]=brief(x);print('U3 total bps',tot,res['U3'][tot],flush=True)
    res['U4']={}
    for name,kw in (('binance',dict(impact_venue=1.)),('venue20',dict(impact_venue=.2)),('venue20_cap1',dict(impact_venue=.2,liq_cap=.01)),('venue20_cap05',dict(impact_venue=.2,liq_cap=.005)),
                    ('venue20_cap05_bps5',dict(impact_venue=.2,liq_cap=.005,extra_bps=3))):
        x=replay(base_legs,**kw);res['U4'][name]=brief(x);print('U4',name,res['U4'][name],flush=True)
    by={k:[l for l in base_legs if l['bot']==k] for k in ('main','c3','pa')};alt={'main':main_legs(list(X.NEW)),'c3':c3_legs(list(BD.B.OTHER20)),'pa':pa_legs(list(PB.IN15))};res['U5']={}
    for k in ('main','c3','pa'):
        legs=[l for kk in by for l in (alt[kk] if kk==k else by[kk])];x=replay(legs);res['U5'][k]=brief(x);print('U5 swap',k,res['U5'][k],flush=True)
    x=replay([l for kk in alt for l in alt[kk]]);res['U5']['all']=brief(x);res['U5_all_boot']=bootstrap(x['_r'],len(x['_r']));print('U5 all',res['U5']['all'],res['U5_all_boot'],flush=True)
    for k in ('main','c3','pa'):x=replay(alt[k],risk=None);res['U5'][k+'_alone']=brief(x);print('U5 alone',k,res['U5'][k+'_alone'],flush=True)
    s=pd.Series(np.cumprod(1+b['_r']));roll=(s/s.shift(365)-1).dropna()
    res['U6']=dict(worst=float(roll.min()*100),best=float(roll.max()*100),median=float(roll.median()*100),share_negative=float((roll<0).mean()*100),share_below_20=float((roll<.2).mean()*100))
    print('U6',res['U6'])
    (OUT/'uncertainty.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
