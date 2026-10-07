"""Stage-1 experiment exactly as declared in output/predeclared_btc_regime.json."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
D=json.loads((ab.OUT/'predeclared_btc_regime.json').read_text())
def minute(date):return int((pd.Timestamp(date,tz='UTC').timestamp()*1000-rs.START)//60000)
PERIODS={k:(minute(a),minute(b)) for k,(a,b) in D['periods'].items()}
V2=dict(vol_mid_pct=.045,vol_mid_mult=.5,vol_max_pct=.056)

def btc_inside_kumo(frames,nbars):
    """True at entry bar b when BTC's last closed 4h close lies inside its 4h Kumo (same sampling as run_suite.inputs)."""
    step=240;boundaries=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    h=frames['BTCUSDT','4h','standard'];hi=np.searchsorted(h.timestamp.to_numpy(np.int64)+14400000,boundaries,side='right')-1;h=h.iloc[hi]
    inside=((h.close>=h.kumo_bottom)&(h.close<=h.kumo_top)).to_numpy();assert len(inside)<=nbars
    out=np.zeros(nbars,bool);out[:len(inside)]=inside;return out

def gate(ss,inside):
    g=ss.copy();btc=rs.SYMBOLS.index('BTCUSDT')
    for s in range(len(g)):
        if s!=btc:g[s,inside,0]=0
    return g

def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in rs.SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in rs.SYMBOLS]);frames=rs.load_frames()
    case,ss,bb,step=ab.build(.0075,frames);inside=btc_inside_kumo(frames,ss.shape[1]);gated=gate(ss,inside)
    btc=rs.SYMBOLS.index('BTCUSDT');assert (ss[btc,inside,0]==0).all()   # BTC never signals inside its own Kumo
    removed=int(((ss[:,:,0]!=0)&(gated[:,:,0]==0)).sum());print('BTC inside Kumo on',round(inside.mean()*100,1),'% of bars; alt signal-bars removed:',removed)
    policies={'4B (reference)':(ss,{}),'V2':(ss,V2),'B':(gated,{}),'V2+B':(gated,V2)};res={}
    for bps in D['slippage_bps_per_fill']:
        for name,(sig,extra) in policies.items():
            row={}
            for period,(b,e) in PERIODS.items():
                a,t,curve=simulate(prices,funding,sig,bb,rs.START,b,e,case['risk'],4,step,True,slip=bps/1e4,**ab.FIX4['4B'],**extra);r=rs.summarize(a,t,curve,b,e,case['symbols'])
                row[period]=dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'],adds=r['pyramid_adds'])
            res[f'{name}|{bps}']=row
    verdicts={}
    for bps in D['slippage_bps_per_fill']:
        ref=res[f'4B (reference)|{bps}']
        for name in policies:
            if name.startswith('4B'):continue
            r=res[f'{name}|{bps}'];f=r['full'];rf=ref['full']
            checks=dict(positive_H1_H2_2026=all(r[p]['net']>0 for p in ('H1','H2','Y2026')),calmar_up_0p05=f['calmar']>=rf['calmar']+.05,dd_lower=f['dd']<rf['dd'],
                        cagr_floor=bool(f['cagr']>=30 if bps==2 else f['cagr']>=.9*rf['cagr']),both_halves=all(r[p]['calmar']>=ref[p]['calmar'] for p in ('H1','H2')))
            verdicts[f'{name}|{bps}']=dict(checks=checks,accepted=all(checks.values()))
    (ab.OUT/'btc_regime_results.json').write_text(json.dumps(dict(results=res,verdicts=verdicts,btc_inside_pct=float(inside.mean()*100),removed_signal_bars=removed),indent=1,default=float))
    for bps in D['slippage_bps_per_fill']:
        print(f'--- {bps}bps/fill: full CAGR / DD / Calmar / PF | Calmar H1 H2 2026 | net H1 H2 2026 | roots adds | verdict')
        for name in policies:
            r=res[f'{name}|{bps}'];f=r['full'];v=verdicts.get(f'{name}|{bps}')
            print(f"{name:15}{f['cagr']:6.2f} {f['dd']:6.2f} {f['calmar']:.3f} {f['pf']:.3f} | {r['H1']['calmar']:.2f} {r['H2']['calmar']:.2f} {r['Y2026']['calmar']:.2f} | {r['H1']['net']:6.0f} {r['H2']['net']:6.0f} {r['Y2026']['net']:6.0f} | {f['roots']} {f['adds']} | "+('reference' if v is None else 'ACCEPTED' if v['accepted'] else 'REJECTED '+','.join(k for k,x in v['checks'].items() if not x)))
if __name__=='__main__':main()
