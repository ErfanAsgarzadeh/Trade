"""Three bots on ONE paper account, 2021-10-05 .. 2026-10-04, as if the bot had been switched on at the start.

Bots (deployed defaults): Shahin = main bot (2A+5A Donchian10+Kumo 4h, 5 coins, 1.0%), Mojsavar = C3+D (4h pullback,
10 coins, 0.4%), Ghoghnous = PA C2 (4h key reversal, no target, signal range >= 1.1 ATR, low-volatility gate volrank < 0.354, exit on an
opposite key reversal; 20 coins, 0.4%; high_cagr/ideas/pa2_final.py F3_vol_opp). Until 2026-10-09 it was C1 at 0.25%.

Method (two steps, so that every risk level can be replayed quickly):
1. Trade ledgers from the research engines that were verified against the live code: Shahin = high_cagr.kernel_fixes
   (as bench/htf_confirm 2A+5A, 4 slots, pyramid, its own margin cap opened so that only the shared cap below binds),
   Mojsavar = c3r2_a4_sizing.engine_s on c3bench_d confirm signals, Ghoghnous = pabench.run (minute fills).
   Each leg keeps its entry/exit time and price, its stop distance and its net P&L per unit (fees, slippage, funding).
2. Event replay on one account starting at $10,000: at every entry the size is
   risk% x equity / (stop distance % + 0.12% fee + 0.04% slippage allowance)   (same formula as the live bot),
   equity = seed + realized + unrealized of all open legs at that minute; isolated leverage 5; the new margin
   (notional / 5) must fit in margin_cap x equity - margin already used (the live shared pool, minus the fee reserve);
   if it does not fit the order is reduced to the free margin, below $20 notional it is skipped (a skipped Shahin root
   also skips its pyramid add). Daily equity is marked at each UTC day close.
Limitations: ledgers are produced once per bot (exits do not depend on size); Shahin's 2% daily-loss stop, exchange
minimums/precision and the live polling delay are not modelled; Shahin's slot logic is the kernel's.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import bench, htf_confirm as hc, c3bench_d as BD, c3r2_a4_sizing as S, pabench as PB, xuni as X
OUT=X.OUT/'three_bots';NAMES={'main':'Shahin','c3':'Mojsavar','pa':'Ghoghnous'}
DEFAULT=dict(main=.01,c3=.004,pa=.004);FEE_RT=.0012;SLIP_ALLOW=.0004;LEV=5;SEED=10000.;DAYS=PB.days()
MIN0=lambda ts:int((ts-rs.START)//60000)

@functools.lru_cache(1)
def ledgers():
    legs=[]
    # Shahin
    ctx=bench.load();c=hc.build(ctx,None);sig=np.ascontiguousarray(c.get('sig',ctx['sig']),dtype=np.float64);bb=np.ascontiguousarray(c.get('bb',ctx['bb']),dtype=np.float64)
    kw=dict(c.get('kwargs',{}))
    if sig.shape[2]>=5:kw['risk_col']=4
    a,t,curve=simulate(ctx['prices'],ctx['funding'],sig,bb,rs.START,0,(rs.END-rs.START)//60000,.01,4,ctx['step'],True,slip=2e-4,legacy_cap=100.,**kw)
    for r in t:
        if r[2]<=0:continue
        legs.append(dict(bot='main',coin=rs.SYMBOLS[int(r[0])],side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),
                         stop_frac=float(r[7]/r[4]),risk_scale=float(r[15]/r[14])/.01,root=('main',int(r[17])),is_add=int(r[18])!=0))
    # Mojsavar
    for s in B_MAIN10():
        d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n'])
        T=S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
        for i,r in enumerate(T):
            e,x=int(r[0]),int(r[1])
            legs.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                             stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('c3',s,i),is_add=False))
    # Ghoghnous (C2)
    from high_cagr.ideas import pa2_final as F
    for s in PB.OTHER20:
        d=PB.coin(s);T=F.run(d,'vol',True)
        for i,r in enumerate(T):
            dist=PB.RISK*1e4/r[5]-r[6]*(2*PB.FEE+2*PB.SLIP)
            legs.append(dict(bot='pa',coin=s,side=int(r[2]),em=int(r[0]),xm=int(r[1]),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                             stop_frac=float(dist/r[6]),risk_scale=1.,root=('pa',s,i),is_add=False))
    return legs

def B_MAIN10():return BD.B.MAIN10

@functools.lru_cache(None)
def closes(coin):return PB._px(coin)[:,3]

def replay(risk=None,margin_cap=.8,bots=('main','c3','pa'),detail=False):
    risk={**DEFAULT,**(risk or {})};L=[l for l in ledgers() if l['bot'] in bots]
    ev=[(l['em'],1,i) for i,l in enumerate(L)]+[(l['xm'],0,i) for i,l in enumerate(L)]+[((d+1)*1440-1,2,d) for d in range(DAYS)]
    ev.sort(key=lambda e:(e[0],e[1]))
    realized=0.;open_={};qty={};skipped_roots=set();daily=np.zeros(DAYS);pnl={b:0. for b in bots};n={b:0 for b in bots}
    rej={b:0 for b in bots};shrunk={b:0 for b in bots};mu=[];peak_m=0.;trades=[]
    def equity(m):
        u=0.
        for i in open_:
            l=L[i];u+=qty[i]*l['side']*(closes(l['coin'])[m]-l['entry'])
        return SEED+realized+u
    def used():return sum(qty[i]*L[i]['entry']/LEV for i in open_)
    for m,typ,i in ev:
        if typ==0:
            if i in open_:
                l=L[i];p=qty[i]*l['unit'];realized+=p;pnl[l['bot']]+=p;del open_[i]
                if detail:trades.append((l['bot'],l['coin'],l['side'],l['em'],l['xm'],qty[i]*l['entry'],p))
        elif typ==1:
            l=L[i]
            if l['is_add'] and l['root'] in skipped_roots:continue
            eq=equity(m)
            if eq<=0:skipped_roots.add(l['root']);rej[l['bot']]+=1;continue
            r=risk[l['bot']]*l['risk_scale'];notional=r*eq/(l['stop_frac']+FEE_RT+SLIP_ALLOW)
            free=max(0.,margin_cap*eq-used())/(1+margin_cap*LEV*FEE_RT)*LEV
            cut=notional>free
            if cut:notional=free
            if notional<20:skipped_roots.add(l['root']);rej[l['bot']]+=1;continue
            shrunk[l['bot']]+=int(cut)
            qty[i]=notional/l['entry'];open_[i]=1;n[l['bot']]+=1;um=used()/eq;peak_m=max(peak_m,um)
        else:
            eq=equity(m);daily[i]=eq;mu.append(used()/eq if eq>0 else 0.)
    r=np.diff(np.concatenate([[SEED],daily]))/np.concatenate([[SEED],daily[:-1]])
    st=X.stats(r);yrs=pd.Series(daily,index=pd.date_range('2021-10-05',periods=DAYS)).resample('YE').last()
    yearly=(yrs/yrs.shift(1).fillna(SEED)-1)*100
    out=dict(risk=risk,margin_cap=margin_cap,final_equity=float(daily[-1]),cagr=st['full'][1],dd=st['full'][2],calmar=st['full'][0],train=st['train'],valid=st['oos'],
             yearly={str(k.year):round(float(v),1) for k,v in yearly.items()},pnl=pnl,entries=n,rejected=rej,shrunk=shrunk,
             margin_avg=float(np.mean(mu)*100),margin_p95=float(np.percentile(mu,95)*100),margin_peak=float(peak_m*100))
    if detail:out['daily']=daily;out['trades']=trades
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True);res={}
    base=replay(detail=True);daily=base.pop('daily');trades=base.pop('trades');res['base']=base
    np.save(OUT/'daily_equity.npy',daily)
    pd.DataFrame(trades,columns=['bot','coin','side','entry_min','exit_min','notional','pnl']).to_csv(OUT/'trades.csv',index=False)
    print('BASE',json.dumps({k:v for k,v in base.items()},default=float),flush=True)
    res['alone']={b:replay(bots=(b,)) for b in ('main','c3','pa')}
    res['cap60']=replay(margin_cap=.6);res['cap100']=replay(margin_cap=1.)
    grid={'main':[.005,.0075,.01,.0125,.015,.02,.025],'c3':[.002,.004,.006,.008,.01,.015],'pa':[.0025,.004,.005,.0075,.01,.015]}
    res['grid']={b:[replay(risk={b:x}) for x in xs] for b,xs in grid.items()}
    res['scale']=[replay(risk={b:DEFAULT[b]*k for b in DEFAULT}) for k in (.5,.75,1.,1.25,1.5,2.,2.5)]
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
    f=lambda r:f"CAGR {r['cagr']:6.1f}% DD {r['dd']:5.1f}% Calmar {r['calmar']:.2f} | train {r['train'][1]:.1f}/{r['train'][2]:.1f} valid {r['valid'][1]:.1f}/{r['valid'][2]:.1f} | margin avg {r['margin_avg']:.0f}% p95 {r['margin_p95']:.0f}% | rej {sum(r['rejected'].values())} shrunk {sum(r['shrunk'].values())}"
    for b,r in res['alone'].items():print('ALONE',NAMES[b],f(r))
    print('CAP60',f(res['cap60']));print('CAP100',f(res['cap100']))
    for b,rows in res['grid'].items():
        for r in rows:print('GRID',NAMES[b],f"{r['risk'][b]*100:.2f}%",f(r))
    for k,r in zip((.5,.75,1.,1.25,1.5,2.,2.5),res['scale']):print('SCALE',k,f(r))
if __name__=='__main__':main()
