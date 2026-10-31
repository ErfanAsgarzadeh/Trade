"""Win-rate study: walk-forward AI entry gate (XGBoost, the model of high_cagr/ml_trade_filter.py) for ALL THREE bots.

Label: the leg is a winner (net R > 0). Features: the causal entry features of ledger.py (coin 4h bar, BTC regime,
funding, time, open-leg counts, the bot's recent closed results) plus the bot as one-hot. One pooled model.
Walk-forward by calendar year (test 2023, 2024, 2025, 2026): the model is trained on legs whose EXIT is at least
14 days before the test year; the drop fraction q (share of a bot's lowest-scored root entries to skip) is chosen per bot
on the PREVIOUS year only (inner model trained on legs exited 14 days before that year), maximising the kept net R
(expectancy-preserving), so no test-year outcome enters any choice. A dropped root also drops its pyramid adds.
"""
from pathlib import Path
import sys
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG
EMBARGO=14*1440;YEARS=(2023,2024,2025,2026);QS=(0.,.1,.2,.3,.4)
START=pd.Timestamp('2021-10-05')
def ymin(y):return int((pd.Timestamp(f'{y}-01-01')-START).total_seconds()//60)
PORT=['n_open','n_same_side','coin_busy','bot_wr10','all_r20','last_coin_R']

def features(df,groups=None):
    cols=[c for c in df.columns if c.startswith('f_')]+PORT
    if groups:cols=[c for c in cols if any(c.startswith(g) or c==g for g in groups)]
    X=df[cols].astype(float).copy()
    for b in ('main','c3','pa'):X['bot_'+b]=(df.bot==b).astype(float)
    return X

def model(seed=71):
    from xgboost import XGBClassifier
    return XGBClassifier(n_estimators=200,max_depth=3,learning_rate=.03,subsample=.8,colsample_bytree=.8,min_child_weight=10,
                         reg_lambda=5.,tree_method='hist',n_jobs=4,random_state=seed,eval_metric='logloss')

def fit_predict(X,y,tr,ap,seed=71):
    m=model(seed);m.fit(X[tr],y[tr]);return m.predict_proba(X[ap])[:,1],m

def choose_q(df,score,mask):
    """Per bot, the drop fraction maximising kept net R on the rows in mask (roots only)."""
    out={}
    for b in ('main','c3','pa'):
        mb=mask&(df.bot.to_numpy()==b)&~df.is_add.to_numpy()
        if mb.sum()<20:out[b]=0.;continue
        s=score[mb];R=df.R.to_numpy()[mb];best,bq=R.sum(),0.
        for q in QS[1:]:
            k=R[s>=np.quantile(s,q)].sum()
            if k>best:best,bq=k,q
        out[b]=bq
    return out

def walk_forward(df,groups=None,seed=71,fixed_q=None):
    """Returns (score per leg (nan outside tests), keep mask over legs, per-year info)."""
    X=features(df,groups).to_numpy();y=df.win.to_numpy();em=df.em.to_numpy();xm=df.xm.to_numpy();roots=df.root.to_numpy()
    isroot=~df.is_add.to_numpy();score=np.full(len(df),np.nan);keep=np.ones(len(df),bool);info={}
    for Y in YEARS:
        a,bnd=ymin(Y),ymin(Y+1);test=(em>=a)&(em<bnd)
        tr=(xm<a-EMBARGO)&isroot
        p,_=fit_predict(X,y,tr,test&isroot,seed);score[test&isroot]=p
        va=(em>=ymin(Y-1))&(em<a);itr=(xm<ymin(Y-1)-EMBARGO)&isroot
        pv,_=fit_predict(X,y,itr,va&isroot,seed);sv=np.full(len(df),np.nan);sv[va&isroot]=pv
        q=choose_q(df,sv,va&isroot) if fixed_q is None else dict(fixed_q)
        for b in ('main','c3','pa'):
            mb=test&isroot&(df.bot.to_numpy()==b);vb=va&isroot&(df.bot.to_numpy()==b)
            if q[b]>0 and mb.sum() and vb.sum():
                # threshold = q-quantile of the previous year's (out-of-sample) scores of this bot
                thr=np.quantile(sv[vb],q[b]);keep[mb&(score<thr)]=False
        info[Y]=dict(train_roots=int(tr.sum()),q=q)
    dropped=set(roots[~keep])
    keep&=~np.isin(roots,list(dropped))   # adds follow their root
    return score,keep,info

def auc(y,s):
    from sklearn.metrics import roc_auc_score
    m=np.isfinite(s);return float(roc_auc_score(y[m],s[m])) if m.sum()>20 and len(np.unique(y[m]))==2 else np.nan
