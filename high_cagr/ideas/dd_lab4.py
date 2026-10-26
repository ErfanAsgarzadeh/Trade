"""Drawdown study, stage 4: AI regime model v2 (dd_ai2.py: more data + forward-drawdown target) as the account multiplier,
with the stage-1/2 controls and AI de-risking of open positions. Same protocol as dd_lab.py."""
import sys,json,pickle,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab2 as D2
AI2=pickle.loads((ROOT/'high_cagr/prepared/dd_ai2.pkl').read_bytes())
def g2(model,mp):
    g=np.ones(E.DAYS)
    for fn,o in AI2.items():d=o['days'];v=D2.MAP[mp](o[model]);g[d[1:]]=v[:-1]
    return g
BASES={'none':{},'vt':dict(vt=(.01,20,.3,1.5)),'vt+ddt':dict(vt=(.01,20,.3,1.5),ddt=(.04,.12,.25)),'ddt':dict(ddt=(.04,.12,.25))}
def configs():
    cs=[]
    for model,mp in itertools.product(('combo','dd10','r20'),('lin','strong','cut30','cut30up','off50')):
        g=g2(model,mp)
        for bn,b in BASES.items():
            cs.append(dict(name=f'AI2 {model}/{mp} + {bn}',ctrl=dict(b,g=g)))
            cs.append(dict(name=f'AI2 {model}/{mp} + {bn} + gopen',ctrl=dict(b,g=g,gopen=True)))
    return cs
def main():
    cs=configs()
    with Pool(4) as p:res=p.map(DL.solve,cs)
    (DL.OUT/'stage4.json').write_text(json.dumps(res,indent=1,default=float));DL.show(res)
if __name__=='__main__':main()
