#!/usr/bin/env python3
"""Stricter portfolio test on fx_search streams: one bot = same parameters on all 3 pairs,
every year positive, correlation < 0.8, at most 8 bots.  Mode IS picks on 2021-11..2024-12,
mode FULL picks on all five years (hindsight).  Output: reports/fx_robust.json"""
import sys,json,numpy as np,pandas as pd
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import fx_lab as fl, fx_search as fs
z=np.load(HERE/'data'/'fx_search_streams.npz');S=z['S'].astype(float);LV=z['LV'].astype(float)
items=list(fl.families());n=len(items)
# reconstruct day axis
t=[pd.read_csv(HERE/'data'/'ohlcv'/f'{p[:3]}_{p[3:]}_bid_1m.csv',usecols=[0]).timestamp for p in fl.PAIRS]
d0=int(min(x.min() for x in t)//fl.DAY_MS);nd=S.shape[1]
days=pd.to_datetime((np.arange(nd)+d0)*fl.DAY_MS,unit='ms')
split=int(np.searchsorted(days.values,np.datetime64('2025-01-01')))
bot=S.reshape(n,3,nd).sum(1);blv=LV.reshape(n,3,nd).sum(1)
yr=days.year.values
def sh(x): return x.mean()/x.std()*np.sqrt(365.25) if x.std()>0 else 0
out={}
for mode in ['IS','FULL']:
  end=split if mode=='IS' else nd
  years=[y for y in range(2022,2025 if mode=='IS' else 2027)]
  cand=[]
  for i in range(n):
    x=bot[i,:end]
    if sh(x)<0.5: continue
    if not all(bot[i][yr==y].sum()>0 for y in years): continue
    cand.append(i)
  cand.sort(key=lambda i:-sh(bot[i,:end]))
  kept=[]
  for i in cand:
    if all(np.corrcoef(bot[i,:end],bot[k,:end])[0,1]<0.8 for k in kept): kept.append(i)
  ch=fs.greedy(bot[:,:end],kept,k_max=8)
  R=bot[ch].sum(0);L=blv[ch].sum(0)
  f,ok=fs.risk_for(R[:end],1.0,end/365.25,fmax=0.06)
  res=dict(candidates=len(cand),bots=[dict(family=items[i][0],tf=items[i][1],params={k:(list(v) if isinstance(v,tuple) else v) for k,v in items[i][2].items()},exits=items[i][3],sh_is=round(sh(bot[i,:split]),2),sh_oos=round(sh(bot[i,split:]),2),r_is=round(float(bot[i,:split].sum()),1),r_oos=round(float(bot[i,split:].sum()),1)) for i in ch],
    risk_for_100=round(f,4),reached=ok)
  for name,s in [('full',slice(0,nd)),('in_sample',slice(0,split)),('out_of_sample',slice(split,nd))]:
    y=(s.stop-s.start)/365.25
    res[name]={k:{a:round(b,3) for a,b in fs.stats(R[s],L[s],ff,y).items()} for k,ff in [('target_risk',f),('risk_1pct',0.01),('risk_0.5pct',0.005)]}
    res[name]['yearly_R']={int(yy):round(float(R[s][yr[s]==yy].sum()),1) for yy in np.unique(yr[s])}
  out[mode]=res
  print(mode,len(cand),len(ch),f,ok)
  for b in res['bots']: print('  ',b['family'],b['tf'],b['params'],b['exits'],b['sh_is'],b['sh_oos'],b['r_is'],b['r_oos'])
  for k in ['full','in_sample','out_of_sample']: print(' ',k,res[k])
json.dump(out,open(HERE/'reports'/'fx_robust.json','w'),indent=1,default=float)
