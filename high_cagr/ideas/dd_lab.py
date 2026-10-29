"""Drawdown study, stage 1: account-level risk controls on the LBank-feasible system (three bots + entry filter E + momentum
sizing M). Goal set by the user: max drawdown <= 15% in EVERY year while keeping profit.
Method: for each control configuration, find (bisection) the global risk scale at which the WORST drawdown of the dev periods
(2022, 2023, 2024) is exactly 15%, then report the profit at that scale for every period including 2025-26 (held out from
the choice). 2022 has no trained entry model (training data start 2021-10), so it uses M only; 2023+ use E+M.
"""
import sys,json,pickle,itertools,warnings
import numpy as np
from pathlib import Path
from multiprocessing import Pool
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, ml_walkforward as WF
OUT=ROOT/'high_cagr/output/ideas/dd_lab';C=pickle.loads((ROOT/'high_cagr/prepared/dd_cache.pkl').read_bytes());DEP=C['dep'];MP=C['mp']
PER={'2022':(WF.mn('2022-01-01'),WF.mn('2023-01-01')),**WF.FOLDS};DEV=('2022','2023','2024')
def mult(fn,legs_kind='EM'):
    if fn=='2022':return .5+MP
    return (C['folds'][fn]['ep']>=.2)*(.5+MP)
def legs(fn,protect):return C['folds'][fn]['Lp'] if (protect and fn!='2022') else DEP
def run(cfg,s,fns):
    ctrl=dict(cfg['ctrl']);ctrl['scale']=s*ctrl.get('scale',1.);o={}
    for fn in fns:
        a,b=PER[fn];r=E.period(legs(fn,cfg.get('protect')),mult(fn),a,b,ctrl);r.pop('daily');o[fn]=r
    return o
def solve(cfg,target=15.):
    lo,hi=.1,2.5
    for _ in range(9):
        mid=(lo+hi)/2;o=run(cfg,mid,DEV);w=min(v['dd'] for v in o.values())
        if -w>target:hi=mid
        else:lo=mid
    o=run(cfg,lo,PER);return dict(name=cfg['name'],scale=lo,res=o)
def configs():
    cs=[dict(name='none',ctrl={})]
    for d0,d1,fl in itertools.product((.04,.06,.08,.10),(.12,.15,.20),(0.,.25,.5)):cs.append(dict(name=f'ddt {d0}-{d1} fl{fl}',ctrl=dict(ddt=(d0,d1,fl))))
    for h in (.02,.03,.04,.05,.06,.08):cs.append(dict(name=f'heat {h}',ctrl=dict(heat=h)))
    for h in (.015,.02,.03,.04):cs.append(dict(name=f'side_heat {h}',ctrl=dict(side_heat=h)))
    for t,lb in itertools.product((.01,.015,.02),(20,40)):cs.append(dict(name=f'vt {t} lb{lb}',ctrl=dict(vt=(t,lb,.3,1.5))))
    for n,mu in itertools.product((10,20,40),(0.,.5)):cs.append(dict(name=f'eqma {n} x{mu}',ctrl=dict(eqma=(n,mu))))
    for x,cu in itertools.product((.06,.08,.10,.12),(.3,.5)):cs.append(dict(name=f'breaker {x} cut{cu}',ctrl=dict(breaker=(x,cu))))
    for bm in ({'pa':.5},{'c3':.5},{'pa':.5,'c3':.5},{'main':.7},{'pa':0.},{'c3':0.}):cs.append(dict(name='bots '+str(bm),ctrl=dict(bots=bm)))
    cs.append(dict(name='protect',ctrl={},protect=True))
    return cs
def main():
    OUT.mkdir(parents=True,exist_ok=True);cs=configs()
    with Pool(4) as p:res=p.map(solve,cs)
    (OUT/'stage1.json').write_text(json.dumps(res,indent=1,default=float));show(res)
def score(r):return np.mean([np.log(r['res'][f]['final']/1e4)/(len(r['res'][f]['years'])) for f in DEV])
def show(res):
    for r in sorted(res,key=score,reverse=True):
        print(f"{r['name']:34s} s={r['scale']:.2f} | "+' | '.join(f"{f} {v['final']:>8,.0f} {v['dd']:5.1f}" for f,v in r['res'].items()),flush=True)
if __name__=='__main__':main()
