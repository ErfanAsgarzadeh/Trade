"""Idea 3 (pre-declared, high_cagr/ideas/predeclared.json '3_time_stop'):
exit at a 4h close if root MFE < 0.5R after N bars. A: N=3 (12h), B: N=6 (24h).
Uses kernel_fixes.simulate switches time_stop_bars / time_stop_mfe; signals and trail bars unchanged.

Extra analysis (no new variants): for every baseline root position, reconstruct its root MFE (in R) at the moment the
time stop would be checked (entry boundary + N*4h), from the 1m prices with the same rule as the kernel
(favourable = sign*(extreme - entry)/dist, max over minutes since entry). Counts how many baseline big winners
(net/risk_usd >= 3) would have been cut (still open at the check AND MFE < 0.5R). Path effects (freed slots,
different later entries) are ignored -- this is a first-order estimate.
"""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench

VARIANTS={'A':dict(time_stop_bars=3,time_stop_mfe=.5),'B':dict(time_stop_bars=6,time_stop_mfe=.5)}

def build(ctx,variant):return {'kwargs':dict(variant)}

def big_winner_cut_estimate():
    ctx=bench.load();(a,t,curve),b,e=bench._sim({},'full',2);rs=bench.rs;step=ctx['step'];prices=ctx['prices']
    roots=t[(t[:,18]==0)&(t[:,1]>0)];out={}
    rows=[]
    for r in roots:
        legs=t[t[:,17]==r[17]];net=float(legs[:,12].sum());R=net/float(r[15])
        s=int(r[0]);sign=r[3];entry=r[4];dist=r[7];open_ts=int(r[1])-3000;i0=(open_ts-rs.START)//60000;exit_ts=int(r[2])
        rows.append((s,sign,entry,dist,open_ts,i0,exit_ts,R,net))
    for v,var in VARIANTS.items():
        N=var['time_stop_bars'];thr=var['time_stop_mfe'];cut=[];cut_all=0
        for s,sign,entry,dist,open_ts,i0,exit_ts,R,net in rows:
            check_ts=open_ts+N*step*60000
            if exit_ts<=check_ts:continue  # closed before (or at) the check: unaffected
            seg=prices[s,i0:i0+N*step]
            ext=seg[:,1].max() if sign==1 else seg[:,2].min()
            mfe=max(0.,sign*(ext-entry)/dist)
            if mfe<thr:
                cut_all+=1
                if R>=3:cut.append(dict(symbol=bench.SYMBOLS[s],entry_ts=int(open_ts+3000),net_R=round(R,2),net=round(net,2),mfe_at_check=round(mfe,3)))
        big=sum(1 for x in rows if x[7]>=3)
        out[v]=dict(roots=len(rows),cut_roots=cut_all,big_winners=big,big_winners_cut=len(cut),big_winner_net_cut=float(sum(c['net'] for c in cut)),cut_list=cut)
        print(f"{v}: roots {len(rows)} would-be-cut {cut_all}; big winners (>=3R) {big}, cut {len(cut)} (net {out[v]['big_winner_net_cut']:.0f})",flush=True)
    return out

if __name__=='__main__':
    notes=('Time stop: at each 4h boundary exit if bars since root open >= N and root MFE < 0.5R (kernel reason 10, counted '
           'in chop_exits). A N=3 (12h), B N=6 (24h). Signals/bars unchanged, so causal by construction.')
    out=bench.run_idea('idea3_time_stop',VARIANTS,build,notes=notes)
    est=big_winner_cut_estimate()
    p=bench.OUT/'idea3_time_stop.json';d=json.loads(p.read_text());d['big_winner_cut_estimate']=est;p.write_text(json.dumps(d,indent=1,default=float))
