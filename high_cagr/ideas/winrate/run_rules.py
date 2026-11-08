"""Entry rules from the failure diagnosis (POST-HOC: the diagnosis looked at both periods, so validation is not clean)
and their combination with the pre-declared exit winner (Mojsavar: lock 1R->+0.1R, half at 2R).
Rule = skip a ROOT entry when the feature is above its TRAIN-period 80th percentile for that bot (adds follow roots)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG, exits as E
RULES={'main_late':('main','f_ret60'),'main_wide':('main','f_atrp'),'c3_crowd':('c3','f_fund3d')}
C3EXIT=dict(bots=('c3',),pfrac=.5,ptarget=2.,arm=1.,lock=.1)
def thresholds(df):
    r=df[~df.is_add&(df.period=='train')];return {k:float(r[r.bot==b][c].quantile(.8)) for k,(b,c) in RULES.items()}
def keep_mask(df,names,thr):
    drop=np.zeros(len(df),bool)
    for k in names:
        b,c=RULES[k];drop|=(df.bot==b).to_numpy()&~df.is_add.to_numpy()&(df[c].to_numpy()>thr[k])
    roots=set(df.root[drop]);return ~df.root.isin(roots).to_numpy()
def main():
    df=LG.build();legs=LG.raw_legs();thr=thresholds(df);res=dict(thresholds=thr)
    c3x,_=E.modified_legs(legs,**C3EXIT)
    combos={'none':[],**{k:[k] for k in RULES},'main_late+c3_crowd':['main_late','c3_crowd'],'all3':list(RULES)}
    fmt=lambda r:f"WR tr {r['win_rate']['train']:.1f} va {r['win_rate']['valid']:.1f} (main {r['win_rate']['main']:.1f} c3 {r['win_rate']['c3']:.1f} pa {r['win_rate']['pa']:.1f}) | Calmar tr {r['train'][0]:.2f} va {r['valid'][0]:.2f} | CAGR {r['cagr']:.1f} DD {r['dd']:.1f} PF {r['pf']:.2f} | final {r['final']:,.0f}"
    for base_name,L in (('shipped',legs),('c3exit',c3x)):
        for name,rs in combos.items():
            k=keep_mask(df,rs,thr);r=E.account_stats(E.replay_legs([l for l,x in zip(L,k) if x]));r['dropped']=int((~k).sum())
            res[f'{base_name}|{name}']=r;print(f'{base_name}|{name}',fmt(r),'dropped',r['dropped'],flush=True)
    (LG.OUT/'rules.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
