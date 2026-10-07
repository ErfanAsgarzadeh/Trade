"""Execution-stress and resampling checks for the deployed policy (4B) vs the old baseline.
Slippage is per fill (entry and exit). Fees, funding and the 4bps sizing allowance stay as in the benchmark."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
POLICIES={'baseline':{},'4B (deployed)':ab.FIX4['4B']};SLIPS_BPS=[2,5,10,15];RNG=np.random.default_rng(20261006)

def ledger_R(t,risk):
    roots=t[t[:,18]==0];pnl=np.array([t[t[:,17]==k,12].sum() for k in roots[:,17]]);return roots[:,1],pnl/(roots[:,14]*risk)

def monthly_returns(curve):
    c=curve[np.isfinite(curve[:,1])];months=((c[:,0]-rs.START)//(30.4375*86400000)).astype(int);last=np.array([c[months==m][-1,1] for m in np.unique(months)])
    return np.diff(np.r_[10000.,last])/np.r_[10000.,last][:-1]

def block_bootstrap(returns,block=3,n=5000):
    L=len(returns);out=[]
    for _ in range(n):
        idx=np.concatenate([(s+np.arange(block))%L for s in RNG.integers(0,L,int(np.ceil(L/block)))])[:L];r=returns[idx];eq=np.cumprod(1+r);peak=np.maximum.accumulate(np.r_[1.,eq])[1:]
        out.append((eq[-1]**(12/L)-1,((peak-eq)/peak).max()))
    return np.array(out)

def month_cluster_R(ts,R,n=5000):
    m=((ts-rs.START)//(30.4375*86400000)).astype(int);groups=[R[m==k] for k in np.unique(m)];means=[];pfs=[]
    for _ in range(n):
        x=np.concatenate([groups[i] for i in RNG.integers(0,len(groups),len(groups))]);means.append(x.mean());pfs.append(x[x>0].sum()/-x[x<0].sum())
    return np.percentile(means,[2.5,50,97.5]),np.percentile(pfs,[2.5,50,97.5])

def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in rs.SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in rs.SYMBOLS]);frames=rs.load_frames()
    case,ss,bb,step=ab.build(.0075,frames);result=dict(slippage={},bootstrap={})
    for name,policy in POLICIES.items():
        for bps in SLIPS_BPS:
            row={}
            for period,(b,e) in rs.PERIODS.items():
                a,t,curve=simulate(prices,funding,ss,bb,rs.START,b,e,case['risk'],4,step,True,slip=bps/1e4,**policy);r=rs.summarize(a,t,curve,b,e,case['symbols']);row[period]=dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'])
            result['slippage'][f'{name}|{bps}']=row
            print(f"{name:14} slip {bps:2}bps | full CAGR {row['full']['cagr']:6.2f} DD {row['full']['dd']:5.2f} PF {row['full']['pf']:.3f} | train {row['train']['cagr']:6.2f} | val {row['oos']['cagr']:6.2f}",flush=True)
        a,t,curve=simulate(prices,funding,ss,bb,rs.START,0,rs.PERIODS['full'][1],case['risk'],4,step,True,**policy)
        ts,R=ledger_R(t,case['risk']);mean_ci,pf_ci=month_cluster_R(ts,R);boot=block_bootstrap(monthly_returns(curve))
        result['bootstrap'][name]=dict(mean_R=float(R.mean()),mean_R_ci=mean_ci.tolist(),pf_R=float(R[R>0].sum()/-R[R<0].sum()),pf_R_ci=pf_ci.tolist(),
            cagr_ci=(np.percentile(boot[:,0],[2.5,50,97.5])*100).tolist(),maxdd_ci=(np.percentile(boot[:,1],[5,50,95])*100).tolist(),p_cagr_negative=float((boot[:,0]<0).mean()),p_dd_over_40=float((boot[:,1]>.40).mean()),p_dd_over_50=float((boot[:,1]>.50).mean()))
        b_=result['bootstrap'][name];print(f"{name:14} bootstrap | mean R {b_['mean_R']:.3f} CI95 {b_['mean_R_ci'][0]:.3f}..{b_['mean_R_ci'][2]:.3f} | PF(R) {b_['pf_R']:.2f} CI {b_['pf_R_ci'][0]:.2f}..{b_['pf_R_ci'][2]:.2f} | CAGR CI95 {b_['cagr_ci'][0]:.1f}..{b_['cagr_ci'][2]:.1f}% | DD 5-95% {b_['maxdd_ci'][0]:.0f}..{b_['maxdd_ci'][2]:.0f}% | P(DD>40%) {b_['p_dd_over_40']:.2f} P(DD>50%) {b_['p_dd_over_50']:.2f} P(CAGR<0) {b_['p_cagr_negative']:.3f}",flush=True)
    (ab.OUT/'robustness.json').write_text(json.dumps(result,indent=1))
if __name__=='__main__':main()
