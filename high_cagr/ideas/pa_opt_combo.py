"""PA optimisation, final step: combine the ideas that improved PA ALONE consistently in the 12-agent meeting.
Written and committed BEFORE running; one run, no tuning afterwards.

Meeting result (96 variants, high_cagr/output/ideas/pa_opt/): only momfilt/G_boost2 and locfilt/no_frisat passed
P1-P5 and both were refuted by the auditors (fragile neighbours, post-hoc weekday). Several ideas raised PA-alone quality
and IN15 generalisation on every slice but lowered the THREE account at the fixed 0.15% risk:
  NOTGT (no target, 30-bar time stop): PA full CAGR 21.6% vs 5.1%, IN15 0.51 vs 0.11
  volfilt B (skip signal bar range < 1.1 ATR): IN15 0.55; volfilt H (skip ATR<0.85 x median OR range<1.1 OR stop<3%): IN15 0.51
  runner C (trail 3 ATR after 1R, hold 60): IN15 0.53
Hypothesis: the account lost because a better PA at the SAME risk changes the PA/TWO mix; choosing PA risk on TRAIN
for the improved PA should let the account keep the gain. Variants (rules fixed from the meeting, nothing new):
  C1 = NOTGT + B     C2 = NOTGT + H     C3 = runner C + B     C4 = baseline rules (control for the risk re-choice)
For each: PA risk chosen on TRAIN from {0.10, 0.15, 0.20, 0.25, 0.30}% = highest THREE train Calmar with THREE train
max DD <= baseline THREE train DD + 1 pp. Gates at the chosen risk, vs the deployed baseline (0.15%):
  P1 THREE train Calmar >= baseline + 0.10   P2 THREE valid Calmar >= baseline   P3 THREE full DD <= baseline + 1 pp
  P4 PA-alone IN15 full Calmar >= baseline IN15   P5 causal
  P6 the combo must beat C4 (same risk re-choice on the baseline rules) on THREE train AND valid Calmar.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import pabench as PB, xuni as X
RISKS=[.001,.0015,.002,.0025,.003]
VARIANTS={'C1_notgt_B':dict(ex=dict(target_r=0.),r=1.1),'C2_notgt_H':dict(ex=dict(target_r=0.),r=1.1,a=.85,s=3.),
          'C3_trail_B':dict(ex=dict(target_r=0.,trail_after_r=1.,trail_atr=3.,hold=60),r=1.1),'C4_control':dict(ex={})}

def fn(d,v):
    n=d['n'];a=d['atr'][:n];side=d['sig']['side'][:n].copy()
    med=pd.Series(a).rolling(60).median().shift(1).to_numpy();rel=a/med;rng=(d['h'][:n]-d['l'][:n])/a
    lev=d['sig']['lev'][:n];stp=np.abs(lev-d['sig']['stp'][:n])/np.abs(lev)*100;bad=np.zeros(n,bool)
    if 'r' in v:bad|=~(rng>=v['r'])
    if 'a' in v:bad|=~(rel>=v['a'])
    if 's' in v:bad|=~(stp>=v['s'])
    side[bad]=0;return PB.run(d,side=side,**v['ex'])

def main():
    b=PB.baseline();bot,c3=PB.two();tw=bot+c3;out=dict(notes=__doc__,baseline=b,variants={})
    for name,v in VARIANTS.items():
        r=PB.evaluate(fn,v);s=r.pop('_series');grid=[]
        for x in RISKS:t=X.stats(tw+s*(x/PB.RISK));grid.append(dict(risk=x,train=t['train'],oos=t['oos'],full=t['full']))
        ok=[g for g in grid if g['train'][2]<=b['three']['train'][2]+1.];pick=max(ok,key=lambda g:g['train'][0]) if ok else grid[0]
        out['variants'][name]=dict(variant=v,pa=r['pa'],in15=r['in15'],trades=r['trades'],grid=grid,pick=pick,causal=PB.check_causal(fn,v))
        print(f"{name}: PA train {r['pa']['train'][0]:.2f} valid {r['pa']['oos'][0]:.2f} CAGR {r['pa']['full'][1]:.1f}% DD {r['pa']['full'][2]:.1f}% IN15 {r['in15']['full'][0]:.2f} | risk {pick['risk']*100:.2f}% THREE train {pick['train'][0]:.2f} valid {pick['oos'][0]:.2f} full {pick['full'][0]:.2f} (CAGR {pick['full'][1]:.1f}% DD {pick['full'][2]:.1f}%)",flush=True)
    c4=out['variants']['C4_control']['pick']
    for name,o in out['variants'].items():
        p=o['pick'];G=dict(P1=p['train'][0]>=b['three']['train'][0]+.1,P2=p['oos'][0]>=b['three']['oos'][0],P3=p['full'][2]<=b['three']['full'][2]+1.,
            P4=o['in15']['full'][0]>=b['in15']['full'][0],P5=o['causal']['causal'],P6=name!='C4_control' and p['train'][0]>c4['train'][0] and p['oos'][0]>c4['oos'][0])
        o['gates']={k:bool(x) for k,x in G.items()};o['passed']=bool(all(G.values()))
        print(name,o['gates'],'PASS=',o['passed'],flush=True)
    PB.OUT.mkdir(parents=True,exist_ok=True);(PB.OUT/'combo.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
