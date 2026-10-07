"""Stage-2 tests exactly as declared in output/predeclared_stage2_universe.json."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
from high_cagr.btc_regime_experiment import PERIODS,V2,btc_inside_kumo
OUT=ROOT/'high_cagr/output';OLD=rs.SYMBOLS
NEW=[c['symbol'] for c in json.loads((OUT/'stage2_selection.json').read_text())['chosen']]
def folder(s):return ROOT/('high_cagr/prepared' if s in OLD else 'high_cagr/prepared_stage2')/s
def frame(s):
    z=np.load(folder(s)/'4h_standard.npz');return pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))
def build(symbols,frames,slots):
    case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.0075,max_open_positions=slots)
    ss,bb,step=rs.inputs(case,frames);bb=np.concatenate([bb,ab.channel_columns(case,frames)],axis=2)
    prices=np.stack([np.load(folder(s)/'prices.npy',mmap_mode='r') for s in symbols]);funding=np.stack([np.load(folder(s)/'funding.npy',mmap_mode='r') for s in symbols])
    return case,ss,bb,step,np.ascontiguousarray(prices),np.ascontiguousarray(funding)
def gate(ss,symbols,inside):
    g=ss.copy()
    for k,s in enumerate(symbols):
        if s!='BTCUSDT':g[k,inside,0]=0
    return g
def run(case,sig,bb,step,prices,funding,extra,bps):
    row={}
    for period,(b,e) in PERIODS.items():
        a,t,curve=simulate(prices,funding,sig,bb,rs.START,b,e,case['risk'],case['max_open_positions'],step,True,slip=bps/1e4,**ab.FIX4['4B'],**extra);r=rs.summarize(a,t,curve,b,e,case['symbols'])
        assert a[6]<=case['max_open_positions'] and a[7]<=.6+1e-8
        row[period]=dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'])
    return row
def main():
    frames={}
    for s in OLD+NEW:frames[s,'4h','standard']=frame(s)
    inside=None;res={};verd={}
    for bps in (2,5):
        for label,symbols,slots,pols in [('OLD5',OLD,4,['REF']),('NEW10',NEW,4,['REF','V2','B','V2+B']),('ALL15',OLD+NEW,4,['REF','V2','V2+B']),('ALL15',OLD+NEW,6,['REF','V2','V2+B'])]:
            case,ss,bb,step,prices,funding=build(symbols,frames,slots)
            if inside is None:inside=btc_inside_kumo({('BTCUSDT','4h','standard'):frames['BTCUSDT','4h','standard']},ss.shape[1])
            for pol in pols:
                sig=gate(ss,symbols,inside) if 'B' in pol.split('+') else ss;extra=V2 if 'V2' in pol else {}
                key=f'{label}|P{slots}|{pol}|{bps}';res[key]=run(case,sig,bb,step,prices,funding,extra,bps);f=res[key]['full']
                print(f"{key:24} CAGR {f['cagr']:6.2f} DD {f['dd']:6.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} | Calmar H1 {res[key]['H1']['calmar']:.2f} H2 {res[key]['H2']['calmar']:.2f} 26 {res[key]['Y2026']['calmar']:.2f} | net {res[key]['H1']['net']:6.0f} {res[key]['H2']['net']:6.0f} {res[key]['Y2026']['net']:6.0f} | roots {f['roots']}",flush=True)
        ref=res[f'NEW10|P4|REF|{bps}']
        for pol in ['V2','B','V2+B']:
            r=res[f'NEW10|P4|{pol}|{bps}'];f,rf=r['full'],ref['full']
            c=dict(positive=all(r[p]['net']>0 for p in ('H1','H2','Y2026')),calmar=f['calmar']>=rf['calmar']+.05,dd=f['dd']<=rf['dd'],cagr=f['cagr']>=.9*rf['cagr'],both_halves=all(r[p]['calmar']>=ref[p]['calmar'] for p in ('H1','H2')))
            verd[f'T1|{pol}|{bps}']=dict(checks=c,generalises=all(c.values()))
        old=res[f'OLD5|P4|REF|{bps}']
        for slots in (4,6):
            for pol in ['REF','V2','V2+B']:
                r=res[f'ALL15|P{slots}|{pol}|{bps}'];c=dict(positive=all(r[p]['net']>0 for p in ('H1','H2','Y2026')),calmar=r['full']['calmar']>=old['full']['calmar']+.05)
                verd[f'T2|P{slots}|{pol}|{bps}']=dict(checks=c,helps=all(c.values()))
    (OUT/'stage2_results.json').write_text(json.dumps(dict(new_symbols=NEW,results=res,verdicts=verd),indent=1,default=float))
    for k,v in verd.items():print(k,'PASS' if v.get('generalises',v.get('helps')) else 'FAIL '+','.join(x for x,ok in v['checks'].items() if not ok))
if __name__=='__main__':main()
