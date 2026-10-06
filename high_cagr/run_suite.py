"""384 predeclared configurations, 3 independent periods, atomic resumable results."""
from pathlib import Path
import sys,json,itertools,time,concurrent.futures,threading,os,zipfile
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.kernel import simulate
START=int(pd.Timestamp('2021-10-05',tz='UTC').timestamp()*1000);END=int(pd.Timestamp('2026-10-05',tz='UTC').timestamp()*1000);SPLIT=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT'];PERIODS={'full':(0,(END-START)//60000),'train':(0,(SPLIT-START)//60000),'oos':((SPLIT-START)//60000,(END-START)//60000)}
OUT=ROOT/'high_cagr/output';LOCK=threading.Lock()
def atomic(p,obj):
 temp=p.with_suffix('.tmp');data=json.dumps(obj,indent=2,allow_nan=False)
 with temp.open('w') as f:f.write(data);f.flush();os.fsync(f.fileno())
 temp.replace(p)
 assert p.read_text()==data, 'Checkpoint read-back mismatch: '+str(p)
def grid():
 cases=[]
 for universe,preset,entry,trail,pyramid,risk,slots in itertools.product(['FIVE','ALTS'],['standard','crypto'],[('4h',10),('4h',15),('1h',20),('1h',40)],['DONCHIAN10','KIJUN'],[False,True],[.0075,.01,.0125],[4,5]):
  tf,n=entry;case=dict(universe=universe,preset=preset,entry_timeframe=tf,lookback=n,trail=trail,pyramid=pyramid,risk=risk,max_open_positions=slots,symbols=SYMBOLS if universe=='FIVE' else SYMBOLS[1:])
  case['id']=f'HC__{universe}__{preset}__{tf}__N{n}__{trail}__PY{int(pyramid)}__R{risk:g}__P{slots}';cases.append(case)
 return cases

def predeclare():
 declaration=dict(cases=grid(),periods={k:list(v) for k,v in PERIODS.items()},start_utc='2021-10-05T00:00:00Z',end_exclusive_utc='2026-10-05T00:00:00Z',split_utc='2025-01-01T00:00:00Z',
 selection='Full-period CAGR descending; >=40 root entries, positive Train and OOS net, max DD in ALL three periods <=35%; report stricter 25/30/35 tiers; no winner if none passes',
 entry='Prior N-bar Donchian close breakout on entry timeframe; last fully closed 4h price outside 4h Kumo; ATR2 safety stop; REJECT <1.2% at signal and actual slipped fill',
 trail='Closed entry-timeframe Donchian10 opposite extreme or Kijun ratchets a shared price stop, never loosens; no partial/BE/hard TP. Original close-only Kijun kept as control.',
 pyramid='Only one add per root: >=2R and stop favorable enough to cover entry fee/slippage allowance; eligible at an earlier timestamp; next same-direction Donchian breakout; half risk, same stop, REJECT <1.2% for add too; slot is a symbol, not a leg',
 costs='0.12% roundtrip fee, adverse 2bps each entry/exit, exact observed Binance funding through Sep2026, adverse 0.01% per 8h unknown Oct1-4; funding before new entries',
 sizing='0.04% slippage sizing allowance (not a duplicate debit), fixed 5x equivalent notional, 60% total reserved margin, slot budget 60%/slots, 0.0001 base-unit step/$5 min; 2% rolling 24h net realized exit loss pause',
 disclosure='BNB exclusion and this new search use past OOS observations; 2025-2026 is a validation slice, not untouched OOS. Minute OHLC path and shared phase ordering are approximations; no mark-price liquidation model.',
 target='50-100% CAGR aspirational only; all results reported and no thresholds relaxed after observation')
 p=OUT/'predeclared_grid.json';OUT.mkdir(parents=True,exist_ok=True)
 if p.exists():assert json.loads(p.read_text())==declaration
 else:atomic(p,declaration)
 return declaration

def load_frames():
 result={}
 for s in SYMBOLS:
  for tf,preset in itertools.product(['1h','4h'],['standard','crypto']):
   z=np.load(ROOT/'high_cagr/prepared'/s/f'{tf}_{preset}.npz');result[s,tf,preset]=pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))
 return result

def inputs(case,frames):
 tf=case['entry_timeframe'];step=60 if tf=='1h' else 240;preset=case['preset'];n=case['lookback'];boundaries=START+np.arange((END-START)//(step*60000)+1)*step*60000;ss=[];bb=[]
 for symbol in case['symbols']:
  f=frames[symbol,tf,preset];htf=frames[symbol,'4h',preset]
  ix=np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,boundaries,side='right')-1;hi=np.searchsorted(htf.timestamp.to_numpy(np.int64)+14400000,boundaries,side='right')-1
  assert ix.min()>=198 and hi.min()>=198
  e=f.iloc[ix];h=htf.iloc[hi];price=e.close.to_numpy();top=h.kumo_top.to_numpy();bottom=h.kumo_bottom.to_numpy();high=e[f'donchian_high_{n}'].to_numpy();low=e[f'donchian_low_{n}'].to_numpy()
  side=((h.close.to_numpy()>top)&(price>high)).astype(np.int64)-((h.close.to_numpy()<bottom)&(price<low)).astype(np.int64)
  # Stop fixed from the signal bar, as in the frozen benchmark's actual-fill logic.
  stop=price-side*2*e.atr.to_numpy()
  score=np.where(side==1,(price-np.maximum(high,top))/price,(np.minimum(low,bottom)-price)/price);score=np.where(side!=0,score,-np.inf)
  ss.append(np.column_stack([side,price,stop,score]))
  if case['trail']=='KIJUN':bb.append(np.column_stack([e.kijun,e.atr,price,e.kijun]))
  else:bb.append(e[['opposite_low_10','atr','close','opposite_high_10']].to_numpy())
 return np.stack(ss),np.stack(bb),step

