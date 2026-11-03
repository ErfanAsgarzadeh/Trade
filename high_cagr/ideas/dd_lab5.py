"""Drawdown study, stage 5: hard drawdown brake on open positions (ddopen) added to the best dev setups of stages 2-4,
and a safety margin (scale solved for a 13% dev drawdown instead of 15%). Same protocol as dd_lab.py."""
import sys,json,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_lab as DL, dd_lab2 as D2, dd_lab4 as D4
VT=dict(vt=(.01,20,.3,1.5));VD=dict(vt=(.01,20,.3,1.5),ddt=(.04,.12,.25))
def tops():
    return {'A r20/cut30up+vt+gopen':dict(VT,g=D4.g2('r20','cut30up'),gopen=True),'B r20/off50+vt+gopen':dict(VT,g=D4.g2('r20','off50'),gopen=True),
            'C r20/strong+vt+ddt':dict(VD,g=D4.g2('r20','strong')),'D r20/off50+vt+ddt':dict(VD,g=D4.g2('r20','off50')),
            'E v1 gbm/strong+vt+gopen':dict(VT,g=D2.gmult('gbm','strong'),gopen=True),'F vt only':dict(VT)}
BRAKES={'-':None,'b1 .05-.12 fl.2':(.05,.12,.2),'b2 .06-.14 fl.1':(.06,.14,.1),'b3 .08-.14 fl.25':(.08,.14,.25),'b4 .04-.10 fl.3':(.04,.10,.3)}
def job(x):
    cfg,t=x;r=DL.solve(cfg,t);r['target']=t;return r
def main():
    cs=[]
    for (tn,c),(bn,b),t in itertools.product(tops().items(),BRAKES.items(),(15.,13.)):
        cs.append((dict(name=f'{tn} | brake {bn} | dev target {t:.0f}',ctrl=dict(c,**({'ddopen':b} if b else {}))),t))
    with Pool(4) as p:res=p.map(job,cs)
    (DL.OUT/'stage5.json').write_text(json.dumps(res,indent=1,default=float));DL.show(res)
if __name__=='__main__':main()
