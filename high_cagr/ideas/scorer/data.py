"""Position scorer data (PREDECLARED.md): deployed + augmented legs with exit components, entry features and 4h in-trade states.

A leg is {bot, coin, side, em, xm, entry, stop_frac, risk_scale, root, is_add, aug, comps}; comps = [(exit minute, fraction of the
size, net P&L per unit of size for that fraction)], so unit = sum(frac x pnl). Mojsavar legs have up to two components
(half at +2R, rest at the profit lock / trail), everything else one. Closing at minute m replaces every later component by a
market exit at the 1m close of m (fee, slippage, funding), which is exact for any earlier-exit action.
"""
from pathlib import Path
import sys,functools,pickle
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import three_bots_replay as TB, xuni as X, holdout_test as H, c3bench_d as BD, c3r2_a4_sizing as SZ
from high_cagr.ideas.winrate import ledger as LG, exits as E, run_rules as RR, universe_eval as U
OUT=ROOT/'high_cagr/output/ideas/scorer';COINS=list(rs.SYMBOLS)+X.NEW+H.H10+H.H2;BM=240
DEP=dict(main=set(rs.SYMBOLS),c3=set(BD.B.MAIN10),pa=set(BD.B.OTHER20))

def c3_orig(s):
    d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n']);out=[]
    T=SZ.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
    for i,r in enumerate(T):
        e,x=int(r[0]),int(r[1])
        out.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,TB.DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                        stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('c3',s,i),is_add=False))
    return out

def c3_comps(l,arm=1.,lock=.1,pfrac=.5,ptarget=2.):
    """Components of a Mojsavar leg under the profit rules; mirrors the corrected exits.modify (asserted in build)."""
    P=LG.coin(l['coin'])['P'];s=l['side'];e=l['entry'];risk=e*l['stop_frac'];em,xm=l['em'],l['xm']
    if xm-em<2:return [(xm,1.,l['unit'])]
    seg=P[em:xm];op,hi,lo=seg[:,0],seg[:,1],seg[:,2];fav=(hi-e) if s==1 else (e-lo);jl=len(seg);xl=0.;comps=[];rest=1.
    armed=np.nonzero(fav>=arm*risk)[0]
    if len(armed) and armed[0]+1<len(seg):
        j0=armed[0]+1;lvl=e+s*lock*risk;cross=np.nonzero((lo[j0:]<=lvl) if s==1 else (hi[j0:]>=lvl))[0]
        if len(cross):jl=j0+cross[0];xl=min(op[jl],lvl) if s==1 else max(op[jl],lvl)
    lvl=e+s*ptarget*risk;hit=np.nonzero((hi[:jl]>=lvl) if s==1 else (lo[:jl]<=lvl))[0]
    if len(hit):
        j=hit[0];xraw=max(op[j],lvl) if s==1 else min(op[j],lvl);comps.append((int(em+j),pfrac,E._net(l,em+j,xraw,1.)));rest=1-pfrac
    comps.append((int(em+jl),rest,E._net(l,em+jl,xl,1.)) if jl<len(seg) else (int(xm),rest,l['unit']))
    return comps

def finish(l,comps,aug):
    return dict(l,comps=comps,unit=float(sum(f*u for _,f,u in comps)),xm=int(max(x for x,_,_ in comps)),aug=aug)

def build_legs(force=False):
    p=OUT/'legs.pkl'
    if p.exists() and not force:return pickle.loads(p.read_bytes())
    OUT.mkdir(parents=True,exist_ok=True);df=LG.build();raw=LG.raw_legs();keep=RR.keep_mask(df,['main_late'],RR.thresholds(df));L=[]
    ref,_=E.modified_legs(raw,**RR.C3EXIT)
    for l,k,r in zip(raw,keep,ref):
        if not k:continue
        c=c3_comps(l) if l['bot']=='c3' else [(l['xm'],1.,l['unit'])];n=finish(l,c,False)
        assert abs(n['unit']-r['unit'])<1e-9*max(1,abs(r['unit'])) and n['xm']==r['xm'],(l['bot'],l['coin'],l['em'])
        L.append(n)
    ndep=len(L)
    for s in COINS:
        if s not in DEP['main']:L+=[finish(l,[(l['xm'],1.,l['unit'])],True) for l in U.shahin_legs(s)]
        if s not in DEP['c3']:L+=[finish(l,c3_comps(l),True) for l in c3_orig(s)]
        if s not in DEP['pa']:L+=[finish(l,[(l['xm'],1.,l['unit'])],True) for l in U.pa_legs(s)]
        print('legs',s,len(L),flush=True)
    for i,l in enumerate(L):l['id']=i;l['root']=str(l['root'])+('|aug' if l['aug'] else '')
    p.write_bytes(pickle.dumps(L));print('deployed',ndep,'augmented',len(L)-ndep);return L

