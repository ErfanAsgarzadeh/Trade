"""Delta-neutral funding carry (PREDECLARED.md section 2): short perp + long Binance spot while recent funding is high.

Hourly grid from rs.START. Decision at the close of hour h from the funding prints of hours <= h; the position is open from
the close of h and earns every print in later hours. Unit notional per position: spot qty = 1/spot_entry, perp qty =
1/perp_entry (short). Hourly P&L = spot leg + perp leg + funding (rate x perp qty x perp close); costs on entry and exit.
Capital of a coin group = 1.2 x the most positions it ever had open at once (spot paid in full + 5x perp margin), so the
reported return is what the peak capacity would have earned (conservative when fewer positions are open).
"""
from pathlib import Path
import sys,json,itertools
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import pa_bot as PBOT
from high_cagr.ideas.chabok import research as RS
from high_cagr.ideas.winrate import prepare_ttt as PT, ledger as LG
OUT=ROOT/'high_cagr/output/ideas/fourth_bot';SPOT=ROOT/'high_cagr/prepared_spot';H=1826*24
PERP_COST=.0006+.0002;SPOT_COST=.001+.0002
GRID=[(k,ti,to) for k in (1,3,9) for ti in (.0001,.0002,.0003,.0005) for to in (0.,ti/2)]

def hourly(s):
    P=np.load(PBOT.prep_dir(s)/s/'prices.npy',mmap_mode='r');f=np.load(PBOT.prep_dir(s)/s/'funding.npy')
    pc=np.asarray(P[59::60,3][:H],np.float64);ev=np.isfinite(f[:H*60]).reshape(H,60);fr=np.nan_to_num(f[:H*60]).reshape(H,60).sum(1)
    sp=SPOT/f'{s}.npy';sc=np.load(sp)[:H] if sp.exists() else np.full(H,np.nan)
    return pc,sc,fr,ev.any(1)

@njit(cache=True)
def engine(pc,sc,fr,ev,start,K,th_in,th_out,perp_cost,spot_cost):
    n=len(pc);pnl=np.zeros(n);occ=np.zeros(n,np.int8);last=np.zeros(K);m=0;open_=False;qs=0.;qp=0.;trades=0;h=0
    while h<n-1:
        if ev[h]:
            for j in range(K-1):last[j]=last[j+1]
            last[K-1]=fr[h];m=min(m+1,K)
        mean=last[K-m:].mean() if m>0 else 0.
        if open_:
            ds=sc[h+1]-sc[h] if (sc[h+1]==sc[h+1] and sc[h]==sc[h]) else 0.
            pnl[h+1]+=qs*ds-qp*(pc[h+1]-pc[h])+fr[h+1]*qp*pc[h+1];occ[h+1]=1
            if mean<=th_out or not (sc[h+1]==sc[h+1]):
                pnl[h+1]-=perp_cost*qp*pc[h+1]+spot_cost*qs*(sc[h+1] if sc[h+1]==sc[h+1] else sc[h]);open_=False
        elif h>=start and m==K and mean>th_in and sc[h]==sc[h] and sc[h]>0:
            qs=1./sc[h];qp=1./pc[h];pnl[h]-=perp_cost+spot_cost;open_=True;trades+=1
            pnl[h+1]+=qs*((sc[h+1]-sc[h]) if sc[h+1]==sc[h+1] else 0.)-qp*(pc[h+1]-pc[h])+fr[h+1]*qp*pc[h+1];occ[h+1]=1
        h+=1
    return pnl,occ,trades

def main():
    OUT.mkdir(parents=True,exist_ok=True);A,B=RS.groups();gi={s:0 for s in A}|{s:1 for s in B}
    daily=np.zeros((2,2,len(GRID),1826));occ=np.zeros((2,len(GRID),H),np.int32);trades=np.zeros((2,len(GRID)),np.int64);cover={}
    for s in A+B:
        pc,sc,fr,ev=hourly(s);cover[s]=int(np.isfinite(sc).sum());g=gi[s];start=(PT.listed_min(s)+PT.WARMUP_DAYS*1440)//60
        if cover[s]==0:print(s,'no spot pair, skipped',flush=True);continue
        for ci,(K,ti,to) in enumerate(GRID):
            for cost,mult in ((0,1.),(1,2.)):
                p,o,nt=engine(pc,sc,fr,ev,start,K,ti,to,PERP_COST*mult,SPOT_COST*mult)
                daily[g,cost,ci]+=p.reshape(1826,24).sum(1)
                if cost==0:occ[g,ci]+=o;trades[g,ci]+=nt
        print(s,'done spot hours',cover[s],flush=True)
    cap=1.2*np.maximum(occ.max(2),1)   # group x config
    split=LG.SPLIT_MIN//1440;rows=[]
    for ci,(K,ti,to) in enumerate(GRID):
        r=dict(K=K,theta_in=ti,theta_out=to)
        for g,G in ((0,'A'),(1,'B')):
            for cost,tag in ((0,''),(1,'_x2')):
                d=daily[g,cost,ci]/cap[g,ci]
                for per,sl in (('train',slice(0,split)),('valid',slice(split,1826))):
                    x=d[sl];r[f'{G}_{per}_ann{tag}']=float(x.mean()*365*100);r[f'{G}_{per}_sharpe{tag}']=float(x.mean()/x.std()*np.sqrt(365)) if x.std()>0 else 0.
            r[f'{G}_max_positions']=int(cap[g,ci]/1.2);r[f'{G}_trades']=int(trades[g,ci])
        eq=np.cumsum((daily[0,0,ci]+daily[1,0,ci])/(cap[0,ci]+cap[1,ci]));r['AB_maxdd']=float((np.maximum.accumulate(np.r_[0,eq])-np.r_[0,eq]).max()*100)
        rows.append(r)
    df=pd.DataFrame(rows);df.to_csv(OUT/'carry_table.csv',index=False);i=int(df.A_train_sharpe.idxmax());r=df.loc[i]
    ok=all(r[f'{k}_ann']>3 and r[f'{k}_sharpe']>1 for k in ('A_valid','B_train','B_valid')) and r.B_train_ann_x2>0 and r.B_valid_ann_x2>0 and r.AB_maxdd<10
    pd.set_option('display.width',250);print(df.round(2).to_string());print('PICK',dict(r.round(3)),'PASSED',ok)
    (OUT/'carry_selection.json').write_text(json.dumps(dict(pick=int(i),row={k:float(v) for k,v in r.items()},passed=bool(ok),spot_coverage=cover),indent=1))
if __name__=='__main__':main()
