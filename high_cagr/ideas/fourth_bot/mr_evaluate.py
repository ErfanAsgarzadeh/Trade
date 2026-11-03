"""Pre-declared selection and gates (same as Chabok) on the mean-reversion grids."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.chabok import evaluate as EV, research as RS
from high_cagr.ideas.fourth_bot import mean_reversion as MR
def cfg(i):
    (en,fl),(sa,mb,ex)=MR.SIG[i//len(MR.EXIT)],MR.EXIT[i%len(MR.EXIT)];return dict(entry=en,filter=fl,stop_atr=sa,max_bars=mb,exit=ex)
def main():
    out={};EV.RS.OUT=MR.OUT;rows=[]
    for tf in MR.TFS:
        src=MR.OUT/f'mr_grid_{tf}.npz';dst=MR.OUT/f'grid_{tf}.npz'
        if not dst.exists():dst.symlink_to(src.name)
        df,yr=EV.table(tf);el=df[df.A_train_n>=EV.MIN_TRADES]
        allpos=int(((df.A_train_R>0)&(df.A_valid_R>0)&(df.B_train_R>0)&(df.B_valid_R>0)).sum())
        med={k:float(df[df.A_train_n>=50][k].replace(np.inf,np.nan).median()) for k in ('A_train_pf','B_valid_pf')}
        if not len(el):print(tf,'no eligible');continue
        i=int(el.A_train_sharpe.idxmax());r=df.loc[i];g=EV.gates(r)
        out[tf]=dict(selected=cfg(i),metrics={k:float(v) for k,v in r.items()},gates=g,all_four_positive=allpos,configs=len(df),median=med,
                     spearman_train_vs_B_valid=float(df.A_train_pf.rank().corr(df.B_valid_pf.rank())))
        print(f"{tf:4s} pick {cfg(i)}\n     A-train n {int(r.A_train_n)} PF {r.A_train_pf:.2f} WR {r.A_train_win*100:.1f}% | A-valid PF {r.A_valid_pf:.2f} | B-train PF {r.B_train_pf:.2f} | B-valid PF {r.B_valid_pf:.2f} WR {r.B_valid_win*100:.1f}% | x2 {r.B_train_pf_x2:.2f}/{r.B_valid_pf_x2:.2f} | worst yr {r.worst_year_R:.0f}R | {g}\n     all-four-positive {allpos}/{len(df)} | median PF train {med['A_train_pf']:.2f} B-valid {med['B_valid_pf']:.2f} | spearman {out[tf]['spearman_train_vs_B_valid']:.2f}",flush=True)
        df.to_csv(MR.OUT/f'mr_table_{tf}.csv',index=False);dst.unlink()
    (MR.OUT/'mr_selection.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
