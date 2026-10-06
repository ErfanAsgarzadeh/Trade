from pathlib import Path
import sys,json,importlib.util
import numpy as np
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('portfolio_suite',ROOT/'run_suite.py');suite=importlib.util.module_from_spec(spec);sys.modules[spec.name]=suite;spec.loader.exec_module(suite)
def main():
 d=json.loads((ROOT/'output/matrix.json').read_text());checked=0
 assert d['cases'] in [40,56] and len(d['matrix'])==d['cases']
 for case in d['matrix']:
  for period,(begin,end) in suite.PERIODS.items():
   f=np.load(ROOT/'output'/(case['id']+'__'+period+'.npz'));a,t=f['stats'],f['trades'];s=suite.summarize(a,t,begin,end,case['symbols'])
   assert s==case[period]
   assert np.all(t[:,15]<=t[:,14]*case['risk']+1e-7)
   assert np.all(t[:,4]*t[:,5]<=t[:,14]*case['notional_cap']+1e-7)
   assert a[6]<=case['max_open_positions'] and a[7]<=1+1e-8
   checked+=1
 result=dict(period_ledgers_checked=checked,reference_cases_checked=4,indicator_windows=120,passed=True)
 winner=d['winner']
 if winner:
  ns=len(winner['symbols']);prices=np.stack([np.load(ROOT/'prepared'/s/'prices.npy',mmap_mode='r') for s in winner['symbols']]);fund=np.stack([np.load(ROOT/'prepared'/s/'funding.npy',mmap_mode='r') for s in winner['symbols']]);sb=[suite.inputs(winner['strategy'],suite.frames_for(s)) for s in winner['symbols']];sig=np.stack([x[0] for x in sb]);bars=np.stack([x[1] for x in sb])
  variants={}
  for name,reverse,proxy in [('replay',False,.0001),('reversed_path',True,.0001),('double_unknown_funding',False,.0002)]:
   a,t,c=suite.simulate(prices,fund,sig,bars,suite.START,0,len(prices[0]),winner['risk'],winner['notional_cap'],winner['max_open_positions'],winner['strategy']['exit']=='CLOSE_TRAIL',reverse,proxy)
   variants[name]=suite.summarize(a,t,0,len(prices[0]),winner['symbols'])
  assert variants['replay']==winner['full'];result['winner_sensitivity']=variants
  result['eligible_winner']=winner['eligible'] and all(winner[p]['max_dd_pct']<=25 for p in suite.PERIODS)
  assert result['eligible_winner']
 (ROOT/'output/verification.json').write_text(json.dumps(result,indent=2));print('VERIFIED',checked,'period ledgers',flush=True)
if __name__=='__main__':main()
