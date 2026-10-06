"""Audit every saved period; replay and adverse-path sensitivity for the winner."""
from pathlib import Path
import sys,json,zipfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.run_suite import *

def main():
 m=json.loads((OUT/'matrix.json').read_text());assert len(m['matrix'])==384;audited=0
 for r in m['matrix']:
  for period,(begin,end) in PERIODS.items():
   path=OUT/(r['id']+'__'+period+'.npz')
   with zipfile.ZipFile(path) as z:assert z.testzip() is None
   z=np.load(path);a=z['stats'];t=z['trades'];c=z['equity'];actual=summarize(a,t,c,begin,end,r['symbols'])
   for key in ['net_profit','trades','cagr_pct','max_dd_pct','fees','funding_pnl','pyramid_adds','avg_margin_pct']:
    np.testing.assert_allclose(actual[key],r[period][key],rtol=1e-11,atol=1e-7,err_msg=path.name+':'+key)
   assert a[6]<=r['max_open_positions'] and a[7]<=.60+1e-8
   fractions=np.where(t[:,18]==1,.5,1.)
   assert np.all(t[:,15]<=t[:,14]*r['risk']*fractions+1e-7)
   adds=t[t[:,18]==1]
   assert len(np.unique(adds[:,17]))==len(adds)
   for unit in adds:
    parent=t[int(unit[17])];assert parent[18]==0 and parent[0]==unit[0] and parent[3]==unit[3]
    assert unit[1]>parent[1] and unit[2]==parent[2]
    assert unit[3]*(unit[6]-parent[4])>=parent[4]*.0016-1e-7
    assert unit[3]*(unit[4]-parent[4])>=2*parent[7]-1e-7
   audited+=1
 print('AUDITED',audited,flush=True)
 w=m['winner'];frames=load_frames();indices=[SYMBOLS.index(s) for s in w['symbols']];prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in w['symbols']]);fund=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in w['symbols']]);ss,bb,step=inputs(w,frames);sens=[]
 for label,reverse,proxy in [('replay',False,.0001),('reverse_minute_path',True,.0001),('double_unknown_funding',False,.0002)]:
  begin,end=PERIODS['full'];a,t,c=simulate(prices,fund,ss,bb,START,begin,end,w['risk'],w['max_open_positions'],step,w['pyramid'],False,reverse,proxy);r=summarize(a,t,c,begin,end,w['symbols']);sens.append(dict(scenario=label,full=r))
  if label=='replay':
   for k in ['net_profit','max_dd_pct','trades','pyramid_adds']:np.testing.assert_allclose(r[k],w['full'][k],atol=1e-7)
 result=dict(audited_period_ledgers=audited,configs=384,cost_and_risk_reconciliation=True,pyramid_invariants=True,winner_sensitivity=sens);atomic(OUT/'verification.json',result);print([(r['scenario'],r['full']['cagr_pct'],r['full']['max_dd_pct']) for r in sens],flush=True)
if __name__=='__main__':main()
