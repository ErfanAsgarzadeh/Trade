import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np,pandas as pd,warnings;warnings.filterwarnings('ignore')
from high_cagr.ideas import nontrend_lab as NL, ml_walkforward as WF
P=NL.panel();lc,r=P['lc'],P['r'];vol=pd.DataFrame(r).rolling(60).std().to_numpy();rev=-(lc-np.vstack([np.full((6,lc.shape[1]),np.nan),lc[:-6]]))/(vol*np.sqrt(6)+1e-12)
fscore=-pd.DataFrame(P['frate']).rolling(18).mean().to_numpy()
for fn in ('2023','2024'):
    a=WF.FOLDS[fn][0]//240;b=WF.FOLDS[fn][1]//240
    W={'PAIRS_L360_Z2.5':NL.pairs_weights(360,2.5,a,b),'PAIRS_L540_Z2.0':NL.pairs_weights(540,2.,a,b),'FUNDSPR_K18_N5':NL.rank_weights(fscore,18,5,a,b),'FUNDMOM_K18_N5':NL.rank_weights(-fscore,18,5,a,b),
       'XREV_N5':NL.rank_weights(rev,6,5,a,b),'XMOM_K18_N5':NL.rank_weights(-rev,18,5,a,b)}
    for k,Wt in W.items():
        row=[]
        for side in (.0008,.0002,0.):
            NL.SIDE=side;d=NL.run_weights(Wt,a,b);row.append(f'{(d[-1]/1e4-1)*100:+6.1f}%')
        turn=np.abs(np.diff(Wt[a:b],axis=0)).sum()/((b-a)/6/365);print(fn,f'{k:16s} taker {row[0]} | maker {row[1]} | zero cost {row[2]} | turnover {turn:,.0f}x equity/yr',flush=True)
