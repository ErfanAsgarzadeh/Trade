"""Frozen top-four strategies, shared equity; atomic checkpoints per completed period."""
from pathlib import Path
import sys,json,copy,importlib.util
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'archetypes'));sys.path.insert(0,str(ROOT.parent/'lbank_project'))
import run_suite as old, strategy_archetypes as shared
sys.path.insert(0,str(ROOT.parent))
from portfolio.kernel import simulate
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','ADAUSDT']
START=old.START;END=old.END;SPLIT=old.SPLIT
PERIODS={'full':(0,(END-START)//60000),'train':(0,(SPLIT-START)//60000),'oos':((SPLIT-START)//60000,(END-START)//60000)}
def atomic(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,allow_nan=False));temp.replace(path)
def predeclare():
 m=json.loads((ROOT.parent/'archetypes/output/matrix.json').read_text())
 top=sorted([x for x in m['matrix'] if x['family']=='DONCHIAN' and x['mode']=='SINGLE' and x['eligible']],key=lambda x:(x['full']['net_profit'],x['full']['profit_factor'] or 0),reverse=True)[:4]
 cases=[]
 for x in top:
  strategy={k:x[k] for k in ['id','family','mode','setting','entry','exit','stop','trail','h2','lookback']}
  scenarios=[('BTC_REFERENCE',.005,.5,1)]+[('BTC_SCALED',r,1.5,1) for r in [.01,.015,.02]]+[('PORTFOLIO',r,1.25,n) for r in [.0075,.01,.015] for n in [3,4]]
  for kind,risk,cap,slots in scenarios:cases.append(dict(id=f"{x['id']}__{kind}__R{risk:g}__P{slots}",strategy=strategy,kind=kind,risk=risk,notional_cap=cap,max_open_positions=slots,symbols=SYMBOLS if kind=='PORTFOLIO' else SYMBOLS[:1]))
 declaration=dict(start_utc='2021-10-05T00:00:00Z',end_exclusive_utc='2026-10-05T00:00:00Z',split_utc='2025-01-01T00:00:00Z',cases=cases,selection='Highest full net portfolio profit, full trades>=40, positive train/oos net and DD<=25% in all three periods; PF tie-break; retain prior config if none',ranking='Descending percent Close beyond the stricter Donchian/Kumo boundary; symbol input order on tie',quantity_model='Frozen 0.0001 base-unit step, $5 minimum; historical exchange filters unavailable',risk_model='Shared MTM equity; reserved initial margin <= equity; 5x leverage; 2% rolling 24h realized exit loss pause',costs='0.12% roundtrip fees, adverse 2bps each fill, observed funding through Sep2026, adverse 0.01% per 8h proxy Oct1-4')
 path=ROOT/'output/predeclared_grid.json'
 if path.exists():assert json.loads(path.read_text())==declaration
 else:atomic(path,declaration)
 return declaration

def frames_for(symbol):
 result={}
 for setting in ['standard','crypto']:
  d=np.load(ROOT/'prepared'/symbol/(setting+'.npz'));result[setting]=pd.DataFrame(d['data'],columns=json.loads(str(d['columns'])))
 return result

def inputs(strategy,frames):
 c=old.config_for(strategy);f=frames[strategy['setting']];boundaries=START+np.arange((END-START)//14400000+1)*14400000
 ix=np.searchsorted(f.timestamp.to_numpy(np.int64)+14400000,boundaries,side='right')-1;assert ix.min()>=198
 selected=f.iloc[ix].reset_index(drop=True);long,short=shared.entry_masks(f,c);side=long.to_numpy(np.int64)[ix]-short.to_numpy(np.int64)[ix]
 stop=selected.kijun.to_numpy() if strategy['stop']=='KIJUN' else selected.close.to_numpy()-side*2*selected.atr.to_numpy()
 n=strategy['lookback'];upper=np.maximum(selected[f'donchian_high_{n}'],selected.kumo_top);lower=np.minimum(selected[f'donchian_low_{n}'],selected.kumo_bottom)
 score=np.where(side==1,(selected.close-upper)/selected.close,(lower-selected.close)/selected.close);score=np.where(side!=0,score,-np.inf)
 sig=np.column_stack([side,selected.close,stop,score])
 bars=selected[['opposite_low_10','atr','close','opposite_high_10']].to_numpy() if strategy['trail']=='DONCHIAN10' else np.column_stack([selected.kijun,selected.atr,selected.close,selected.kijun])
 return sig,bars

def summarize(a,t,begin,end,symbols):
 pnl=t[:,12];win=pnl[pnl>0];loss=pnl[pnl<0]
 assert abs(a[0]-10000-pnl.sum())<1e-6 and np.allclose(t[:,9]-t[:,10]+t[:,11],pnl,atol=1e-8)
 assert np.all(t[:,1]<=t[:,2]) and np.all(t[:,7]/t[:,4]>=.012-1e-12)
 years=(end-begin)/525960
 return dict(trades=len(t),net_profit=float(a[0]-10000),return_pct=float((a[0]/10000-1)*100),cagr_pct=float(((a[0]/10000)**(1/years)-1)*100) if a[0]>0 else -100.,profit_factor=float(win.sum()/-loss.sum()) if len(loss) else None,max_dd_pct=float(a[1]*100),fees=float(t[:,10].sum()),funding_pnl=float(t[:,11].sum()),gross_pnl=float(t[:,9].sum()),win_rate_pct=float(len(win)/len(t)*100) if len(t) else 0.,avg_win=float(win.mean()) if len(win) else 0.,avg_loss=float(loss.mean()) if len(loss) else 0.,min_stop_rejections=int(a[2]),slot_rejections=int(a[3]),margin_rejections=int(a[4]),missing_funding_proxy_events=int(a[5]),maximum_open_positions=int(a[6]),maximum_entry_margin_pct=float(a[7]*100),maximum_entry_notional_pct=float(a[8]*100),per_symbol={s:dict(trades=int((t[:,0]==j).sum()),net_profit=float(pnl[t[:,0]==j].sum()),fees=float(t[t[:,0]==j,10].sum()),funding_pnl=float(t[t[:,0]==j,11].sum())) for j,s in enumerate(symbols)})

def verify_reference():
 declaration=predeclare();prices,funding,frames=old.load_features();prior={x['id']:x for x in json.loads((ROOT.parent/'archetypes/output/matrix.json').read_text())['matrix']};checks=[]
 for case in [x for x in declaration['cases'] if x['kind']=='BTC_REFERENCE']:
  s,b=inputs(case['strategy'],{name:frames['SINGLE',name] for name in ['standard','crypto']})
  a,t,c=simulate(prices[None],funding[None],s[None],b[None],START,0,len(prices),.005,.5,1,case['strategy']['exit']=='CLOSE_TRAIL')
  summary=summarize(a,t,0,len(prices),['BTCUSDT']);expected=prior[case['strategy']['id']]['full']
  for key in ['trades','net_profit','max_dd_pct','fees','funding_pnl']:np.testing.assert_allclose(summary[key],expected[key],rtol=1e-10,atol=1e-7,err_msg=key)
  checks.append(dict(id=case['id'],summary=summary,passed=True));print('REFERENCE PASS',case['id'],flush=True)
 atomic(ROOT/'output/reference_verification.json',checks)

def main():
 declaration=predeclare();prices=np.stack([np.load(ROOT/'prepared'/s/'prices.npy',mmap_mode='r') for s in SYMBOLS]);funding=np.stack([np.load(ROOT/'prepared'/s/'funding.npy',mmap_mode='r') for s in SYMBOLS]);frames=[frames_for(s) for s in SYMBOLS]
 for index,definition in enumerate(declaration['cases'],1):
  checkpoint=ROOT/'output'/(definition['id']+'.json')
  case=json.loads(checkpoint.read_text()) if checkpoint.exists() else copy.deepcopy(definition)
  ns=len(case['symbols']);sb=[inputs(case['strategy'],f) for f in frames[:ns]];signals=np.stack([x[0] for x in sb]);bars=np.stack([x[1] for x in sb])
  for period,(begin,end) in PERIODS.items():
   if period in case:continue
   a,t,curve=simulate(prices[:ns],funding[:ns],signals,bars,START,begin,end,case['risk'],case['notional_cap'],case['max_open_positions'],case['strategy']['exit']=='CLOSE_TRAIL')
   case[period]=summarize(a,t,begin,end,case['symbols']);assert a[6]<=case['max_open_positions'] and a[7]<=1+1e-8
   np.savez_compressed(ROOT/'output'/(case['id']+'__'+period+'.npz'),trades=t,equity=curve,stats=a);atomic(checkpoint,case)
   print(index,period,'net',round(case[period]['net_profit'],2),'DD',round(case[period]['max_dd_pct'],2),flush=True)
  case['eligible']=case['full']['trades']>=40 and case['train']['net_profit']>0 and case['oos']['net_profit']>0 and all(case[p]['max_dd_pct']<=25 for p in PERIODS);atomic(checkpoint,case)
  done=[json.loads(p.read_text()) for p in (ROOT/'output').glob('DONCHIAN*.json')];atomic(ROOT/'output/matrix.json',dict(declaration=declaration,matrix=done))
 rows=[json.loads((ROOT/'output'/(c['id']+'.json')).read_text()) for c in declaration['cases']];passing=sorted([x for x in rows if x['kind']=='PORTFOLIO' and x['eligible']],key=lambda x:(x['full']['net_profit'],x['full']['profit_factor'] or 0),reverse=True);winner=passing[0] if passing else None
 result=dict(declaration=declaration,matrix=rows,cases=len(rows),eligible_portfolio_count=len(passing),winner=winner);atomic(ROOT/'output/matrix.json',result);atomic(ROOT/'output/selection.json',dict(winner_id=winner['id'] if winner else None,eligible_portfolio_count=len(passing),rule=declaration['selection']))
 if winner:
  c=old.config_for(winner['strategy']);c['risk_and_exit'].update(risk_per_trade_pct=winner['risk'],max_open_positions=winner['max_open_positions'],max_margin_per_position_pct=.25,default_isolated_leverage=5);c['symbols']=[s.replace('USDT','/USDT:USDT') for s in SYMBOLS];c['portfolio_risk']=dict(rank_by='BREAKOUT_DISTANCE',enforce_shared_margin=True);atomic(ROOT/'output/winning_config.json',c)
 print('WINNER',winner['id'] if winner else None,flush=True)
if __name__=='__main__':
 if '--verify-reference' in sys.argv:verify_reference()
 else:main()
