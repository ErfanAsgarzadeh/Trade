"""Bot 4: confirmation entry (F2) + broader training set. Pre-declared before running.
Traded: PB candidates with confirmation (the next 4h bar closes beyond the signal close in the trade direction; entry one bar
later), top 30% of training scores, risk 0.5% alone / x0.3 next to the three bots. Model: gradient boosting (as bot 4) on
technical + sentiment features + rule id; target trade >= 2 R; percentiles from the TRAINING scores of the traded rule.
  G0  train on PB-confirmed only                                      (= F2 of bot4_failures)
  G1  train on PB-confirmed + BRK-confirmed (20-bar breakout)
  G2  train on PB-confirmed + BRK-confirmed + PB-unconfirmed
Folds 2023 / 2024 (dev), 2025-26 reported for comparison (not independent). Reference rows: the current bot 4 (h4_ai_bot).
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bot4_failures as BF, h4_ai_bot as H4, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, criteria_lib as C, live_monitor_study as LM, pabench as PB
OUT=ROOT/'high_cagr/output/ideas/bot4_f2'

def brk_candidates(confirm):
    legs=[]
    for s in C.COINS:
        B=PB._bars(s);o,h,l,c,a=B['o'],B['h'],B['l'],B['c'],B['atr']
        hi=pd.Series(h).shift(1).rolling(20).max().to_numpy();lo=pd.Series(l).shift(1).rolling(20).min().to_numpy()
        sig=np.where(c>hi,1,np.where(c<lo,-1,0)).astype(np.int64);T=BF.engine2(o,h,l,c,a,sig,.004,60,confirm,0.);fc=LM.fc(s);nm=len(fc)-2
        for i,r in enumerate(T):
            t,x,sd,e,xp,sf,t0=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5],int(r[6]);em=(t0+1)*240;xm=min(x*240+239,nm)
            unit=sd*(xp-e)-(e+xp)*BF.FEE-sd*e*(fc[xm+1]-fc[em]);lvl=hi[t] if sd>0 else lo[t]
            legs.append(dict(bot='h4',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('h4b',s,i,confirm),is_add=False,t=t,rule=0,
                             q=float(sd*(c[t]-lvl)/a[t]),atrc=float(a[t]/c[t])))
    return legs

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time()
    pbc=BF.candidates(True,0.);pbu=BF.candidates(False,0.);brc=brk_candidates(True)
    for l in pbu:l['rule']=2   # unconfirmed PB marked as its own rule id
    pools={'G0':pbc,'G1':pbc+brc,'G2':pbc+brc+pbu};X={k:H4.features(v) for k,v in pools.items()};print('built',round(time.time()-t0),'s',{k:len(v) for k,v in pools.items()},flush=True)
    dep=FY.ledgers('soft');res={}
    ref=json.loads((ROOT/'high_cagr/output/ideas/h4_ai_bot/result_dev2.json').read_text());reff=json.loads((ROOT/'high_cagr/output/ideas/h4_ai_bot/result_final.json').read_text())
    for fn,(a,b) in WF.FOLDS.items():
        bots=WF.replay(dep,a,b);out={'bots':bots};rv=(ref.get(fn) or reff.get(fn))['PB|gbm|top30|0.3']['alone']
        print(f'fold {fn}{" (comparison only)" if fn=="2025-26" else ""}: three bots {bots["final"]:,.0f} / {bots["dd"]:.1f} / {bots["calmar"]:.2f} | current bot 4 alone {rv["final"]:,.0f} CAGR {rv["cagr"]:.1f}% DD {rv["dd"]:.1f}%',flush=True)
        for g,L in pools.items():
            R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>=2).astype(int);em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);rule=np.array([l['rule'] for l in L])
            tr=xm<a;A=X[g].fillna(X[g][tr].median()).to_numpy();p=BF.gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];trade=(rule==1)
            pc=BF.pct_of(p[tr&trade],p);idx=np.where((em>=a)&((em<b) if b else True)&trade&(pc>=.7))[0];legs=[L[i] for i in idx]
            r=W.run_period(legs,[1.]*len(legs),a,b);d=r.pop('daily');mo=BF.monthly(d,a//1440);both=WF.replay(dep+[dict(x,risk_scale=.3) for x in legs],a,b)
            out[g]=dict(alone=r,with_bots=both,monthly=mo.round(2).tolist(),pos=float((mo>0).mean()*100),mean=float(mo.mean()),worst=float(mo.min()),n_train=int(tr.sum()))
            print(f'  {g}: train {tr.sum():5d} | alone {r["final"]:>8,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% trades {r["trades"]:4d} win {r["win"]:4.1f}% | months+ {(mo>0).mean()*100:3.0f}% mean {mo.mean():+5.1f}% worst {mo.min():+5.1f}% | +3 bots {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}',flush=True)
        res[fn]=out
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float));print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
