"""Drawdown study, stage 2: the AI regime multiplier (dd_ai.py) alone and combined with the best stage-1 controls.
Same protocol as dd_lab.py: risk scale solved so the worst drawdown of 2022/2023/2024 is 15%, 2025-26 reported.
The multiplier for day d uses the model score computed at the close of day d-1.
Mappings of the score percentile p: lin = 0.5+p, strong = 0.25+1.5p, cut30 = 0.4 if p<0.3 else 1, cut30up = 0.3 if p<0.3,
1.4 if p>0.7, else 1; off50 = 0 if p<0.5 else 1 (trade only in the better half).
"""
import sys,json,pickle,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL
AI=pickle.loads((ROOT/'high_cagr/prepared/dd_ai.pkl').read_bytes())
MAP={'lin':lambda p:.5+p,'strong':lambda p:.25+1.5*p,'cut30':lambda p:np.where(p<.3,.4,1.),'cut30up':lambda p:np.where(p<.3,.3,np.where(p>.7,1.4,1.)),'off50':lambda p:(p>=.5)*1.}
def gmult(model,mp):
    g=np.ones(E.DAYS)
    for fn,o in AI.items():d=o['days'];v=MAP[mp](o[model]);g[d[1:]]=v[:-1]
    return g
BEST={'none':{},'vt':dict(vt=(.01,20,.3,1.5)),'ddt':dict(ddt=(.04,.12,.25)),'eqma':dict(eqma=(20,.5)),'vt+ddt':dict(vt=(.01,20,.3,1.5),ddt=(.04,.12,.25)),
      'vt+eqma':dict(vt=(.01,20,.3,1.5),eqma=(20,.5)),'vt+ddt+eqma':dict(vt=(.01,20,.3,1.5),ddt=(.04,.12,.25),eqma=(20,.5))}
def configs():
    cs=[dict(name=k,ctrl=v) for k,v in BEST.items() if k!='none']
    for model,mp in itertools.product(('ens','gbm','ridge','ens_all'),MAP):
        g=gmult(model,mp)
        for k,v in BEST.items():cs.append(dict(name=f'AI {model}/{mp} + {k}',ctrl=dict(v,g=g)))
    for t,lb,hi in itertools.product((.008,.01,.012),(10,20,30),(1.5,2.5)):cs.append(dict(name=f'vt {t} lb{lb} hi{hi}',ctrl=dict(vt=(t,lb,.3,hi))))
    return cs
def main():
    cs=configs()
    with Pool(4) as p:res=p.map(DL.solve,cs)
    for r in res:r['res']={f:{k:v for k,v in x.items()} for f,x in r['res'].items()}
    (DL.OUT/'stage2.json').write_text(json.dumps([dict(name=r['name'],scale=r['scale'],res=r['res']) for r in res],indent=1,default=float));DL.show(res)
if __name__=='__main__':main()
