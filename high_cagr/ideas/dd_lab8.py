"""Drawdown study, stage 8: per-bot losing-streak control (botdd) on top of the stage-6/7 setups. Motivation: in the
Aug-Sep 2025 drawdown the AI regime score stayed high (0.85-0.97) while Ghoghnous (pa) and Mojsavar (c3) lost; a bot whose own
recent closed trades are losing is shrunk regardless of the market score. Same protocol and ranking as dd_lab6.py."""
import sys,json,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab6 as D6
BR={'b2 open-only':((.06,.14,.1),False),'win60 open-only':((.08,.14,.2,60),False),'late .10-.16 all':((.10,.16,.2),True),'b2 all':((.06,.14,.1),True)}
BD={'-':None,'10tr<-3R x.5':(10,-3.,.5),'10tr<-3R x0':(10,-3.,0.),'20tr<-4R x.5':(20,-4.,.5),'8tr<-2R x.3':(8,-2.,.3),'15tr<0 x.5':(15,0.,.5)}
def main():
    p=D6.raw();cs=[]
    for mp,(bn,(b,new)),(dn,bd),t in itertools.product(('off30','off30up'),BR.items(),BD.items(),(13.,14.)):
        cs.append((dict(name=f'{mp} | {bn} | botdd {dn} | t{t:.0f}',ctrl=dict(D6.VT,g=D6.gfrom(p,mp),gopen=True,ddopen=b,ddnew=new,**({'botdd':bd} if bd else {}))),t))
    with Pool(4) as pool:res=pool.map(D6.job,cs)
    for f in DL.PER:a,b=DL.PER[f];D6.BASE[f]=E.period(DL.DEP,np.ones(len(DL.DEP)),a,b)['final']
    for r in res:r['rank']=D6.rank(r)
    res.sort(key=lambda r:r['rank'],reverse=True);(DL.OUT/'stage8.json').write_text(json.dumps(res,indent=1,default=float))
    for r in res:print(f"{r['name']:52s} s={r['scale']:.2f} worst-rel {r['rank'][0]:.2f} | "+' | '.join(f"{f} {v['final']:>8,.0f} {v['dd']:5.1f}" for f,v in r['res'].items()),flush=True)
if __name__=='__main__':main()
