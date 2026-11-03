"""Family 3: the two rules that passed (Mojsavar exit, Shahin late-entry gate) together, vs the shipped account;
plus a cost stress (every leg pays one extra round trip of fee+slippage = costs x2)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG, exits as E, run_rules as RR
def stressed(legs):return [dict(l,unit=l['unit']-2*l['entry']*(E.FEE+E.SLIP)) for l in legs]
def main():
    df=LG.build();legs=LG.raw_legs();thr=RR.thresholds(df);keep=RR.keep_mask(df,['main_late'],thr)
    c3x,_=E.modified_legs(legs,**RR.C3EXIT)
    V={'shipped':legs,'c3exit':c3x,'main_late':[l for l,k in zip(legs,keep) if k],'final':[l for l,k in zip(c3x,keep) if k]}
    res={}
    for name,L in V.items():
        for cost,LL in (('x1',L),('x2',stressed(L))):
            r=E.replay_legs(LL);st=E.account_stats(r);t=r['trades']
            st['by_bot']={b:dict(trades=int(len(g)),win=float((g.pnl>0).mean()*100),pnl=float(g.pnl.sum()),avg_win=float(g.pnl[g.pnl>0].mean()),avg_loss=float(g.pnl[g.pnl<=0].mean())) for b,g in t.groupby('bot')}
            res[f'{name}|{cost}']=st
            print(name,cost,f"WR {st['win_rate']['all']:.1f} (tr {st['win_rate']['train']:.1f} va {st['win_rate']['valid']:.1f}) main {st['win_rate']['main']:.1f} c3 {st['win_rate']['c3']:.1f} pa {st['win_rate']['pa']:.1f} | Calmar tr {st['train'][0]:.2f} va {st['valid'][0]:.2f} | CAGR {st['cagr']:.1f} DD {st['dd']:.1f} PF {st['pf']:.2f} | final {st['final']:,.0f} | yearly {st['yearly']}",flush=True)
            if cost=='x1':np.save(LG.OUT/f'daily_{name}.npy',r['daily'])
    (LG.OUT/'final.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
