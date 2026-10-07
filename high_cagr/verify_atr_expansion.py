"""Independent check of ChatGPT's ATR_EXPANSION filter: ATR[t] >= mult * median(ATR[t-W .. t-1]) on closed 4h bars,
applied to root entries and pyramid adds (signal mask). Reproduction, sensitivity surface, and untouched symbols."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs, fb_harness as fh
from high_cagr.kernel_fixes import simulate
from high_cagr.btc_regime_experiment import btc_inside_kumo
from high_cagr.stage2_experiment import OLD,NEW,frame
HOLD=[c['symbol'] for c in json.loads((ROOT/'high_cagr/output/stage3_selection.json').read_text())['chosen']]
V2=dict(vol_mid_pct=.045,vol_mid_mult=.5,vol_max_pct=.056)
def universe(symbols,name):
    frames={s:frame(s) for s in set(symbols)|{'BTCUSDT'}};fk={(s,'4h','standard'):f for s,f in frames.items()}
    case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.0075,max_open_positions=4)
    ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    ix={s:(np.searchsorted(frames[s].timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]] for s in symbols}
    inside=btc_inside_kumo(fk,ss.shape[1])
    return dict(symbols=symbols,frames=frames,ss=ss,bb=bb,step=step,ix=ix,inside=inside,prices=fh._stacked('prices',name,symbols),funding=fh._stacked('funding',name,symbols))
def atr_mask(U,W,mult):
    out=[]
    for s in U['symbols']:
        a=U['frames'][s].atr;med=a.rolling(W).median().shift(1).to_numpy();v=a.to_numpy();i=U['ix'][s]
        out.append((v[i]>=mult*med[i])&np.isfinite(med[i]))
    return np.stack(out)
def run(U,mask=None,btc_gate=False,extra=None,slots=4,periods=('full','H1','H2','Y2026'),bps=2):
    g=U['ss'].copy()
    if mask is not None:g[~mask,0]=0
    if btc_gate:
        for k,s in enumerate(U['symbols']):
            if s!='BTCUSDT':g[k,U['inside'],0]=0
    out={}
    for per in periods:
        b,e=fh.PERIODS[per];a,t,c=simulate(U['prices'],U['funding'],g,U['bb'],rs.START,b,e,.0075,slots,U['step'],True,slip=bps/1e4,**ab.FIX4['4B'],**(extra or {}))
        r=rs.summarize(a,t,c,b,e,U['symbols']);out[per]=dict(cagr=r['cagr_pct'],dd=r['max_dd_pct'],calmar=r['cagr_pct']/r['max_dd_pct'],net=r['net_profit'],roots=r['root_entries'])
    return out
