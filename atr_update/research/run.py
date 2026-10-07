from pathlib import Path
import sys,json,zipfile,time
import numpy as np,pandas as pd
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'source'))
from high_cagr.run_suite import inputs,summarize,PERIODS,START,SYMBOLS
from kernel import simulate
OUT=BASE/'output';OUT.mkdir(exist_ok=True)
ref=next(r for r in json.loads((BASE/'source/high_cagr/output/matrix.json').read_text())['matrix'] if r['id']=='HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4')
frames={}
for s in SYMBOLS:
 z=np.load(BASE/'source/high_cagr/prepared'/s/'4h_standard.npz');frames[s,'4h','standard']=pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))
prices=np.stack([np.load(BASE/'source/high_cagr/prepared'/s/'prices.npy') for s in SYMBOLS]);fund=np.stack([np.load(BASE/'source/high_cagr/prepared'/s/'funding.npy') for s in SYMBOLS]);ss,bb,step=inputs(ref,frames)
results={}
for label,buffer in [('before',0.),('after',.25)]:
 results[label]={}
 for period,(begin,end) in PERIODS.items():
  checkpoint=OUT/f'{label}_{period}.json';dest=OUT/f'{label}_{period}.npz'
  if checkpoint.exists() and dest.exists():m=json.loads(checkpoint.read_text())
  else:
   a,t,curve=simulate(prices,fund,ss,bb,START,begin,end,.0075,4,240,True,trail_atr_buffer=buffer)
   m=summarize(a,t,curve,begin,end,SYMBOLS);m['calmar']=m['cagr_pct']/m['max_dd_pct']
   np.savez_compressed(dest,trades=t,equity=curve,stats=a)
   with zipfile.ZipFile(dest) as z:assert z.testzip() is None
   checkpoint.write_text(json.dumps(m,indent=2))
  if label=='before':
   for k in ['net_profit','cagr_pct','max_dd_pct','fees','funding_pnl','trades','root_entries','pyramid_adds']:
    assert np.isclose(m[k],ref[period][k],rtol=1e-10,atol=1e-7),(period,k,m[k],ref[period][k])
  results[label][period]=m
  print(label,period,'CAGR',m['cagr_pct'],'DD',m['max_dd_pct'],'NET',m['net_profit'],flush=True)
(OUT/'comparison.json').write_text(json.dumps(results,indent=2))
print('ALL BASELINE PARITY CHECKS PASSED',flush=True)
