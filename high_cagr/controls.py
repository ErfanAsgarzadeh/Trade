"""Frozen close-only controls and the prior six-symbol study."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.run_suite import *

def main():
 frames=load_frames();prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in SYMBOLS]);rows=[]
 for label,symbols,risk in [('BTC_ORIGINAL',SYMBOLS[:1],.00375),('FIVE_ORIGINAL_RISK',SYMBOLS,.00375),('FIVE_CURRENT_DEPLOYED_RISK',SYMBOLS,.005)]:
  case=dict(symbols=symbols,preset='crypto',entry_timeframe='4h',lookback=20,trail='KIJUN');ss,bb,step=inputs(case,frames);row=dict(id=label)
  ns=len(symbols)
  for period,(begin,end) in PERIODS.items():
   a,t,curve=simulate(prices[:ns],funding[:ns],ss,bb,START,begin,end,risk,4,step,False,True,False,.0001,1.,0.,1.25)
   row[period]=summarize(a,t,curve,begin,end,symbols)
  rows.append(row)
 # The frozen winner itself is a committed control, independent of the new suite.
 old=json.loads((ROOT/'portfolio/output/matrix.json').read_text())['winner'];rows.insert(0,dict(id='SIX_FROZEN_WINNER',**{p:old[p] for p in PERIODS}))
 atomic(OUT/'controls.json',rows);print([(r['id'],r['full']['cagr_pct']) for r in rows],flush=True)
if __name__=='__main__':main()
