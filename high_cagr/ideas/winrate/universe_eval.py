"""Each of the three bots, as shipped after the win-rate study, on every TheTrueTrade futures coin with enough history.

Shahin  = 2A+5A (xuni.bot_daily logic, 1% risk) + late-entry gate (threshold frozen in rules.json), one coin at a time.
Mojsavar= C3+D legs (three_bots_replay) + profit lock 1R->+0.1R and half at 2R (exits.modify).
Ghoghnous = C_exhaustion_soft x1.5 legs (five_year_report.pa_soft_legs logic).
Every leg is a dict in the three_bots_replay format, so any coin list can be replayed on the shared account.
Trades opening before listing + WARMUP_DAYS are dropped (padded pre-listing data). Cached per bot in legs_<bot>.pkl.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import xuni as X, three_bots_replay as TB, five_year_report as FY, pabench as PB, pa2_confluence as CF, pabench2 as Q, pa2_exits as EX
from high_cagr.ideas import c3bench_d as BD, c3r2_a4_sizing as SZ
from high_cagr.ideas.winrate import ledger as LG, exits as E, prepare_ttt as PT
OUT=LG.OUT/'universe'
LATE=json.loads((LG.OUT/'rules.json').read_text())['thresholds']['main_late']
C3EXIT=dict(bots=('c3',),pfrac=.5,ptarget=2.,arm=1.,lock=.1)
MIN0=lambda ts:int((ts-rs.START)//60000)

def coins():return PT.universe()[0]

def shahin_legs(s):
    f=X.frame(s);prices=np.load(X.PREP/s/'prices.npy')[None];fu=np.load(X.PREP/s/'funding.npy')[None]
    case=dict(symbols=[s],entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.01,max_open_positions=4)
    fk={(s,'4h','standard'):f};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    ix=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
    ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix];low=~(ar>=1.)&(ss[0,:,0]!=0);ss[0,low,0]=0;ss[0,low,3]=-np.inf
    c=f.close.to_numpy();r60=np.log(c/np.roll(c,60));r60[:60]=np.nan;late=(ss[0,:,0]*r60[ix]>LATE)&(ss[0,:,0]!=0);ss[0,late,0]=0;ss[0,late,3]=-np.inf
    a,t,curve=simulate(prices,fu,np.ascontiguousarray(ss),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.01,4,step,True,slip=2e-4,
                       floor_on=True,floor_trigger=1.,floor_lock=.1,legacy_cap=100.)
    out=[]
    for r in t:
        if r[2]<=0:continue
        out.append(dict(bot='main',coin=s,side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),stop_frac=float(r[7]/r[4]),
                        risk_scale=float(r[15]/r[14])/.01 if r[14] else 1.,root=('main',s,int(r[17])),is_add=int(r[18])!=0))
    return out

def c3_legs(s):
    d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n'])
    T=SZ.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300);out=[]
    for i,r in enumerate(T):
        e,x=int(r[0]),int(r[1])
        out.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,TB.DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                        stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('c3',s,i),is_add=False))
    return E.modified_legs(out,**C3EXIT)[0]

def pa_legs(s):
    d=PB.coin(s);side=Q.c1_side(d);n=len(side);g=d['sig'];vr,sl,_,_=CF.feats(d,side)
    with np.errstate(invalid='ignore'):gate=(vr<.354)&(sl<.146)&(side!=0)
    w=np.nan_to_num(np.where(gate,(.75+.25*np.clip((.554-vr)/.4,0,1))/FY.NORM,0.))
    def run(mlt):
        return EX.engine_x(d['P'],d['fc'],240,side,g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],mlt,np.full(n,30,np.int64),
                           0.,1.,0.,3.,0.,0,0.,np.zeros(0),np.zeros(0),side.astype(np.int8),PB.FEE,PB.SLIP,PB.RISK,100.,PB.MINSTOP,250)
    A=run(gate.astype(float));B=run(w);out=[]
    for i,(r,rb) in enumerate(zip(A,B)):
        dist=PB.RISK*1e4/r[5]-r[6]*(2*PB.FEE+2*PB.SLIP)
        out.append(dict(bot='pa',coin=s,side=int(r[2]),em=int(r[0]),xm=int(r[1]),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                        stop_frac=float(dist/r[6]),risk_scale=float(FY.VOLMULT*rb[5]/r[5]),root=('pa',s,i),is_add=False))
    return out

BUILD=dict(main=shahin_legs,c3=c3_legs,pa=pa_legs)

def legs(bot,force=False):
    OUT.mkdir(parents=True,exist_ok=True);p=OUT/f'legs_{bot}.pkl'
    cache=pd.read_pickle(p) if p.exists() and not force else {}
    for s in coins():
        if s in cache:continue
        try:L=BUILD[bot](s)
        except Exception as exc:print('FAILED',bot,s,repr(exc),flush=True);continue
        start=PT.listed_min(s)+PT.WARMUP_DAYS*1440;cache[s]=[l for l in L if l['em']>=start]
        pd.to_pickle(cache,p);print(bot,s,len(cache[s]),'legs',flush=True)
    return cache

def coin_stats(L,listed):
    """Per-coin metrics in R (size-independent): all, train (< 2025) and validation (>= 2025)."""
    def st(x):
        if not x:return dict(n=0,win=np.nan,meanR=np.nan,pf=np.nan,sumR=0.)
        R=np.array([l['unit']/l['entry']/l['stop_frac'] for l in x]);g=R[R>0].sum();b=-R[R<0].sum()
        return dict(n=len(R),win=float((R>0).mean()*100),meanR=float(R.mean()),pf=float(g/b) if b>0 else np.inf,sumR=float(R.sum()))
    tr=[l for l in L if l['em']<LG.SPLIT_MIN];va=[l for l in L if l['em']>=LG.SPLIT_MIN]
    years=(TB.DAYS*1440-max(listed+PT.WARMUP_DAYS*1440,0))/525960
    return dict(all=st(L),train=st(tr),valid=st(va),years=float(years),R_per_year=float(st(L)['sumR']/years) if years>0 else np.nan)

def table():
    rows=[]
    for bot in ('main','c3','pa'):
        C=legs(bot)
        for s,L in C.items():
            cs=coin_stats(L,PT.listed_min(s));rows.append(dict(bot=bot,coin=s,years=cs['years'],R_year=cs['R_per_year'],
                **{f'{p}_{k}':cs[p][k] for p in ('all','train','valid') for k in ('n','win','meanR','pf','sumR')}))
    df=pd.DataFrame(rows);df.to_csv(OUT/'per_coin.csv',index=False);return df

if __name__=='__main__':
    df=table();pd.set_option('display.width',250);pd.set_option('display.max_rows',200)
    for b,g in df.groupby('bot'):print('==',b);print(g.sort_values('all_meanR',ascending=False)[['coin','years','all_n','all_win','all_meanR','all_pf','train_n','train_meanR','valid_n','valid_meanR','R_year']].round(2).to_string(index=False))
