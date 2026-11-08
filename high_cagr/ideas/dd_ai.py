"""Drawdown study, stage 2: AI regime model ('when should the whole account trade smaller / larger').
Pre-declared before running. Daily features at the close of day d, all LBank-feasible and known at that close:
  market   BTC return 1/3/7/14/30 d, BTC daily vol 7/30 d, BTC distance to 50/200-day mean, share of the 35 coins above their
           20/50-day mean, mean and dispersion of 7-day coin returns, mean correlation of coins with the equal-weight index (30 d),
           mean 3-day funding across coins, Fear & Greed (+7-day change), stablecoin supply growth (30 d)
  system   reference account (three bots, constant risk, no filters) return 5/10/30 d, its drawdown from peak, its 20-day vol;
           open positions long / short, open profit in R (sum over open legs of side*(close-entry)/(entry*stop)), its 5-day change
Targets: (reg) reference-account return over the next 10 days; (clf) next-10-day reference return < -3%.
Models: gradient boosting (depth 3, 200 trees, lr 0.03, min leaf 40) + ridge, rank-averaged. Training: STRICT walk-forward for
2023 / 2024 / 2025-26 (only days whose 10-day target ended before the test period); 2022 has no past, so it is trained on
2023-2026 with a 30-day purge on both sides (combinatorial purged CV) and is labelled as such.
Per-bot variant (argument main / c3 / pa): the reference account and the open-position features use that bot's legs only.
Output: daily percentile p of the score vs. the training scores -> multipliers used by dd_lab2.py.
"""
import sys,json,pickle,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, three_bots_replay as TB, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM, dd_lab as DL
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
OUT=ROOT/'high_cagr/prepared/dd_ai.pkl';H=10;D=E.DAYS

def features(dep=None):
    dep=DL.DEP if dep is None else dep;ref=E.replay(dep)['daily'];rr=np.r_[0,ref[1:]/ref[:-1]-1]
    ends=(np.arange(D)+1)*1440-1;cl={s:TB.closes(s)[np.minimum(ends,len(TB.closes(s))-1)] for s in C.COINS}
    P=pd.DataFrame(cl);R=P.pct_change();b=P['BTCUSDT'];f=pd.DataFrame(index=range(D))
    for k in (1,3,7,14,30):f[f'btc_r{k}']=b.pct_change(k)
    br=b.pct_change();f['btc_v7']=br.rolling(7).std();f['btc_v30']=br.rolling(30).std();f['btc_m50']=b/b.rolling(50).mean()-1;f['btc_m200']=b/b.rolling(200,min_periods=100).mean()-1
    f['above20']=(P>P.rolling(20).mean()).mean(1);f['above50']=(P>P.rolling(50).mean()).mean(1);r7=P.pct_change(7);f['r7_mean']=r7.mean(1);f['r7_disp']=r7.std(1)
    idx=R.mean(1);f['corr30']=pd.concat([R[c].rolling(30).corr(idx) for c in R],axis=1).mean(1)
    fu=[];
    for s in C.COINS:
        fc=LM.fc(s);m=np.minimum(ends,len(fc)-1);m3=np.maximum(m-3*1440,0);fu.append(fc[m]-fc[m3])
    f['fund3']=np.nanmean(np.array(fu),0)
    dm=SL.daily_market();bi=np.minimum((np.arange(D)+1)*6-1,len(dm['fng'])-1);f['fng']=dm['fng'][bi];f['fng_chg7']=dm['fng_chg7'][bi];f['stable_g30']=dm['stable_g30'][bi]
    rs=pd.Series(rr);f['sys_r5']=rs.rolling(5).sum();f['sys_r10']=rs.rolling(10).sum();f['sys_r30']=rs.rolling(30).sum();f['sys_dd']=ref/np.maximum.accumulate(ref)-1;f['sys_v20']=rs.rolling(20).std()
    nl=np.zeros(D);ns=np.zeros(D);oR=np.zeros(D)
    for l in dep:
        d0=l['em']//1440;d1=min(l['xm']//1440,D)
        if d1<=d0:continue
        dd=np.arange(d0,d1);(nl if l['side']>0 else ns)[dd]+=1;px=cl[l['coin']][dd];oR[dd]+=l['side']*(px-l['entry'])/(l['entry']*l['stop_frac'])
    f['open_long']=nl;f['open_short']=ns;f['open_R']=oR;f['open_R_chg5']=pd.Series(oR).diff(5)
    y=pd.Series(rr).rolling(H).sum().shift(-H).to_numpy();return f.replace([np.inf,-np.inf],np.nan),y

def fit_predict(X,y,tr,te):
    med=X[tr].median();A=X.fillna(med).to_numpy();ok=tr&np.isfinite(y);out={}
    g=HistGradientBoostingRegressor(max_depth=3,max_iter=200,learning_rate=.03,min_samples_leaf=40,random_state=0).fit(A[ok],y[ok])
    r=make_pipeline(StandardScaler(),Ridge(alpha=30.)).fit(A[ok],y[ok]);yc=(y[ok]<-.03).astype(int)
    gc=HistGradientBoostingClassifier(max_depth=3,max_iter=200,learning_rate=.03,min_samples_leaf=40,random_state=0).fit(A[ok],yc)
    lc=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=2000)).fit(A[ok],yc)
    def pct(ptr,p):s=np.sort(ptr);return np.searchsorted(s,p,side='right')/len(s)
    for nm,(m,sign,kind) in {'gbm':(g,1,'r'),'ridge':(r,1,'r'),'gbm_clf':(gc,-1,'c'),'log_clf':(lc,-1,'c')}.items():
        p=(m.predict(A) if kind=='r' else m.predict_proba(A)[:,1])*sign;out[nm]=pct(p[ok],p)
    out['ens']=pct((out['gbm']+out['ridge'])[ok],out['gbm']+out['ridge']);out['ens_all']=pct(sum(out[k] for k in ('gbm','ridge','gbm_clf','log_clf'))[ok],sum(out[k] for k in ('gbm','ridge','gbm_clf','log_clf')))
    return {k:v[te] for k,v in out.items()}

def main(bot=None):
    X,y=features(None if bot is None else [l for l in DL.DEP if l['bot']==bot]);days=np.arange(D);res={};diag={}
    for fn,(a,b) in DL.PER.items():
        a0=a//1440;b0=(b//1440) if b else D;te=(days>=a0)&(days<b0)
        tr=(days+H<a0) if fn!='2022' else ((days>b0+30)|(days+H<a0-30))
        tr&=days>=60;o=fit_predict(X,y,tr,te);res[fn]=dict(days=days[te],**o)
        yt=y[te];m=np.isfinite(yt);diag[fn]={k:float(np.corrcoef(v[m],yt[m])[0,1]) for k,v in o.items()}
        print(fn,'train days',int(tr.sum()),'corr(score, next-10d return):',{k:round(v,3) for k,v in diag[fn].items()},flush=True)
    tag='' if bot is None else '_'+bot
    OUT.with_name(f'dd_ai{tag}.pkl').write_bytes(pickle.dumps(res));(ROOT/'high_cagr/output/ideas/dd_lab').mkdir(parents=True,exist_ok=True);(ROOT/f'high_cagr/output/ideas/dd_lab/ai_diag{tag}.json').write_text(json.dumps(diag,indent=1))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else None)
