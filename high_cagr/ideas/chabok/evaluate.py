"""Apply the pre-declared selection and gates (PREDECLARED.md) to the grids written by research.py."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.chabok import research as RS
from high_cagr.ideas.winrate import ledger as LG
SPLIT_DAY=LG.SPLIT_MIN//1440;MIN_TRADES=300
YEARS=pd.date_range('2021-10-05',periods=RS.DAYS).year.to_numpy()

def cfg(i):
    (N,ur,ut),(sa,ta,mb,lk)=RS.SIG[i//len(RS.EXIT)],RS.EXIT[i%len(RS.EXIT)]
    return dict(N=N,rsi_band=ur,trend_filter=ut,stop_atr=sa,trail_atr=ta,max_bars=mb,profit_lock=lk)

def sharpe(x):
    s=x.std();return float(x.mean()/s*np.sqrt(365)) if s>0 else 0.

def table(tf):
    z=np.load(RS.OUT/f'grid_{tf}.npz');days,cnt,gp,gl,wins=z['days'],z['cnt'],z['gp'],z['gl'],z['wins']
    pf=lambda g,c,p:np.where(gl[g,c,:,p]>0,gp[g,c,:,p]/np.maximum(gl[g,c,:,p],1e-12),np.inf)
    tot=lambda g,c,p:gp[g,c,:,p]-gl[g,c,:,p]
    df=pd.DataFrame(dict(
        A_train_n=cnt[0,0,:,0],A_train_sharpe=[sharpe(days[0,0,i,:SPLIT_DAY]) for i in range(days.shape[2])],
        A_train_pf=pf(0,0,0),A_train_R=tot(0,0,0),A_train_win=wins[0,:,0]/np.maximum(cnt[0,0,:,0],1),
        A_valid_pf=pf(0,0,1),A_valid_R=tot(0,0,1),B_train_pf=pf(1,0,0),B_train_R=tot(1,0,0),B_valid_pf=pf(1,0,1),B_valid_R=tot(1,0,1),
        B_valid_win=wins[1,:,1]/np.maximum(cnt[1,0,:,1],1),B_train_pf_x2=pf(1,1,0),B_valid_pf_x2=pf(1,1,1),
        trades_per_year=cnt[:,0].sum(axis=(0,2))/5.))
    allR=days[0,0]+days[1,0];yr=pd.DataFrame(allR.T).groupby(YEARS).sum().T
    df['worst_year_R']=yr.min(axis=1).to_numpy();df['all_R']=allR.sum(1)
    return df,yr

def gates(r):
    c1=all(r[f'{k}_pf']>=1.1 and r[f'{k}_R']>0 for k in ('A_valid','B_train','B_valid'))
    c2=r.B_train_pf_x2>=1. and r.B_valid_pf_x2>=1.;c3=r.worst_year_R>=-10
    return dict(C1=bool(c1),C2=bool(c2),C3=bool(c3),passed=bool(c1 and c2 and c3))

def main():
    out={}
    for tf in RS.TFS:
        p=RS.OUT/f'grid_{tf}.npz'
        if not p.exists():continue
        df,yr=table(tf);elig=df[df.A_train_n>=MIN_TRADES]
        if not len(elig):out[tf]=dict(note='no configuration with enough trades');print(tf,'no eligible');continue
        i=int(elig.A_train_sharpe.idxmax());r=df.loc[i];g=gates(r)
        pos=dict(A_train=int((df.A_train_R>0).sum()),all_four_positive=int(((df.A_train_R>0)&(df.A_valid_R>0)&(df.B_train_R>0)&(df.B_valid_R>0)).sum()),configs=len(df))
        out[tf]=dict(selected=cfg(i),index=i,metrics={k:float(v) for k,v in r.items()},yearly_R={str(k):float(v) for k,v in yr.loc[i].items()},gates=g,counts=pos)
        print(f"{tf:4s} pick {cfg(i)}\n     A-train n {int(r.A_train_n)} sharpe {r.A_train_sharpe:.2f} PF {r.A_train_pf:.2f} WR {r.A_train_win*100:.1f}% | A-valid PF {r.A_valid_pf:.2f} R {r.A_valid_R:.0f} | B-train PF {r.B_train_pf:.2f} R {r.B_train_R:.0f} | B-valid PF {r.B_valid_pf:.2f} R {r.B_valid_R:.0f} WR {r.B_valid_win*100:.1f}% | x2 PF {r.B_train_pf_x2:.2f}/{r.B_valid_pf_x2:.2f} | worst year {r.worst_year_R:.0f}R | {g}\n     configs positive in all four cells: {pos['all_four_positive']}/{pos['configs']}",flush=True)
        df.to_csv(RS.OUT/f'table_{tf}.csv',index=False)
    (RS.OUT/'selection.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
