"""Frozen bench for PA-sleeve upgrades (4h KEYREV, stop entry, 2R target, 30-bar time stop). DO NOT EDIT from an agent.

Baseline = the deployed PA sleeve = pa_bot.py config 4h|KEYREV|TP2|none (reproduced exactly, asserted in baseline()).
Account: TWO = main bot 1.0% + C3+D 0.4% (daily series saved by pa_bot.py); THREE = TWO + PA at 0.15% risk
(PA series is simulated at 0.5% of a fixed 1e4 base and scaled by 0.3).
Periods: TRAIN 2021-10-05..2024-12-31 (decide), VALIDATION 2025-01-01..2026-10-04 (judge only).
Universes: OTHER20 = deploy (no coin shared with the other bots); MAIN5 = main bot coins; MAIN10 = C3 coins;
IN15 = MAIN5 + MAIN10 (generalisation check).

A candidate is fn(d, variant) -> trades array from run(d, ...) (or your own engine returning the same columns):
  [entry_min, exit_min, side, net_frac, R, qty, entry, exit, cost, root_id]  (minute indexes from rs.START, base 1e4)
d = coin(sym): name, P (minutes x OHLC, float64), fc (cumulative funding, len n_min+1), c1 (minute closes), n (4h bars),
  o h l c v (4h OHLC + volume), atr e20 e50 e200 rsi adx (4h, causal), htf (+1/-1/0: last closed daily close vs daily
  EMA50), sig = dict(side, kind, lev, stp, val) = baseline KEYREV signals per 4h bar (signal on bar t, orders from bar t+1),
  btc = dict(c, e50, e200, atr) on the same 4h grid.
Entry filters must only use bar data <= t for a signal on bar t (check_causal() reruns on truncated data).

run(d, side=None, mult=None, **kw) keywords (defaults = baseline):
  target_r=2.0 (0 = no target) | hold=30 (time stop at the close of the hold-th bar after the entry bar; 0 = off)
  partial_frac=0, partial_r=1.0 (close this fraction when the price reaches partial_r R, rest continues)
  be_r=0 (stop to entry + costs once the max favourable excursion reaches be_r R; 0 = off)
  trail_after_r=0, trail_atr=3.0 (after the best 4h close is >= trail_after_r R: chandelier best close - trail_atr ATR,
     on 4h closes; 0 = off) | early_bars=0, early_r=0.0 (exit at the close of bar early_bars after entry if the best
     close so far is < early_r R; 0 = off) | valid=None (override stop-order validity in bars)
  side: int8 array to replace sig['side'] (0 = drop a signal); mult: float array per bar = risk multiplier.
GATES (pre-declared, vs the baseline, all at 0.15% PA risk):
  P1 THREE train Calmar >= baseline + 0.10
  P2 THREE validation Calmar >= baseline
  P3 THREE full max DD <= baseline + 1.0 pp
  P4 PA alone on IN15 full Calmar >= baseline IN15 full Calmar (the idea generalises to coins it was not tuned on)
  P5 causal
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import pa_bot as PB, xuni as X, ltf_search as L, c3bench as B
OUT=X.OUT/'pa_opt';CACHE=ROOT/'high_cagr/prepared_pa';SPLIT=X.SPLIT
OTHER20=list(PB.OTHER20);MAIN5=list(rs.SYMBOLS);MAIN10=list(B.MAIN10);IN15=MAIN5+MAIN10;ALL35=OTHER20+IN15
FEE,SLIP,RISK,CAP,MINSTOP=PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP;PA_SCALE=.0015/RISK

def _px(s):
    CACHE.mkdir(parents=True,exist_ok=True);f=CACHE/f'{s}_px.npy'
    if not f.exists():p,_=PB.load_coin(s);np.save(f,np.ascontiguousarray(p))
    return np.load(f,mmap_mode='r').view(np.ndarray)

@functools.lru_cache(None)
def _bars(s):
    f=CACHE/f'{s}_bars.npz'
    if f.exists():return dict(np.load(f))
    p=_px(s);_,fc=PB.load_coin(s);o,h,l,c=L.bars(p,240);n=len(c);a=PB.atr14(h,l,c);_,_,adx=L.signals(o,h,l,c)
    fr=X.frame(s,PB.prep_dir(s));ts=rs.START+np.arange(n)*240*60000;ix=np.searchsorted(fr.timestamp.to_numpy(np.int64),ts)
    v=np.where(ix<len(fr),fr.volume.to_numpy()[np.minimum(ix,len(fr)-1)],0.);v[fr.timestamp.to_numpy(np.int64)[np.minimum(ix,len(fr)-1)]!=ts]=0.
    g=PB.signals(p,240,'KEYREV')
    out=dict(o=o,h=h,l=l,c=c,v=v,atr=a,e20=PB.ema(c,20),e50=PB.ema(c,50),e200=PB.ema(c,200),rsi=L.rsi(c,14),adx=adx,htf=PB.htf_side(p,240),fc=fc,
             s_side=g['side'],s_kind=g['kind'],s_lev=g['lev'],s_stp=g['stp'],s_val=g['val'])
    np.savez(f,**out);return out

def coin(s):
    b=_bars(s);P=_px(s);bt=_bars('BTCUSDT')
    return dict(name=s,P=P,fc=b['fc'],c1=P[:,3],n=len(b['c']),**{k:b[k] for k in ('o','h','l','c','v','atr','e20','e50','e200','rsi','adx','htf')},
                sig=dict(side=b['s_side'],kind=b['s_kind'],lev=b['s_lev'],stp=b['s_stp'],val=b['s_val']),btc=dict(c=bt['c'],e50=bt['e50'],e200=bt['e200'],atr=bt['atr']))

@njit(cache=True)
def engine2(P,fcum,bm,side,kind,lev,stp,val,atr,mult,target_r,hold,pfrac,pr,be_r,tra,tatr,eb_n,eb_r,fee,slip,risk,cap,minstop,warm):
    nb=len(side);nm=P.shape[0];out=np.zeros((2*nb,10));k=0;free=0;root=0
    for t in range(warm,nb-1):
        s=side[t]
        if s==0 or mult[t]<=0:continue
        m0=(t+1)*bm
        if m0<free or m0>=nm:continue
        em=-1;raw=0.
        if kind[t]==2:em=m0;raw=P[m0,0]
        else:
            lv=lev[t];mend=min((t+1+val[t])*bm,nm)
            for m in range(m0,mend):
                if (s==1 and P[m,2]<=stp[t]) or (s==-1 and P[m,1]>=stp[t]):
                    if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):break
                if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        if em<0:continue
        entry=raw*(1+s*slip);stop=stp[t];dist=s*(entry-stop)
        if not dist/entry>=minstop:continue
        qty=min(risk*mult[t]*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        tp=entry+s*target_r*dist if target_r>0 else 0.
        ptp=entry+s*pr*dist;pq=qty*pfrac if pfrac>0 else 0.;pdone=pfrac<=0
        be=entry*(1+s*(2*fee+2*slip));best=-1e300 if s==1 else 1e300;armed=False;mfe=0.
        x=-1;xraw=0.;ebar=em//bm;rem=qty
        for m in range(em,nm):
            hi=P[m,1];lo=P[m,2];op=P[m,0] if m>em else raw
            if s==1:
                if lo<=stop:xraw=min(op,stop);x=m;break
            else:
                if hi>=stop:xraw=max(op,stop);x=m;break
            if not pdone and ((s==1 and hi>=ptp) or (s==-1 and lo<=ptp)):
                pxr=max(op,ptp) if s==1 else min(op,ptp);xp=pxr*(1-s*slip);fund=-s*raw*pq*(fcum[m+1]-fcum[em])
                net=s*(xp-entry)*pq-(entry+xp)*pq*fee+fund
                out[k,0]=em;out[k,1]=m;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(pxr-raw)/dist;out[k,5]=pq;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*pq*fee-fund;out[k,9]=root;k+=1
                rem=qty-pq;pdone=True
            if target_r>0:
                if (s==1 and hi>=tp) or (s==-1 and lo<=tp):xraw=max(op,tp) if s==1 else min(op,tp);x=m;break
            fav=(hi-entry)/dist if s==1 else (entry-lo)/dist
            if fav>mfe:mfe=fav
            if be_r>0 and mfe>=be_r and s*(be-stop)>0:stop=be
            if (m+1)%bm==0:
                b=m//bm;cl=P[m,3]
                if hold>0 and b-ebar>=hold:xraw=cl;x=m;break
                best=max(best,cl) if s==1 else min(best,cl)
                if eb_n>0 and b-ebar==eb_n and s*(best-entry)<eb_r*dist:xraw=cl;x=m;break
                if tra>0:
                    if s*(best-entry)>=tra*dist:armed=True
                    if armed:
                        ns=best-s*tatr*atr[b]
                        if s*(ns-stop)>0:stop=ns
        if x<0:x=nm-1;xraw=P[nm-1,3]
        xp=xraw*(1-s*slip);fund=-s*raw*rem*(fcum[x+1]-fcum[em])
        net=s*(xp-entry)*rem-(entry+xp)*rem*fee+fund
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=rem;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*rem*fee-fund;out[k,9]=root;k+=1
        root+=1;free=x+1
    return out[:k]

def run(d,side=None,mult=None,target_r=2.,hold=30,partial_frac=0.,partial_r=1.,be_r=0.,trail_after_r=0.,trail_atr=3.,early_bars=0,early_r=0.,valid=None,risk=RISK):
    g=d['sig'];sd=g['side'] if side is None else np.asarray(side,np.int8);n=len(sd)
    mu=np.ones(n) if mult is None else np.asarray(mult,np.float64);vl=g['val'][:n] if valid is None else np.full(n,int(valid),np.int64)
    return engine2(d['P'],d['fc'],240,sd,g['kind'][:n],g['lev'][:n],g['stp'][:n],vl,d['atr'][:n],mu,float(target_r),int(hold),float(partial_frac),float(partial_r),
                   float(be_r),float(trail_after_r),float(trail_atr),int(early_bars),float(early_r),FEE,SLIP,risk,CAP,MINSTOP,250)

def base_fn(d,variant=None):return run(d)

@functools.lru_cache(1)
def days():return len(_px(OTHER20[0]))//1440
@functools.lru_cache(1)
def two():
    z=np.load(PB.OUT/'series.npz');return z['bot'],z['c3']

def series(fn,variant,coins):
    r=np.zeros(days());T=[]
    for s in coins:
        d=coin(s);t=np.asarray(fn(d,variant),float);T.append(t)
        if len(t):r+=PB.m2m(np.ascontiguousarray(t[:,:9]),d['c1'],days())
    return r,T

def tstats(T):
    t=np.concatenate([x for x in T if len(x)]) if any(len(x) for x in T) else np.zeros((0,10))
    if not len(t):return dict(roots=0,win=0.,mean_R_net=0.)
    sm=X.SPLIT*1440;roots=len({(i,int(r)) for i,x in enumerate(T) for r in (x[:,9] if len(x) else [])})
    return dict(roots=int(roots),legs=int(len(t)),train_legs=int((t[:,0]<sm).sum()),win_legs=float((t[:,3]>0).mean()*100),net_per_leg_bp=float(t[:,3].mean()*1e4))

def evaluate(fn,variant=None,generalise=True):
    bot,c3=two();tw=bot+c3;o,To=series(fn,variant,OTHER20);res=dict(pa=X.stats(o),three=X.stats(tw+o*PA_SCALE),trades=tstats(To),
        corr_two=float(np.corrcoef(o,tw)[0,1]) if o.std()>0 else 0.,yearly=pd.Series(o*PA_SCALE*100,index=pd.date_range('2021-10-05',periods=days())).groupby(lambda x:x.year).sum().round(2).to_dict())
    if generalise:g,_=series(fn,variant,IN15);res['in15']=X.stats(g)
    res['_series']=o;return res

@functools.lru_cache(1)
def baseline():
    r=evaluate(base_fn);z=np.load(PB.OUT/'series.npz')
    assert np.allclose(r['_series'],z['4h|KEYREV|TP2|none']),'bench does not reproduce pa_bot KEYREV TP2'
    r.pop('_series');return r

def verdict(r):
    b=baseline();ck=dict(P1=r['three']['train'][0]>=b['three']['train'][0]+.10,P2=r['three']['oos'][0]>=b['three']['oos'][0],
        P3=r['three']['full'][2]<=b['three']['full'][2]+1.,P4=r['in15']['full'][0]>=b['in15']['full'][0])
    return dict(checks={k:bool(v) for k,v in ck.items()},passed=bool(all(ck.values())))

def check_causal(fn,variant,coins=('LINKUSDT','CRVUSDT'),cuts=(.45,.75)):
    """Trades that are closed before the cut must be identical when the future (bars and minutes) is removed."""
    for s in coins:
        d=coin(s);full=np.asarray(fn(d,variant),float)
        for q in cuts:
            k=int(d['n']*q);km=k*240;dt=dict(d)
            for key in ('o','h','l','c','v','atr','e20','e50','e200','rsi','adx','htf'):dt[key]=d[key][:k]
            dt['sig']={key:v[:k] for key,v in d['sig'].items()};dt['btc']={key:v[:k] for key,v in d['btc'].items()}
            dt['P']=d['P'][:km];dt['c1']=d['c1'][:km];dt['fc']=d['fc'][:km+1];dt['n']=k
            part=np.asarray(fn(dt,variant),float)
            a=full[full[:,1]<km-1] if len(full) else full;b_=part[part[:,1]<km-1] if len(part) else part
            if a.shape!=b_.shape or (len(a) and not np.allclose(a,b_)):return dict(causal=False,coin=s,cut=q)
    return dict(causal=True)

def fmt(r):
    p,t,g=r['pa'],r['three'],r.get('in15')
    return (f"PA train {p['train'][0]:.2f} valid {p['oos'][0]:.2f} full CAGR {p['full'][1]:.1f}% DD {p['full'][2]:.1f}% | THREE train {t['train'][0]:.2f} "
            f"valid {t['oos'][0]:.2f} full {t['full'][0]:.2f} (CAGR {t['full'][1]:.1f}% DD {t['full'][2]:.1f}%)"+(f" | IN15 {g['full'][0]:.2f}" if g else '')+f" | roots {r['trades']['roots']}")

def run_idea(name,variants,fn,notes=''):
    """Evaluate every declared variant (dict name -> variant), gate it, write output/ideas/pa_opt/<name>.json."""
    b=baseline();out=dict(name=name,notes=notes,baseline=b,variants={})
    for v,var in variants.items():
        r=evaluate(fn,var);r.pop('_series');cz=check_causal(fn,var);vd=verdict(r)
        out['variants'][v]=dict(variant=var,**r,causal=cz,verdict=vd,passed=bool(vd['passed'] and cz['causal']))
        print(f"{name}/{v}: {fmt(r)} | causal={cz['causal']} PASS={out['variants'][v]['passed']} fail={[k for k,x in vd['checks'].items() if not x]}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{name}.json').write_text(json.dumps(out,indent=1,default=float));return out

if __name__=='__main__':
    b=baseline();print('BASELINE',fmt(b),'| yearly PA@0.15%',b['yearly'],'| corr TWO',round(b['corr_two'],3))
