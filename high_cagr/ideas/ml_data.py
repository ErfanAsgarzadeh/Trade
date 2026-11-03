"""Large training set for the in-trade decision models.
1) LEGS. Deployed ledger (five_year_report.ledgers('soft'), the trades the account really takes) + AUGMENTED legs: the same three
   entry/exit engines run on the coins each bot does NOT trade (Shahin 2A+5A on the 30 other coins with no slot limit,
   Mojsavar C3+D on OTHER20, Ghoghnous soft on MAIN5+MAIN10). Augmented legs are used for training only, never in the replay.
2) STATES every 1h close while a leg is open (from the first full hour). Features = 48 criteria + 15 sentiment criteria of
   the last closed 4h bar, fast 1h features (1h/4h return, 1h range/ATR, 1h taker buy share) and the position path
   (unrealised R, MFE, MAE, give-back, hours held), all signed with the side.
3) ACTION VALUES per state, in R after all costs (fee 0.06%/side, 2 bps slippage, funding), relative to exiting now:
   hold    = final net R of the leg - net R of exiting at this close
   tighten = net R if the stop moves to 0.5 R behind this close (first touch on 1-minute bars, else the original exit)
             - net R of exiting now
   exit    = 0 by definition.
"""
import sys,functools,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import five_year_report as FY, three_bots_replay as TB, pabench as PB, xuni as X, c3bench as B3, c3bench_d as BD, c3r2_a4_sizing as S4, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM
OUT=ROOT/'high_cagr/output/ideas/ml';CACHE=ROOT/'high_cagr/cache_sentiment'
FEE=.0006;SLIP=.0002;MIN0=lambda ts:int((ts-rs.START)//60000)
FAST=['ret1h','ret4h','range1h','tbr1h']
DYN=['unreal_R','mfe_R','mae_R','giveback','hours']

def aug_main(symbols):
    legs=[]
    for g in range(0,len(symbols),6):
        sy=symbols[g:g+6];F4={s:X.frame(s) for s in sy}
        case=dict(symbols=sy,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.01,max_open_positions=len(sy))
        fk={(s,'4h','standard'):F4[s] for s in sy};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
        bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
        for j,s in enumerate(sy):
            f=F4[s];ix=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
            ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix];low=~(ar>=1.)&(ss[j,:,0]!=0);ss[j,low,0]=0;ss[j,low,3]=-np.inf
        P=np.stack([np.load(X.PREP/s/'prices.npy') for s in sy]);FU=np.stack([np.load(X.PREP/s/'funding.npy') for s in sy])
        a,t,curve=simulate(P,FU,np.ascontiguousarray(ss),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.01,len(sy),step,True,slip=2e-4,legacy_cap=100.,floor_on=True,floor_trigger=1.,floor_lock=.1)
        for r in t:
            if r[2]<=0:continue
            legs.append(dict(bot='main',coin=sy[int(r[0])],side=int(r[3]),em=MIN0(r[1]),xm=MIN0(r[2]),entry=float(r[4]),unit=float(r[12]/r[5]),
                stop_frac=float(r[7]/r[4]),risk_scale=1.,root=('amain',sy[int(r[0])],int(r[17])),is_add=int(r[18])!=0,aug=True))
        del P,FU
    return legs

def aug_c3(symbols):
    legs=[]
    for s in symbols:
        d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n'])
        T=S4.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
        for i,r in enumerate(T):
            e,x=int(r[0]),int(r[1])
            legs.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,TB.DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                             stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('ac3',s,i),is_add=False,aug=True))
    return legs

def aug_pa(symbols):
    old=PB.OTHER20;PB.OTHER20=list(symbols)
    try:legs=FY.pa_soft_legs()
    finally:PB.OTHER20=old
    for l in legs:l['root']=('apa',)+tuple(l['root'][1:]);l['aug']=True
    return legs

@functools.lru_cache(1)
def all_legs():
    dep=[dict(l,aug=False) for l in FY.ledgers('soft')]
    other30=[s for s in C.COINS if s not in rs.SYMBOLS];mains=list(rs.SYMBOLS)+list(B3.MAIN10)
    aug=aug_main(other30)+aug_c3(list(PB.OTHER20))+aug_pa(mains)
    aug=[l for l in aug if l['xm']>l['em']+60 and np.isfinite(l['unit']) and l['stop_frac']>0]
    print('legs deployed',len(dep),'augmented',len(aug),{b:sum(1 for l in aug if l['bot']==b) for b in ('main','c3','pa')},flush=True)
    return dep+aug

