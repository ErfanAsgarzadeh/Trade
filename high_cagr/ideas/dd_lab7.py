"""Drawdown study, stage 7: brake that acts only on positions open when it deepens (ddnew=False, new trades keep full size so
the recovery is caught), vs the normal brake, with the best stage-6 AI mappings (absolute score: off30, off30up, cut30up).
Same protocol and ranking as dd_lab6.py."""
import sys,json,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab6 as D6
BR={'late .09-.15 fl.1':(.09,.15,.1),'late .10-.16 fl.2':(.10,.16,.2),'win60 .08-.14 fl.2':(.08,.14,.2,60),'b2 .06-.14 fl.1':(.06,.14,.1),
    'mid .07-.13 fl0':(.07,.13,0.),'b4 .04-.10 fl.3':(.04,.10,.3)}
def main():
    p=D6.raw();cs=[]
    for mp,(bn,b),new,t in itertools.product(('off30','off30up','cut30up'),BR.items(),(True,False),(13.,14.)):
        cs.append((dict(name=f'{mp} | {bn} | {"brake all" if new else "brake open-only"} | t{t:.0f}',ctrl=dict(D6.VT,g=D6.gfrom(p,mp),gopen=True,ddopen=b,ddnew=new)),t))
    with Pool(4) as pool:res=pool.map(D6.job,cs)
    for f in DL.PER:a,b=DL.PER[f];D6.BASE[f]=E.period(DL.DEP,np.ones(len(DL.DEP)),a,b)['final']
    for r in res:r['rank']=D6.rank(r)
    res.sort(key=lambda r:r['rank'],reverse=True);(DL.OUT/'stage7.json').write_text(json.dumps(res,indent=1,default=float))
    for r in res:print(f"{r['name']:50s} s={r['scale']:.2f} worst-rel {r['rank'][0]:.2f} | "+' | '.join(f"{f} {v['final']:>8,.0f} {v['dd']:5.1f}" for f,v in r['res'].items()),flush=True)
if __name__=='__main__':main()
