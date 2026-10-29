"""Drawdown study, stage 9: fine brake levels for the stage-8 winner (AI off30up + vol target + AI on open positions +
per-bot streak control 20 trades < -4R -> x0.5). Same protocol and ranking as dd_lab6.py."""
import sys,json,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab6 as D6
BR=[(.08,.14,.2),(.09,.15,.2),(.10,.15,.1),(.08,.15,.3),(.10,.16,.2),(.09,.14,.1),(.07,.15,.3),(.10,.14,0.)]
def main():
    p=D6.raw();cs=[]
    for mp,b,t in itertools.product(('off30up','off30'),BR,(13.,14.)):
        cs.append((dict(name=f'{mp} | brake {b} all | botdd 20<-4R x.5 | t{t:.0f}',ctrl=dict(D6.VT,g=D6.gfrom(p,mp),gopen=True,ddopen=b,botdd=(20,-4.,.5))),t))
    with Pool(4) as pool:res=pool.map(D6.job,cs)
    for f in DL.PER:a,b=DL.PER[f];D6.BASE[f]=E.period(DL.DEP,np.ones(len(DL.DEP)),a,b)['final']
    for r in res:r['rank']=D6.rank(r)
    res.sort(key=lambda r:r['rank'],reverse=True);(DL.OUT/'stage9.json').write_text(json.dumps(res,indent=1,default=float))
    for r in res:print(f"{r['name']:56s} s={r['scale']:.2f} worst-rel {r['rank'][0]:.2f} | "+' | '.join(f"{f} {v['final']:>8,.0f} {v['dd']:5.1f}" for f,v in r['res'].items()),flush=True)
if __name__=='__main__':main()
