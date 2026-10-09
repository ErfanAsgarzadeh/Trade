"""Coded price-action rules for the main bot. Written and committed BEFORE running; one run, no tuning afterwards.

Baseline: main bot as deployed (2A+5A, Donchian10+Kumo 4h, 5 coins) at the new default risk 1.0%.
Flags are computed for EVERY signal bar from closed 4h rows <= ix[sym][b] (causal), side-adjusted ("against" = above for
longs, below for shorts). Pivots: 3-bar fractals, usable only once 3 later bars have closed.
  barb     last 3 bars: any doji (body <= 0.25 range) and every overlap >= 0.65 (same as lbank_bot Barb Wire)
  noh2     no H2/L2 two-legged pullback in the last 8 bars (lbank_bot logic)
  badsb    signal bar fails lbank_bot's quality test (close in the top/bottom 40%, tail or body condition)
  room1    nearest pivot against the trade (last 200 bars) is less than 1 ATR beyond the close
  room2    same, less than 2 ATR (= less room than the initial stop distance)
  double   two pivots against the trade in the last 40 bars within 0.5 ATR of each other, 0..1.5 ATR beyond the close
  climax   a bar in the last 3 has range > 2 ATR and the close is > 3 ATR beyond EMA20 in the trade direction
  wedge    last three pivots in the trade direction rising (falling) with shrinking increments, newest within 30 bars
  tlbreak  trendline through the last two pivots on the trade side (rising lows / falling highs) was closed through after
           the second pivot
  range    high-low of the last 20 bars < 4 ATR
  failbo   in the last 20 bars a close beyond the prior 10-bar extreme in the trade direction was followed within 5 bars
           by a close back inside that level
  htf      prior-day or prior-week high (long) / low (short) is 0..1 ATR beyond the close
PHASE A (TRAIN trades): per flag n, mean net R YES vs NO.
PHASE B: candidate = flag with n_yes >= 30 in TRAIN and |mean R YES - NO| >= 0.15 R. Action: YES worse -> 'skip' and
  'half' (0.5x risk); YES better -> '1.5x'. Simulate each candidate/action on TRAIN; keep the 2 best by TRAIN Calmar that
  beat the baseline TRAIN Calmar. Plus one entry-mechanics variant 'confirm': enter only after a 4h close beyond the signal
  bar's high (long) / low (short) on the next bar (lbank_bot's signal-bar breakout approximated as a close confirmation).
VALIDATION gates (each kept candidate and 'confirm'): V1 valid Calmar >= baseline + 0.10; V2 valid max DD <= baseline;
  V3 valid CAGR >= baseline - 3 pp; V4 for '1.5x' only: valid Calmar above the flat control at the same mean multiplier.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import bench, htf_confirm as hc, conviction_2x as CV
bench.RISK=.01;OUT=bench.OUT/'pa_rules';FLAGS=['barb','noh2','badsb','room1','room2','double','climax','wedge','tlbreak','range','failbo','htf']

def pivots(h,l,k=3):
    n=len(h);ph=np.zeros(n,bool);pl=np.zeros(n,bool)
    for i in range(k,n-k):
        ph[i]=h[i]==h[i-k:i+k+1].max();pl[i]=l[i]==l[i-k:i+k+1].min()
    return ph,pl

def prep(f):
    o,h,l,c=(f[k].to_numpy() for k in ('open','high','low','close'));atr=f.atr.to_numpy();ph,pl=pivots(h,l)
    ts=pd.to_datetime(f.timestamp,unit='ms');d=ts.dt.floor('D');w=ts.dt.to_period('W').dt.start_time
    g=pd.DataFrame(dict(h=h,l=l,d=d,w=w))
    dh=g.groupby('d').h.max();dl=g.groupby('d').l.min();wh=g.groupby('w').h.max();wl=g.groupby('w').l.min()
    pdh=d.map(dh.shift(1)).to_numpy();pdl=d.map(dl.shift(1)).to_numpy();pwh=w.map(wh.shift(1)).to_numpy();pwl=w.map(wl.shift(1)).to_numpy()
    return dict(o=o,h=h,l=l,c=c,atr=atr,ph=ph,pl=pl,ema20=f.ema20.to_numpy(),pdh=pdh,pdl=pdl,pwh=pwh,pwl=pwl)

def flags_at(x,r,side):
    o,h,l,c,a=x['o'],x['h'],x['l'],x['c'],x['atr'][r];F={}
    if r<210 or not a>0:return None
    t=slice(r-2,r+1);rng=np.maximum(h[t]-l[t],1e-12);doji=(np.abs(c[t]-o[t])<=.25*rng).any()
    ov=[max(0.,min(h[i],h[i-1])-max(l[i],l[i-1]))/max(h[i]-l[i],1e-12) for i in range(r-1,r+1)];F['barb']=bool(doji and all(v>=.65 for v in ov))
    found=False
    for k in range(max(1,r-8),r-1):
        leg1=h[k]>h[k-1] if side>0 else l[k]<l[k-1]
        leg2=any((l[m]<l[k] if side>0 else h[m]>h[k]) for m in range(k+1,r+1));found=found or (leg1 and leg2)
    F['noh2']=not found
    body,span=abs(c[r]-o[r]),max(h[r]-l[r],1e-8);lower,upper=min(o[r],c[r])-l[r],h[r]-max(o[r],c[r])
    ok=((c[r]-l[r])/span>=.6 and (lower>=1.2*body or (c[r]>o[r] and body>=.5*span))) if side>0 else ((h[r]-c[r])/span>=.6 and (upper>=1.2*body or (c[r]<o[r] and body>=.5*span)))
    F['badsb']=not ok
    lim=r-3;idx_h=np.where(x['ph'][r-200:lim+1])[0]+r-200;idx_l=np.where(x['pl'][r-200:lim+1])[0]+r-200
    against=h[idx_h] if side>0 else l[idx_l];beyond=side*(against-c[r]);beyond=beyond[beyond>0]
    room=beyond.min()/a if len(beyond) else 99.;F['room1']=room<1;F['room2']=room<2
    rec=(idx_h if side>0 else idx_l);rec=rec[rec>=r-40];lv=(h if side>0 else l)[rec];dbl=False
    for i in range(len(lv)):
        for j in range(i+1,len(lv)):
            m=(lv[i]+lv[j])/2;dist=side*(m-c[r])/a
            if abs(lv[i]-lv[j])<.5*a and 0<=dist<=1.5:dbl=True
    F['double']=dbl
    F['climax']=bool((h[r-2:r+1]-l[r-2:r+1]).max()>2*a and side*(c[r]-x['ema20'][r])/a>3)
    tr=(idx_h if side>0 else idx_l)[-3:];vals=(h if side>0 else l)[tr]
    if len(tr)==3 and tr[-1]>=r-30:d1,d2=side*(vals[1]-vals[0]),side*(vals[2]-vals[1]);F['wedge']=bool(d1>0 and d2>0 and d2<d1)
    else:F['wedge']=False
    sup=(idx_l if side>0 else idx_h)[-2:];F['tlbreak']=False
    if len(sup)==2:
        p0,p1=sup;v0,v1=((l if side>0 else h)[p] for p in sup)
        if side*(v1-v0)>0:
            slope=(v1-v0)/(p1-p0);ii=np.arange(p1+1,r+1);line=v1+slope*(ii-p1);F['tlbreak']=bool((side*(c[ii]-line)<0).any())
    F['range']=bool(h[r-19:r+1].max()-l[r-19:r+1].min()<4*a)
    fb=False
    for i in range(r-20,r-1):
        lvl=(h[i-10:i].max() if side>0 else l[i-10:i].min())
        if side*(c[i]-lvl)>0 and any(side*(c[j]-lvl)<0 for j in range(i+1,min(i+6,r+1))):fb=True;break
    F['failbo']=fb
    lv2=[x['pdh'][r],x['pwh'][r]] if side>0 else [x['pdl'][r],x['pwl'][r]];F['htf']=any(np.isfinite(v) and 0<=side*(v-c[r])/a<=1 for v in lv2)
    return F

def all_flags(ctx,sig):
    X={s:prep(ctx['frames'][s]) for s in bench.SYMBOLS};out={}
    for j,s in enumerate(bench.SYMBOLS):
        for b in np.where(sig[j,:,0]!=0)[0]:
            fl=flags_at(X[s],int(ctx['ix'][s][b]),int(sig[j,b,0]))
            if fl:out[(j,int(b))]=fl
    return out,X

def stats(c):return CV.stats(c)

def confirm_variant(ctx,base,X):
    sig=base['sig'].copy();new=sig.copy();new[:,:,0]=0;new[:,:,3]=-np.inf
    for j,s in enumerate(bench.SYMBOLS):
        x=X[s]
        for b in np.where(sig[j,:,0]!=0)[0]:
            if b+1>=sig.shape[1]:continue
            r=int(ctx['ix'][s][b]);r1=int(ctx['ix'][s][b+1]);side=int(sig[j,b,0])
            if r1!=r+1:continue
            if side*(x['c'][r1]-(x['h'][r] if side>0 else x['l'][r]))>0 and new[j,b+1,0]==0:
                new[j,b+1]=sig[j,b];new[j,b+1,1]=x['c'][r1]
    return dict(base,sig=new)

def main():
    ctx=bench.load();base=hc.build(ctx,None);F=CV.feats(ctx);P=CV.ledger(ctx,base,F);FL,X=all_flags(ctx,base['sig'])
    for k in FLAGS:P[k]=[FL.get((int(r.j),int(r.b)),{}).get(k,False) for r in P.itertuples()]
    tr=P[P.train];va=P[~P.train];res=dict(notes=__doc__,flags={})
    print(f'trades train {len(tr)} valid {len(va)}',flush=True)
    for k in FLAGS:
        g={nm:dict(n_yes=int(d[k].sum()),yes_R=float(d.R[d[k]].mean()) if d[k].any() else None,no_R=float(d.R[~d[k]].mean())) for nm,d in (('train',tr),('valid',va))}
        res['flags'][k]=g;t,v=g['train'],g['valid']
        print(f"{k:8s} TRAIN yes {t['n_yes']:3d} R {t['yes_R'] if t['yes_R'] is not None else float('nan'):+.2f} vs no {t['no_R']:+.2f} | VALID yes {v['n_yes']:3d} R {v['yes_R'] if v['yes_R'] is not None else float('nan'):+.2f} vs no {v['no_R']:+.2f}",flush=True)
    sb=stats(base);res['baseline']=sb;print('baseline (1% risk)',{p:{m:round(v,2) for m,v in x.items()} for p,x in sb.items()},flush=True)
    sims={}
    for k in FLAGS:
        t=res['flags'][k]['train']
        if t['n_yes']<30 or t['yes_R'] is None or abs(t['yes_R']-t['no_R'])<.15:continue
        acts=['skip','half'] if t['yes_R']<t['no_R'] else ['1.5x']
        for act in acts:
            m={'skip':0.,'half':.5,'1.5x':1.5}[act]
            def mf(j,b,side,score,k=k,m=m):return m if FL.get((j,int(b)),{}).get(k,False) else 1.
            c=CV.with_mult(base,mf)
            if act=='skip':
                for (j,b),fl in FL.items():
                    if fl.get(k):c['sig'][j,b,0]=0;c['sig'][j,b,3]=-np.inf
            st=stats(c);sims[f'{k}:{act}']=dict(stats=st,cfg=c,m=m,k=k,act=act)
            print(f"candidate {k}:{act} TRAIN Calmar {st['train']['calmar']:.2f} CAGR {st['train']['cagr']:.1f}% DD {st['train']['dd']:.1f}%",flush=True)
    kept=sorted([n for n in sims if sims[n]['stats']['train']['calmar']>sb['train']['calmar']],key=lambda n:-sims[n]['stats']['train']['calmar'])[:2]
    conf=confirm_variant(ctx,base,X);sims['confirm']=dict(stats=stats(conf),act='confirm');kept.append('confirm')
    res['candidates']={n:dict(stats=s['stats']) for n,s in sims.items()};res['validated']={}
    for n in kept:
        st=sims[n]['stats'];V=dict(V1=st['oos']['calmar']>=sb['oos']['calmar']+.1,V2=st['oos']['dd']<=sb['oos']['dd'],V3=st['oos']['cagr']>=sb['oos']['cagr']-3)
        if sims[n].get('act')=='1.5x':
            k=sims[n]['k'];share=float(np.mean([v.get(k,False) for v in FL.values()]));mm=1+.5*share
            ctrl=stats(CV.with_mult(base,lambda j,b,side,score,mm=mm:mm));V['V4']=st['oos']['calmar']>ctrl['oos']['calmar']
        res['validated'][n]=dict(stats=st,gates=V,passed=all(V.values()))
        print(f"VALIDATE {n}: TRAIN Calmar {st['train']['calmar']:.2f} | VALID Calmar {st['oos']['calmar']:.2f} CAGR {st['oos']['cagr']:.1f}% DD {st['oos']['dd']:.1f}% (baseline {sb['oos']['calmar']:.2f} / {sb['oos']['cagr']:.1f}% / {sb['oos']['dd']:.1f}%) | {V} PASS={all(V.values())}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