@functools.lru_cache(None)
def taker1h(s):
    f=CACHE/f'taker1h_{s}.npy'
    if f.exists():return np.load(f)
    import zipfile
    n=(rs.END-rs.START)//3600000;tb=np.zeros(n);vv=np.zeros(n)
    for z in SL.kline_files(s):
        with zipfile.ZipFile(z) as zz:d=pd.read_csv(zz.open(zz.namelist()[0]),header=None,usecols=[0,5,9],names=['t','v','tb'],low_memory=False)
        d=d[pd.to_numeric(d.t,errors='coerce').notna()].astype(float)
        if d.t.max()>1e14:d.t/=1000
        b=((d.t.to_numpy()-rs.START)//3600000).astype(np.int64);m=(b>=0)&(b<n);np.add.at(tb,b[m],d.tb.to_numpy()[m]);np.add.at(vv,b[m],d.v.to_numpy()[m])
    out=np.vstack([tb,vv]);np.save(f,out);return out

@njit(cache=True)
def tighten_outcomes(lo,hi,op,cl_at,ms,em,xm,side,entry,sd,fc,fee,slip,unit_final):
    """for each state minute ms[k] (index into the 1m arrays), net unit if the stop is moved to close - side*0.5R."""
    out=np.empty(len(ms))
    for k in range(len(ms)):
        m=ms[k];c=cl_at[k];stop=c-side*.5*sd;res=unit_final
        for i in range(m+1,xm+1):
            if (side==1 and lo[i]<=stop) or (side==-1 and hi[i]>=stop):
                xr=min(op[i],stop) if side==1 else max(op[i],stop);xp=xr*(1-side*slip)
                res=side*(xp-entry)-(entry+xp)*fee-side*entry*(fc[i+1]-fc[em]);break
        out[k]=res
    return out

def leg_states(l):
    s=l['side'];e=l['entry'];sd=e*l['stop_frac'];P=LM.px(l['coin']);fc=LM.fc(l['coin']);em,xm=l['em'],l['xm']
    ms=np.arange((em//60+1)*60+59,xm,60)
    if len(ms)==0:return None
    seg=P[em:xm+1];hi=np.maximum.accumulate(seg[:,1]);lo=np.minimum.accumulate(seg[:,2]);i=ms-em;c=P[ms,3]
    fav=np.where(s>0,hi[i]-e,e-lo[i]);adv=np.where(s>0,e-lo[i],hi[i]-e);rn=s*(c-e)/sd
    xp=c*(1-s*SLIP);exit_now=s*(xp-e)-(e+xp)*FEE-s*e*(fc[ms+1]-fc[em])
    tight=tighten_outcomes(P[:,2],P[:,1],P[:,0],c,ms,em,xm,s,e,sd,fc,FEE,SLIP,l['unit'])
    h=ms//60;tk=taker1h(l['coin']);tb=np.where(tk[1][h]>0,tk[0][h]/np.maximum(tk[1][h],1e-12)-.5,0.)
    b4=(ms+1)//240-1;atr=PB._bars(l['coin'])['atr'][b4]
    c1=P[np.maximum(ms-60,0),3];c4=P[np.maximum(ms-240,0),3];rg=np.array([P[m-59:m+1,1].max()-P[m-59:m+1,2].min() for m in ms])
    D=pd.DataFrame(dict(unreal_R=rn,mfe_R=fav/sd,mae_R=adv/sd,giveback=fav/sd-rn,hours=(ms-em)/60.,ret1h=s*(c/c1-1),ret4h=s*(c/c4-1),range1h=rg/atr,tbr1h=s*tb))
    D['m']=ms;D['b4']=b4;D['v_hold']=(l['unit']-exit_now)/sd;D['v_tight']=(tight-exit_now)/sd
    return D

def build_states(L,step_hours=1):
    parts=[]
    for j,l in enumerate(L):
        D=leg_states(l)
        if D is None:continue
        if step_hours>1:D=D.iloc[::step_hours]
        D['leg']=j;parts.append(D)
        if j%500==0:print('states leg',j,'/',len(L),flush=True)
    S=pd.concat(parts,ignore_index=True)
    # 4h criteria + sentiment for the last closed 4h bar (computed once per leg x bar)
    key=S[['leg','b4']].drop_duplicates();rows=[]
    for leg,b4 in zip(key.leg,key.b4):
        l=L[leg];r=C.at(l['coin'],b4,l['side'],l['stop_frac'],l['bot']);r.update(SL.at(l['coin'],b4,l['side']));r['leg']=leg;r['b4']=b4;rows.append(r)
    F=pd.DataFrame(rows);S=S.merge(F,on=['leg','b4'],how='left')
    return S
FEATS=C.ALL+SL.SENT+FAST+DYN

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True);L=all_legs()
    pd.DataFrame([{k:(str(v) if k=='root' else v) for k,v in l.items()} for l in L]).to_parquet(OUT/'legs.parquet')
    S=build_states(L);S.to_parquet(OUT/'states.parquet');print('states',S.shape,flush=True)
