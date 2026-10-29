"""Failure taxonomy of the shipped legs (descriptive): every losing leg gets ONE cause from its minute path."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG
CATS=['WIN','GIVEBACK_GE1R','GIVEBACK_05_1R','FAST_STOP_LE8H','NO_FOLLOW_LT02R','WEAK_02_05R']
def cause(r):
    if r.R>0:return 'WIN'
    if r.mfe_R>=1:return 'GIVEBACK_GE1R'
    if r.mfe_R>=.5:return 'GIVEBACK_05_1R'
    if r.hours<=8:return 'FAST_STOP_LE8H'
    return 'NO_FOLLOW_LT02R' if r.mfe_R<.2 else 'WEAK_02_05R'
def main():
    df=LG.build();df['cause']=df.apply(cause,axis=1);out={}
    for b,g in df.groupby('bot'):
        t=g.groupby('cause').agg(n=('R','size'),sumR=('R','sum'),medR=('R','median'),hours=('hours','median'))
        t['share']=t.n/len(g)*100;out[b]=dict(legs=len(g),win=float(g.win.mean()*100),mean_R=float(g.R.mean()),
            win_by_period={p:float(x.win.mean()*100) for p,x in g.groupby('period')},causes=t.reindex(CATS).fillna(0).round(3).to_dict(orient='index'))
    (LG.OUT/'diagnosis.json').write_text(json.dumps(out,indent=1,default=float));print(json.dumps(out,indent=1,default=float)[:1500])
if __name__=='__main__':main()
