"""Which main-bot trades deserve 2x risk? Written and committed BEFORE running; one run, no tuning afterwards.

Baseline = bot 2A+5A (htf_confirm.build, 5 coins, 0.75% risk). Ledger of root trades; features at the SIGNAL bar
(closed 4h frame row ix[sym][b], causal), side-adjusted so that "higher = more with the trade":
  adx      ADX14
  ema_gap  side*(EMA50-EMA200)/ATR
  kumo     side*(close - Kumo edge in trade direction)/ATR
  brk      breakout rank score (sig col 3)
  atr_rel  ATR / median ATR of the prior 60 bars
  htf      side*(close/EMA300 - 1)*100  (~50-day trend on 4h bars)
  btc      side*(BTC close/BTC EMA300 - 1)*100  (market trend)
  rsi      side-adjusted RSI14 (100-RSI for shorts)
PHASE A (TRAIN trades only, entry < 2025-01-01): terciles of each feature -> n, win %, mean net R.
PHASE B rule choice (TRAIN only): for each feature, candidate rule = "top tercile" (thresholds from TRAIN). Simulate 2x
  risk (sig col 4 = 2) on signals meeting it; pick the ONE feature with the highest TRAIN Calmar among those whose top
  tercile mean R >= 1.5 x the overall TRAIN mean R.
GATES on VALIDATION (2025-01-01..2026-10-04) for the picked rule, all must hold:
  V1 valid Calmar >= baseline valid Calmar
  V2 valid CAGR >= baseline + 3 pp
  V3 valid max DD <= baseline + 3 pp
  V4 beats the leverage control: flat risk multiplier = realised mean multiplier of the rule, on ALL trades, valid Calmar
  V5 causal (features from rows <= ix; checked by bench.check_causal-style truncation)
Also reported for every feature: VALID mean R by TRAIN terciles (does the ordering hold out of sample?).
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import bench, htf_confirm as hc, ltf_search as L
OUT=bench.OUT/'conviction_2x';SPLIT=rs.SPLIT;BAR=240*60000

def feats(ctx):
    F={}
    btc=ctx['frames']['BTCUSDT'];btc_t=L.ema(btc.close.to_numpy(),300)
    for s in bench.SYMBOLS:
        f=ctx['frames'][s];o,h,l,c=(f[k].to_numpy() for k in ('open','high','low','close'));atr=f.atr.to_numpy()
        _,_,adx=L.signals(o,h,l,c);e200=L.ema(c,200);e300=L.ema(c,300)
        med=pd.Series(atr).rolling(60).median().shift(1).to_numpy()
        bts=btc.timestamp.to_numpy();bi=np.searchsorted(bts,f.timestamp.to_numpy(),side='right')-1
        F[s]=dict(adx=adx,gap=(f.ema50.to_numpy()-e200)/atr,kt=f.kumo_top.to_numpy(),kb=f.kumo_bottom.to_numpy(),c=c,atr=atr,atr_rel=atr/med,
                  htf=(c/e300-1)*100,btc=(btc.close.to_numpy()[bi]/btc_t[bi]-1)*100,rsi=f.rsi.to_numpy())
    return F

def row_features(F,s,r,side,score):
    x=F[s]
    return dict(adx=x['adx'][r],ema_gap=side*x['gap'][r],kumo=side*(x['c'][r]-(x['kt'][r] if side>0 else x['kb'][r]))/x['atr'][r],brk=score,
                atr_rel=x['atr_rel'][r],htf=side*x['htf'][r],btc=side*x['btc'][r],rsi=x['rsi'][r] if side>0 else 100-x['rsi'][r])

def ledger(ctx,base,F):
    (a,t,cv),_,_=bench._sim(base,'full',2);sig=base['sig'];rows=[]
    for r_ in t[t[:,18]==0]:
        j=int(r_[0]);s=bench.SYMBOLS[j];b=int((r_[1]-rs.START)//BAR);side=int(r_[3])
        while b>0 and sig[j,b,0]==0:b-=1          # signal bar at or before the fill
        legs=t[t[:,17]==r_[17]];R=legs[:,12].sum()/max(r_[15],1e-9)
        rows.append(dict(sym=s,j=j,b=b,side=side,entry=r_[1],R=R,train=r_[1]<SPLIT,**row_features(F,s,ctx['ix'][s][b],side,sig[j,b,3])))
    return pd.DataFrame(rows)

def with_mult(base,mask_fn):
    sig=base['sig'].copy()
    if sig.shape[2]<5:sig=np.concatenate([sig,np.ones(sig.shape[:2]+(1,))],axis=2)
    for j in range(sig.shape[0]):
        on=np.where(sig[j,:,0]!=0)[0]
        for b in on:sig[j,b,4]*=mask_fn(j,b,int(sig[j,b,0]),sig[j,b,3])
    return dict(base,sig=sig)

def stats(c):
    out={}
    for p in ('train','oos','full'):
        (a,t,cv),_,_=bench._sim(c,p,2);eq=cv[np.isfinite(cv).all(1)][:,1];yrs=len(eq)/(365*24) if len(eq) else 1
        dd=float(((np.maximum.accumulate(eq)-eq)/np.maximum.accumulate(eq)).max()*100);cagr=float(((eq[-1]/eq[0])**(1/max(yrs,1e-9))-1)*100)
        out[p]=dict(cagr=cagr,dd=dd,calmar=cagr/dd if dd else 0.)
    return out

def main():
    ctx=bench.load();base=hc.build(ctx,None);F=feats(ctx);P=ledger(ctx,base,F);OUT.mkdir(parents=True,exist_ok=True)
    keys=['adx','ema_gap','kumo','brk','atr_rel','htf','btc','rsi'];tr=P[P.train];va=P[~P.train];allR=tr.R.mean()
    print(f'trades train {len(tr)} valid {len(va)} | train mean R {allR:.3f} win {np.mean(tr.R>0)*100:.0f}%',flush=True)
    res=dict(notes=__doc__,features={},rules={})
    for k in keys:
        q1,q2=np.nanquantile(tr[k],[1/3,2/3]);band=lambda x:np.where(x<=q1,'low',np.where(x<=q2,'mid','high'))
        g={}
        for nm,d in (('train',tr),('valid',va)):
            bb=band(d[k].to_numpy());g[nm]={z:dict(n=int((bb==z).sum()),win=float(np.mean(d.R[bb==z]>0)*100),meanR=float(d.R[bb==z].mean())) for z in ('low','mid','high')}
        res['features'][k]=dict(q1=q1,q2=q2,**g)
        print(f"{k:8s} thresholds {q1:8.3f} {q2:8.3f} | TRAIN meanR low/mid/high {g['train']['low']['meanR']:+.2f} {g['train']['mid']['meanR']:+.2f} {g['train']['high']['meanR']:+.2f} win high {g['train']['high']['win']:.0f}% | VALID {g['valid']['low']['meanR']:+.2f} {g['valid']['mid']['meanR']:+.2f} {g['valid']['high']['meanR']:+.2f}",flush=True)
    sb=stats(base);res['baseline']=sb;print('baseline',{p:{m:round(v,2) for m,v in x.items()} for p,x in sb.items()},flush=True)
    cands={}
    for k in keys:
        f=res['features'][k]
        if not f['train']['high']['meanR']>=1.5*allR:continue
        q2=f['q2']
        def m(j,b,side,score,k=k,q2=q2):
            s=bench.SYMBOLS[j];v=row_features(F,s,ctx['ix'][s][b],side,score)[k];return 2. if v>q2 else 1.
        c=with_mult(base,m);st=stats(c);share=float(np.mean([m(int(r.j),int(r.b),int(r.side),base['sig'][int(r.j),int(r.b),3])==2. for r in tr.itertuples()]))
        cands[k]=dict(stats=st,share_2x=share,mult=1+share);print(f"rule {k}>q2: TRAIN Calmar {st['train']['calmar']:.2f} CAGR {st['train']['cagr']:.1f}% DD {st['train']['dd']:.1f}% | share 2x {share*100:.0f}%",flush=True)
    res['rules']=cands
    if not cands:print('no feature passes the train lift filter -> nothing to adopt');(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));return
    pick=max(cands,key=lambda k:cands[k]['stats']['train']['calmar']);c=cands[pick];st=c['stats']
    ctrl=stats(with_mult(base,lambda j,b,side,score,m=c['mult']:m))
    V=dict(V1=st['oos']['calmar']>=sb['oos']['calmar'],V2=st['oos']['cagr']>=sb['oos']['cagr']+3,V3=st['oos']['dd']<=sb['oos']['dd']+3,V4=st['oos']['calmar']>ctrl['oos']['calmar'])
    res.update(pick=pick,control=ctrl,gates=V,passed=all(V.values()))
    print(f"PICK {pick}: VALID Calmar {st['oos']['calmar']:.2f} CAGR {st['oos']['cagr']:.1f}% DD {st['oos']['dd']:.1f}% | baseline {sb['oos']['calmar']:.2f} {sb['oos']['cagr']:.1f}% {sb['oos']['dd']:.1f}% | control x{c['mult']:.2f}: {ctrl['oos']['calmar']:.2f} {ctrl['oos']['cagr']:.1f}% {ctrl['oos']['dd']:.1f}% | gates {V} PASS={all(V.values())}",flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