@functools.lru_cache(1)
def momentum_rank():
    """Per day d (known at its close): percentile rank across the 35 coins of the 30-day return."""
    days=TB.DAYS;ends=(np.arange(days)+1)*1440-1;C=pd.DataFrame({s:np.asarray(LG.coin(s)['P'][ends,3]) for s in COINS})
    return C.pct_change(30).rank(axis=1,pct=True)

def mom(coin,side,minute):
    d=minute//1440-1
    if d<30:return .5
    v=momentum_rank()[coin].iat[d];v=.5 if not np.isfinite(v) else float(v);return v if side>0 else 1-v

def market(l,minute):
    """ledger.entry_features evaluated on the last 4h bar closed before `minute` (side-signed), + momentum rank."""
    f=LG.entry_features(dict(l,em=int(minute)))
    if f is None:return None
    f=dict(f);f.pop('side',None);f['mom_rank']=mom(l['coin'],l['side'],minute);return f

def R_of(l):return l['unit']/l['entry']/l['stop_frac']

def entry_table(L,force=False):
    p=OUT/'entry.pkl'
    if p.exists() and not force:return pd.read_pickle(p)
    rows=[]
    for l in L:
        f=market(l,l['em'])
        if f is None:f={}
        rows.append(dict(id=l['id'],bot=l['bot'],coin=l['coin'],side=l['side'],em=l['em'],xm=l['xm'],aug=l['aug'],is_add=l['is_add'],root=l['root'],R=R_of(l),**{'f_'+k:v for k,v in f.items()}))
    df=pd.DataFrame(rows);df.to_pickle(p);return df

def exit_unit(l,m,frac=1.):
    """New (unit, xm) if `frac` of what is still open is closed at the 1m close of minute m."""
    px=float(LG.coin(l['coin'])['P'][m,3]);u=E._net(l,m,px,1.);tot=0.
    for x,f,v in l['comps']:tot+=f*v if x<=m else f*(frac*u+(1-frac)*v)
    return tot

def state_table(L,force=False):
    p=OUT/'states.pkl'
    if p.exists() and not force:return pd.read_pickle(p)
    rows=[]
    for k,l in enumerate(L):
        d=LG.coin(l['coin']);P=d['P'];s=l['side'];e=l['entry'];risk=e*l['stop_frac'];em,xm=l['em'],l['xm']
        b0=(em+BM)//BM+1;b1=xm//BM   # closes at minutes (b*BM-1) with em+BM <= m < xm
        if b1<b0:continue
        hi=np.maximum.accumulate(P[em:xm+1,1]);lo=np.minimum.accumulate(P[em:xm+1,2])
        for b in range(b0,b1+1):
            m=b*BM-1
            if m>=xm or m<em+BM:continue
            rem=sum(f for x,f,_ in l['comps'] if x>m)
            if rem<=0:break
            f=market(l,m+1)
            if f is None:continue
            cl=float(P[m,3]);un=s*(cl-e)/risk;mfe=(hi[m-em]-e)/risk if s==1 else (e-lo[m-em])/risk;mae=(e-lo[m-em])/risk if s==1 else (hi[m-em]-e)/risk
            hold=sum(fr*v for x,fr,v in l['comps'] if x>m);ex=rem*E._net(l,m,cl,1.)
            rows.append(dict(id=l['id'],m=m,unreal=un,mfe=mfe,mae=mae,giveback=mfe-un,bars=(m-em)/BM,rem=rem,v_hold=(hold-ex)/rem/risk,**{'f_'+kk:vv for kk,vv in f.items()}))
        if k%1000==0:print('states',k,len(rows),flush=True)
    df=pd.DataFrame(rows);df.to_pickle(p);return df

if __name__=='__main__':
    L=build_legs('--force' in sys.argv);et=entry_table(L,True);st=state_table(L,True)
    print(et.groupby(['bot','aug']).agg(n=('R','size'),win=('R',lambda x:(x>0).mean()),R=('R','mean')).round(3));print('states',len(st),st.v_hold.describe().round(3).to_dict())
