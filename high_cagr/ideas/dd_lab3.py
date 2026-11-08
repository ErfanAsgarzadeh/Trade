"""Drawdown study, stage 3: per-bot AI regime models (dd_ai.py main/c3/pa) and AI de-risking of OPEN positions (gopen),
on top of the best stage-2 setups. Same protocol (scale solved on worst 2022/2023/2024 drawdown = 15%, 2025-26 reported)."""
import sys,json,pickle,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab2 as D2
AIB={b:pickle.loads((ROOT/f'high_cagr/prepared/dd_ai_{b}.pkl').read_bytes()) for b in ('main','c3','pa')}
def gbot(model,mp,bots=('main','c3','pa')):
    out={}
    for b in bots:
        g=np.ones(E.DAYS)
        for fn,o in AIB[b].items():d=o['days'];v=D2.MAP[mp](o[model]);g[d[1:]]=v[:-1]
        out[b]=g
    return out
VT=dict(vt=(.01,20,.3,1.5));VD=dict(vt=(.01,20,.3,1.5),ddt=(.04,.12,.25))
def configs():
    cs=[]
    for model,mp in itertools.product(('gbm','ens'),('lin','strong','cut30','off50')):
        g=D2.gmult(model,mp);gb=gbot(model,mp)
        for base_nm,base in (('vt',VT),('vt+ddt',VD)):
            cs.append(dict(name=f'global {model}/{mp} + {base_nm} + gopen',ctrl=dict(base,g=g,gopen=True)))
            cs.append(dict(name=f'perbot {model}/{mp} + {base_nm}',ctrl=dict(base,gb=gb)))
            cs.append(dict(name=f'perbot {model}/{mp} + {base_nm} + gopen',ctrl=dict(base,gb=gb,gopen=True)))
            cs.append(dict(name=f'global+perbot {model}/{mp} + {base_nm}',ctrl=dict(base,g=g,gb=gb)))
            cs.append(dict(name=f'global {model}/strong + perbot {mp} + {base_nm}',ctrl=dict(base,g=D2.gmult('gbm','strong'),gb=gb)))
    return cs
def main():
    cs=configs()
    with Pool(4) as p:res=p.map(DL.solve,cs)
    (DL.OUT/'stage3.json').write_text(json.dumps(res,indent=1,default=float));DL.show(res)
if __name__=='__main__':main()
