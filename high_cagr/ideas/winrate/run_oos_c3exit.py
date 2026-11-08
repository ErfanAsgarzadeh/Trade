"""Independent check of the Mojsavar exit rule (lock 1R->+0.1R, half at 2R) on the 20 coins Mojsavar never traded
(c3bench OTHER20) (and on its own ten coins for reference): Mojsavar legs built exactly like three_bots_replay, replayed alone."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import c3bench_d as BD, c3r2_a4_sizing as S, three_bots_replay as TB
from high_cagr.ideas.winrate import ledger as LG, exits as E
C3EXIT=dict(bots=('c3',),pfrac=.5,ptarget=2.,arm=1.,lock=.1)
def legs_for(coins):
    out=[]
    for s in coins:
        d=BD.B.coin(s);le,se=BD.confirm_signals(d);m=np.ones(d['n'])
        T=S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],m,m,.0006,.0002,d['fb'],300)
        for i,r in enumerate(T):
            e,x=int(r[0]),int(r[1])
            out.append(dict(bot='c3',coin=s,side=int(r[2]),em=e*240,xm=min(x*240+239,TB.DAYS*1440-1),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                            stop_frac=float(2*d['atr'][e-1]/r[6]),risk_scale=1.,root=('c3',s,i),is_add=False))
    return out
def main():
    res={}
    for name,coins in (('other20',BD.B.OTHER20),('main10',BD.B.MAIN10)):
        L=legs_for(coins)
        for v,LL in (('base',L),('c3exit',E.modified_legs(L,**C3EXIT)[0])):
            r=E.account_stats(E.replay_legs(LL,bots=('c3',)));res[f'{name}|{v}']=r
            print(name,v,f"WR {r['win_rate']['all']:.1f} (tr {r['win_rate']['train']:.1f} va {r['win_rate']['valid']:.1f}) | Calmar tr {r['train'][0]:.2f} va {r['valid'][0]:.2f} | CAGR {r['cagr']:.1f} DD {r['dd']:.1f} PF {r['pf']:.2f} | legs {r['trades']}",flush=True)
    (LG.OUT/'oos_c3exit.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