def summarize(a,t,curve,begin,end,symbols):
 pnl=t[:,12];wins=pnl[pnl>0];loss=pnl[pnl<0];years=(end-begin)/525960
 assert abs(a[0]-10000-pnl.sum())<1e-6
 assert np.allclose(t[:,9]-t[:,10]+t[:,11],pnl,atol=1e-8) and np.all(t[:,7]/t[:,4]>=.012-1e-12)
 assert np.all(t[:,1]>=START+begin*60000) and np.all(t[:,2]<START+end*60000)
 return dict(trades=len(t),root_entries=int((t[:,18]==0).sum()),pyramid_adds=int(a[9]),net_profit=float(a[0]-10000),return_pct=float((a[0]/10000-1)*100),cagr_pct=float(((a[0]/10000)**(1/years)-1)*100) if a[0]>0 else -100.,profit_factor=float(wins.sum()/-loss.sum()) if len(loss) else None,max_dd_pct=float(a[1]*100),fees=float(t[:,10].sum()),funding_pnl=float(t[:,11].sum()),win_rate_pct=float(len(wins)/max(1,len(t))*100),min_stop_rejections=int(a[2]),slot_rejections=int(a[3]),margin_rejections=int(a[4]),missing_funding_proxy_events=int(a[5]),maximum_open_positions=int(a[6]),maximum_entry_margin_pct=float(a[7]*100),avg_margin_pct=float(a[10]*100),avg_margin_active_pct=float(a[11]*100),avg_open_positions=float(a[12]),per_symbol={s:dict(trades=int((t[:,0]==j).sum()),net_profit=float(pnl[t[:,0]==j].sum()),fees=float(t[t[:,0]==j,10].sum()),funding_pnl=float(t[t[:,0]==j,11].sum())) for j,s in enumerate(symbols)})

def run_case(case,prices,funding,frames):
 p=OUT/(case['id']+'.json');row=json.loads(p.read_text()) if p.exists() else dict(case)
 indices=np.array([SYMBOLS.index(s) for s in case['symbols']]);pp=prices if case['universe']=='FIVE' else prices[1:];ff=funding if case['universe']=='FIVE' else funding[1:]
 ss,bb,step=inputs(case,frames)
 for period,(begin,end) in PERIODS.items():
  if period in row:continue
  a,t,curve=simulate(pp,ff,ss,bb,START,begin,end,case['risk'],case['max_open_positions'],step,case['pyramid'])
  row[period]=summarize(a,t,curve,begin,end,case['symbols']);assert a[6]<=case['max_open_positions'] and a[7]<=.6+1e-8
  # Persist every unit's ledger for audit, without unused preallocated capacity.
  dest=OUT/(case['id']+'__'+period+'.npz');temp=dest.with_suffix('.tmp.npz')
  with temp.open('wb') as f:
   np.savez_compressed(f,trades=t,equity=curve,stats=a);f.flush();os.fsync(f.fileno())
  with zipfile.ZipFile(temp) as z:assert z.testzip() is None
  temp.replace(dest);atomic(p,row)
 row['positive_periods']=row['train']['net_profit']>0 and row['oos']['net_profit']>0
 row['worst_period_dd_pct']=max(row[k]['max_dd_pct'] for k in PERIODS)
 row['dd_tier']=next((limit for limit in [25,30,35] if row['worst_period_dd_pct']<=limit),None)
 row['eligible']=row['positive_periods'] and row['full']['root_entries']>=40 and row['dd_tier'] is not None
 atomic(p,row)
 with LOCK:print('DONE',case['id'],'CAGR',round(row['full']['cagr_pct'],2),'DD',round(row['worst_period_dd_pct'],2),'eligible',row['eligible'],flush=True)
 return row

def main():
 declaration=predeclare()
 # The committed aggregate is also a durable checkpoint on a fresh clone.
 if (OUT/'matrix.json').exists():
  saved=json.loads((OUT/'matrix.json').read_text())
  if saved.get('declaration')==declaration:
   for row in saved['matrix']:
    checkpoint=OUT/(row['id']+'.json')
    if not checkpoint.exists():atomic(checkpoint,row)
 prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy',mmap_mode='r') for s in SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy',mmap_mode='r') for s in SYMBOLS]);frames=load_frames()
 # Compile before threads; --workers lets the checkpointed workload resume.
 case=declaration['cases'][0];ss,bb,step=inputs(case,frames);simulate(prices[:,:2],funding[:,:2],ss,bb,START,0,2,case['risk'],case['max_open_positions'],step)
 workers=int(sys.argv[sys.argv.index('--workers')+1]) if '--workers' in sys.argv else 4
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
  futures=[pool.submit(run_case,c,prices,funding,frames) for c in declaration['cases']]
  for f in concurrent.futures.as_completed(futures):f.result()
 rows=[json.loads((OUT/(c['id']+'.json')).read_text()) for c in declaration['cases']];ranked=sorted(rows,key=lambda r:r['full']['cagr_pct'],reverse=True);eligible=[r for r in ranked if r['eligible']]
 result=dict(declaration=declaration,cases=len(rows),matrix=ranked,winner=eligible[0] if eligible else None,eligible_count=len(eligible),tier_winners={str(limit):next((r for r in eligible if r['worst_period_dd_pct']<=limit),None) for limit in [25,30,35]})
 atomic(OUT/'matrix.json',result);atomic(OUT/'selection.json',dict(winner_id=result['winner']['id'] if eligible else None,eligible_count=len(eligible),selection=declaration['selection']));print('SELECTED',result['winner']['id'] if eligible else None,flush=True)
if __name__=='__main__':main()
