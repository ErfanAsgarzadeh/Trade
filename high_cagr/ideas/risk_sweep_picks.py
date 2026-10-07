import sys;sys.path.insert(0,'/home/user/Trade')
import pandas as pd
from high_cagr.ideas import risk_sweep as R
P=pd.read_csv(R.OUT/'grid.csv')
def pick(kind,ddmax):
    q=P[(P.kind==kind)&(P.train_dd<=ddmax)];return q.sort_values('train_cagr',ascending=False).iloc[0]
res=[]
for kind in ('bot','c3','both'):
    for dd in (20,25,30,100):
        x=pick(kind,dd);res.append((kind,dd,x.bot,x.c3,x.train_cagr,x.train_dd,x.oos_cagr,x.oos_dd,x.full_cagr,x.full_dd,x.full_cal))
    x=P[P.kind==kind].sort_values('train_cal',ascending=False).iloc[0];res.append((kind,'maxCal',x.bot,x.c3,x.train_cagr,x.train_dd,x.oos_cagr,x.oos_dd,x.full_cagr,x.full_dd,x.full_cal))
T=pd.DataFrame(res,columns=['kind','rule','bot','c3','tr_cagr','tr_dd','va_cagr','va_dd','fu_cagr','fu_dd','fu_cal'])
T['peak_lev']=[R.notional(max(r.bot,1e-9) if r.bot else .0001,r.c3 if r.c3 else 1e-9)[2] for r in T.itertuples()]
print(T.round(3).to_string());T.to_csv(R.OUT/'picks.csv',index=False)
