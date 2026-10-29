"""Independent check of the Shahin 'late entry' rule on coins Shahin never traded: 2A+5A (xuni.bot_daily, unchanged
logic) on the 30 coins of Mojsavar/Ghoghnous, with and without the rule. The threshold is FROZEN from the five Shahin
coins' TRAIN period (rules.json, side x ln(close/close[-60]) on the last closed 4h bar > 0.1521 -> no root entry)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import xuni as X
from high_cagr.ideas.winrate import ledger as LG, fetch30 as F
THR=json.loads((LG.OUT/'rules.json').read_text())['thresholds']['main_late']

def run(symbols,rule):
    frames={s:X.frame(s) for s in symbols};prices=np.stack([np.load(X.PREP/s/'prices.npy') for s in symbols]);funding=np.stack([np.load(X.PREP/s/'funding.npy') for s in symbols])
    days=prices.shape[1]//1440
    case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=.0075,max_open_positions=4)
    fk={(s,'4h','standard'):frames[s] for s in symbols};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;blocked=0
    for j,s in enumerate(symbols):
        f=frames[s];ix=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
        ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix];low=~(ar>=1.)&(ss[j,:,0]!=0);ss[j,low,0]=0;ss[j,low,3]=-np.inf
        if rule:
            c=f.close.to_numpy();r60=np.log(c/np.roll(c,60));r60[:60]=np.nan;late=(ss[j,:,0]*r60[ix]>THR)&(ss[j,:,0]!=0)
            blocked+=int(late.sum());ss[j,late,0]=0;ss[j,late,3]=-np.inf
    a,t,curve=simulate(prices,funding,np.ascontiguousarray(ss),np.ascontiguousarray(bb),rs.START,0,(rs.END-rs.START)//60000,.0075,4,step,True,slip=2e-4,floor_on=True,floor_trigger=1.,floor_lock=.1)
    r=X.daily_from_curve(curve,days);st=X.stats(r);t=t[t[:,2]>0];split=rs.START+X.SPLIT*86400000
    win=lambda m:float((t[m,12]>0).mean()*100)
    return dict(full=st['full'],train=st['train'],valid=st['oos'],legs=int(len(t)),win=win(np.ones(len(t),bool)),win_train=win(t[:,1]<split),win_valid=win(t[:,1]>=split),blocked_signals=blocked)

def main():
    res={}
    for name,syms in (('xuni10',X.NEW),('all30',F.COINS)):
        for rule in (False,True):
            r=run(syms,rule);res[f'{name}|{"late_rule" if rule else "base"}']=r
            print(name,'rule' if rule else 'base',f"WR {r['win']:.1f} (tr {r['win_train']:.1f} va {r['win_valid']:.1f}) | Calmar full {r['full'][0]:.2f} tr {r['train'][0]:.2f} va {r['valid'][0]:.2f} | CAGR {r['full'][1]:.1f} DD {r['full'][2]:.1f} | legs {r['legs']} blocked {r['blocked_signals']}",flush=True)
    (LG.OUT/'oos30_late_rule.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
