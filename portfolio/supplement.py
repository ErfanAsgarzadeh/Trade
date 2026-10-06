"""Predeclared lower-risk follow-up after all 24 requested portfolios failed DD25.
Original 40-case grid/results stay unchanged. This is adaptive research, not OOS.
"""
from pathlib import Path
import importlib.util,sys,json,copy
import numpy as np
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('portfolio_suite',ROOT/'run_suite.py');suite=importlib.util.module_from_spec(spec);sys.modules[spec.name]=suite;spec.loader.exec_module(suite)
def main():
 original=json.loads((ROOT/'output/matrix.json').read_text())
 if len(original['matrix'])!=40:
  original=json.loads((ROOT/'output/requested_matrix.json').read_text())
 else:suite.atomic(ROOT/'output/requested_matrix.json',original)
 assert not original['winner']
 cases=[]
 for reference in [x for x in original['matrix'] if x['kind']=='BTC_REFERENCE']:
  for risk in [.00375,.005]:
   for slots in [3,4]:
    c={k:copy.deepcopy(reference[k]) for k in ['strategy','kind','risk','notional_cap','max_open_positions','symbols']}
    c.update(kind='PORTFOLIO',risk=risk,notional_cap=1.25,max_open_positions=slots,symbols=suite.SYMBOLS,supplemental=True)
    c['id']=f"{c['strategy']['id']}__PORTFOLIO__R{risk:g}__P{slots}";cases.append(c)
 definition=dict(reason='All 24 original portfolios have full DD>25%; test lower sizing, no strategy modifications',cases=cases,registered_after_original_results=True,selection=original['declaration']['selection'])
 path=ROOT/'output/supplement_grid.json'
 if path.exists():assert json.loads(path.read_text())==definition
 else:suite.atomic(path,definition)
 prices=np.stack([np.load(ROOT/'prepared'/s/'prices.npy',mmap_mode='r') for s in suite.SYMBOLS]);fund=np.stack([np.load(ROOT/'prepared'/s/'funding.npy',mmap_mode='r') for s in suite.SYMBOLS]);frames=[suite.frames_for(s) for s in suite.SYMBOLS]
 complete=[]
 for index,c in enumerate(cases,1):
  checkpoint=ROOT/'output'/(c['id']+'.json');case=json.loads(checkpoint.read_text()) if checkpoint.exists() else c
  sb=[suite.inputs(c['strategy'],f) for f in frames];sig=np.stack([x[0] for x in sb]);bars=np.stack([x[1] for x in sb])
  for period,(begin,end) in suite.PERIODS.items():
   if period in case:continue
   a,t,curve=suite.simulate(prices,fund,sig,bars,suite.START,begin,end,c['risk'],c['notional_cap'],c['max_open_positions'],c['strategy']['exit']=='CLOSE_TRAIL')
   case[period]=suite.summarize(a,t,begin,end,suite.SYMBOLS);np.savez_compressed(ROOT/'output'/(case['id']+'__'+period+'.npz'),stats=a,trades=t,equity=curve);suite.atomic(checkpoint,case)
  case['eligible']=case['full']['trades']>=40 and case['train']['net_profit']>0 and case['oos']['net_profit']>0 and all(case[p]['max_dd_pct']<=25 for p in suite.PERIODS);suite.atomic(checkpoint,case);complete.append(case)
  print(index,case['strategy']['setting'],case['strategy']['trail'],case['risk'],case['max_open_positions'],'net',round(case['full']['net_profit'],2),'dd',round(case['full']['max_dd_pct'],2),'oos',round(case['oos']['net_profit'],2),'eligible',case['eligible'],flush=True)
 rows=original['matrix']+complete;passing=sorted([c for c in rows if c['kind']=='PORTFOLIO' and c['eligible']],key=lambda c:(c['full']['net_profit'],c['full']['profit_factor'] or 0),reverse=True);winner=passing[0] if passing else None
 data=dict(declaration=original['declaration'],supplement=definition,matrix=rows,cases=len(rows),requested_cases=40,supplemental_cases=16,eligible_portfolio_count=len(passing),winner=winner)
 suite.atomic(ROOT/'output/matrix.json',data);suite.atomic(ROOT/'output/selection.json',dict(winner_id=winner['id'] if winner else None,eligible_portfolio_count=len(passing),rule=original['declaration']['selection'],adaptive_supplement=True))
 if winner:
  config=suite.old.config_for(winner['strategy']);config['risk_and_exit'].update(risk_per_trade_pct=winner['risk'],max_open_positions=winner['max_open_positions'],max_margin_per_position_pct=.25,default_isolated_leverage=5);config['symbols']=[s.replace('USDT','/USDT:USDT') for s in suite.SYMBOLS];config['portfolio_risk']=dict(rank_by='BREAKOUT_DISTANCE',enforce_shared_margin=True);suite.atomic(ROOT/'output/winning_config.json',config)
 print('WINNER',winner['id'] if winner else None,flush=True)
if __name__=='__main__':main()
