"""Drawdown study, stage 6: fix the weak years of A / B. Diagnosis (continuous account, ablations):
  * the open-position drawdown brake is the biggest profit cost (A without it: 2024 +205% instead of +90%) - it fires on normal
    4-6% dips and, measured from the all-time high, keeps size low for the whole recovery;
  * the AI regime score was too pessimistic in 2022 (B traded only 16% of days while the bots made +19% on the 'off' days) and
    wrong in 2024 (bots made +45% on B's off days).
Tested here (pre-declared): later brakes and brakes measured from a rolling N-day high (release as the account recovers);
softer AI mappings; an ADAPTIVE AI score = rank of today's score among its own last 120 days (removes the level bias of a
model trained in other years) and a blend of both. Same protocol: scale solved on the worst dev (2022-24) drawdown = target
(13% / 14%), 2025-26 reported. Ranking: worst dev period growth relative to the current bots (no weak year), then total."""
import sys,json,itertools,warnings
import numpy as np,pandas as pd
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab2 as D2, dd_lab4 as D4
M={'off50':lambda p:(p>=.5)*1.,'off40':lambda p:(p>=.4)*1.,'off30':lambda p:(p>=.3)*1.,'off30up':lambda p:np.where(p<.3,0.,np.where(p>.7,1.4,1.)),
   'cut30up':lambda p:np.where(p<.3,.3,np.where(p>.7,1.4,1.)),'cut20':lambda p:np.where(p<.2,.25,1.)}
def raw():
    p=np.full(E.DAYS,np.nan)
    for fn,o in D4.AI2.items():p[o['days']]=o['r20']
    return p
def gfrom(p,mp):
    g=np.ones(E.DAYS);ok=np.isfinite(p);v=np.ones(E.DAYS);v[ok]=M[mp](p[ok]);g[1:]=v[:-1];return g
def variants():
    p=raw();rel=pd.Series(p).rolling(120,min_periods=30).apply(lambda x:(x[:-1]<x[-1]).mean(),raw=True).to_numpy();rel=np.where(np.isfinite(rel),rel,p)
    return {'abs':p,'rel120':rel,'blend':.5*p+.5*rel}
VT=dict(vt=(.01,20,.3,1.5))
BR={'b2 .06-.14 fl.1':(.06,.14,.1),'b4 .04-.10 fl.3':(.04,.10,.3),'late .09-.15 fl.1':(.09,.15,.1),'late .10-.16 fl.2':(.10,.16,.2),
    'win60 .08-.14 fl.2':(.08,.14,.2,60),'win90 .06-.12 fl.2':(.06,.12,.2,90),'win120 .10-.15 fl.1':(.10,.15,.1,120),'none':None}
def job(x):
    cfg,t=x;r=DL.solve(cfg,t);r['target']=t;return r
BASE={}
def rank(r):
    rel=[np.log(r['res'][f]['final']/1e4)/np.log(BASE[f]/1e4) for f in DL.DEV];return (min(rel),sum(np.log(r['res'][f]['final']/1e4) for f in DL.DEV))
def main():
    V=variants();cs=[]
    for (vn,p),mp,(bn,b),t in itertools.product(V.items(),M,BR.items(),(13.,14.)):
        if vn!='abs' and mp in ('cut20',):continue
        ctrl=dict(VT,g=gfrom(p,mp),gopen=True,**({'ddopen':b} if b else {}))
        cs.append((dict(name=f'{vn}/{mp} | {bn} | t{t:.0f}',ctrl=ctrl),t))
    print(len(cs),'configs',flush=True)
    with Pool(4) as pool:res=pool.map(job,cs)
    for f in DL.PER:a,b=DL.PER[f];BASE[f]=E.period(DL.DEP,np.ones(len(DL.DEP)),a,b)['final']
    for r in res:r['rank']=rank(r)
    res.sort(key=lambda r:r['rank'],reverse=True);(DL.OUT/'stage6.json').write_text(json.dumps(res,indent=1,default=float))
    print('current bots per period:',{f:round(v) for f,v in BASE.items()})
    for r in res[:40]:print(f"{r['name']:42s} s={r['scale']:.2f} worst-rel {r['rank'][0]:.2f} | "+' | '.join(f"{f} {v['final']:>8,.0f} {v['dd']:5.1f}" for f,v in r['res'].items()),flush=True)
if __name__=='__main__':main()
