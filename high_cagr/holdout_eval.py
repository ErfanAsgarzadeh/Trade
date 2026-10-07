"""One-shot holdout evaluation (predeclared_round2.json part C). Candidates are fixed; nothing is tuned here."""
from pathlib import Path
import sys,json,importlib
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs, fb_harness as fh
from high_cagr.kernel_fixes import simulate
from high_cagr.btc_regime_experiment import btc_inside_kumo
from high_cagr.stage2_experiment import frame
OUT=ROOT/'high_cagr/output'
HOLD=[c['symbol'] for c in json.loads((OUT/'stage3_selection.json').read_text())['chosen']]
def load():
    frames={s:frame(s) for s in HOLD+['BTCUSDT']};fk={(s,'4h','standard'):f for s,f in frames.items()}
    case=dict(symbols=HOLD,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=fh.RISK,max_open_positions=4)
    ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    inside=btc_inside_kumo(fk,ss.shape[1]);ss[:,inside,0]=0          # none of the holdout symbols is BTC
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    ix={s:(np.searchsorted(frames[s].timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]] for s in HOLD}
    side={s:ss[k,:,0].astype(int) for k,s in enumerate(HOLD)}
    return dict(frames=frames,ix=ix,side=side,sig=ss,bb=bb,step=step,prices=fh._stacked('prices','HOLD10',HOLD),funding=fh._stacked('funding','HOLD10',HOLD))
def candidates(ctx):
    c={'baseline':{}}
    sig=ctx['sig'].copy()
    for k,s in enumerate(HOLD):
        atr=ctx['frames'][s].atr.to_numpy()[ctx['ix'][s]];sd=sig[k,:,0];sig[k,:,2]=np.where(sd!=0,sig[k,:,1]-sd*2.5*atr,sig[k,:,2])
    c['initial_stop_2.5ATR']={'sig':sig}
    c['no_pyramid']={'kwargs':{'pyramid':False}}
    m=importlib.import_module('high_cagr.fb.m_confirmation');mk=m.mask_fn(ctx['frames'],ctx['ix'],ctx['side'],m.VARIANTS['B']);g=ctx['sig'].copy()
    for k,s in enumerate(HOLD):g[k,~np.asarray(mk[s],bool),0]=0
    c['confirmation_B']={'sig':g}
    return c
def run(ctx,c,bps,per):
    kw={**fh.POLICY,**c.get('kwargs',{})};pyr=kw.pop('pyramid',True);b,e=fh.PERIODS[per]
    a,t,curve=simulate(ctx['prices'],ctx['funding'],np.ascontiguousarray(c.get('sig',ctx['sig'])),ctx['bb'],rs.START,b,e,fh.RISK,4,ctx['step'],pyr,slip=bps/1e4,**kw)
    r=rs.summarize(a,t,curve,b,e,HOLD);return dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'])
def main():
    ctx=load();res={}
    for name,c in candidates(ctx).items():
        res[name]={f'{p}|{b}':run(ctx,c,b,p) for b in (2,5) for p in fh.PERIODS};f=res[name]['full|2']
        print(f"{name:22} CAGR {f['cagr']:6.2f} DD {f['dd']:6.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} | @5 {res[name]['full|5']['calmar']:.3f} | net H1 {res[name]['H1|2']['net']:.0f} H2 {res[name]['H2|2']['net']:.0f} 26 {res[name]['Y2026|2']['net']:.0f} | roots {f['roots']}",flush=True)
    B=res['baseline'];verd={}
    for n in res:
        if n=='baseline':continue
        x=res[n];ck={'calmar+0.05|2':x['full|2']['calmar']>=B['full|2']['calmar']+.05,'calmar+0.05|5':x['full|5']['calmar']>=B['full|5']['calmar']+.05,'positive_H1_H2_2026|2':all(x[f'{p}|2']['net']>0 for p in ('H1','H2','Y2026'))}
        verd[n]=dict(checks=ck,passed=all(ck.values()));print(n,'HOLDOUT PASS' if verd[n]['passed'] else 'HOLDOUT FAIL '+','.join(k for k,v in ck.items() if not v))
    (OUT/'holdout_results.json').write_text(json.dumps(dict(symbols=HOLD,results=res,verdicts=verd),indent=1))
if __name__=='__main__':main()
