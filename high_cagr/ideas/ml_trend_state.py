"""What the in-trade model had NOT seen: the trend trade's own state. Pre-declared before any result was seen.
NEW STATE FEATURES (at each hourly state, causal):
  stop      distance to the bot's CURRENT protective stop in R (Ghoghnous: fixed stop; Mojsavar: max(initial 2 ATR, best 4h close
            - 4.5 ATR); Shahin: max(initial, 10-bar Donchian of closed 4h bars, +0.1R floor after a 1R excursion))
  maturity  hours since the 4h close crossed EMA50 in the trade direction; extension = side*(close-EMA50)/ATR; ATR now / at entry
  flow      taker buy share since entry and over the last 24h (signed) and their difference (divergence); OI change since entry
            and over the last 24h; funding paid since entry (signed, per 8h); volume of the last 24h vs the average since entry
  higher TF daily close vs daily EMA20 / EMA50 (signed, in daily vol units), 7-day return (signed), 30-day momentum rank
            across the 35 coins (side-adjusted)
  crowding  number of deployed positions open at that minute on the same side / on the opposite side
TARGETS: v_hold (R of holding vs exiting now), big = (final R - R now >= 2)
MODELS: gradient boosting (depth 5, 400 trees, lr 0.05, min leaf 200), pooled; and one per bot; both with OLD features only and
OLD + NEW (to measure what the new features add). Same purged walk-forward folds as ml_walkforward.py.
POLICIES (one action per position, from hour 4):
  tighten30  TIGHTEN when v_hold_hat is in the bottom 30% of training predictions
  protect    when unrealised R >= 1 and P(big)_hat is in the bottom 30% of training -> TIGHTEN (stop 0.5 R behind the close)
  cutloser   when unrealised R <= -0.3 and v_hold_hat is in the bottom 10% of training -> EXIT
  protect+cut both
Pass = Calmar above the current bots and DD not worse by > 2 pp in EVERY fold.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, live_monitor_study as LM, pabench as PB, ml_short as MS, criteria_lib as C
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
OUT=MD.OUT
NEW=['stop_R','trend_age','ext50','atr_ratio_e','tb_since','tb_24h','tb_div','oi_since','oi_24h','fund_since','vol_ratio','d_ema20','d_ema50','ret7d','mom30','crowd_same','crowd_opp']

def daily_panel():
    cl={s:PB._px(s)[1439::1440,3] for s in C.COINS};n=min(len(v) for v in cl.values());cl={s:v[:n] for s,v in cl.items()}
    r30=pd.DataFrame({s:np.log(v/np.concatenate([np.full(30,np.nan),v[:-30]])) for s,v in cl.items()});rk=r30.rank(axis=1,pct=True)
    return cl,rk

def add_new(S,L):
    dep=[l for l in L if not l['aug']];de=np.array([l['em'] for l in dep]);dx=np.array([l['xm'] for l in dep]);ds=np.array([l['side'] for l in dep])
    srt={s:(np.sort(de[ds==s]),np.sort(dx[ds==s])) for s in (1,-1)}
    cl,rk=daily_panel();out=np.full((len(S),len(NEW)),np.nan,np.float32)
    for j,g in S.groupby('leg').groups.items():
        l=L[j];s=l['side'];e=l['entry'];sd=e*l['stop_frac'];ix=np.asarray(g);ms=S.m.to_numpy()[ix];co=l['coin'];P=LM.px(co);c=P[ms,3]
        B=PB._bars(co);b4=(ms+1)//240-1;b0=l['em']//240;atr=B['atr'];e50=B['e50'];c4=B['c'];lo4=B['l'];hi4=B['h']
        init=e-s*sd
        if l['bot']=='pa':stop=np.full(len(ms),init)
        elif l['bot']=='c3':
            best=np.array([(c4[b0:k+1].max() if s>0 else c4[b0:k+1].min()) if k>=b0 else e for k in b4]);stop=np.where(s>0,np.maximum(init,best-4.5*atr[b4]),np.minimum(init,best+4.5*atr[b4]))
        else:
            don=np.array([lo4[max(k-9,0):k+1].min() if s>0 else hi4[max(k-9,0):k+1].max() for k in b4]);stop=np.where(s>0,np.maximum(init,don),np.minimum(init,don))
            seg=P[l['em']:,1] if s>0 else P[l['em']:,2]
            mfe=np.array([(P[l['em']:m+1,1].max()-e) if s>0 else (e-P[l['em']:m+1,2].min()) for m in ms])/sd
            fl=e+s*.1*sd;stop=np.where(mfe>=1,np.where(s>0,np.maximum(stop,fl),np.minimum(stop,fl)),stop)
        out[ix,0]=s*(c-stop)/sd
        side_ok=(s*(c4-e50)>0)
        age=np.zeros(len(ms))
        for i,k in enumerate(b4):
            kk=k
            while kk>0 and side_ok[kk] and k-kk<500:kk-=1
            age[i]=(k-kk)*4
        out[ix,1]=age;out[ix,2]=s*(c4[b4]-e50[b4])/atr[b4];out[ix,3]=atr[b4]/atr[max(b0-1,0)]
        tk=MD.taker1h(co);h=(ms+1)//60-1;h0=l['em']//60;ctb=np.cumsum(tk[0]);cv=np.cumsum(tk[1])
        def share(a,b):
            v=cv[b]-cv[np.maximum(a,0)];return np.where(v>0,(ctb[b]-ctb[np.maximum(a,0)])/np.maximum(v,1e-12)-.5,0.)
        tbs=s*share(np.full(len(h),h0),h);tb24=s*share(h-24,h);out[ix,4]=tbs;out[ix,5]=tb24;out[ix,6]=tb24-tbs
        oi=MS.base15(co)['oi'];q=(ms+1)//15-1;q0=l['em']//15;oq=oi[np.minimum(q,len(oi)-1)];out[ix,7]=oq/oi[min(q0,len(oi)-1)]-1;out[ix,8]=oq/oi[np.maximum(q-96,0)]-1
        f=LM.fc(co);out[ix,9]=s*(f[ms+1]-f[l['em']])/np.maximum((ms-l['em'])/480,1)*1e3
        v24=cv[h]-cv[np.maximum(h-24,0)];vall=(cv[h]-cv[max(h0,0)])/np.maximum(h-h0,1)*24;out[ix,10]=np.log((v24+1)/(vall+1))
        dc=cl[co];d=np.minimum((ms+1)//1440-1,len(dc)-1);ser=pd.Series(dc);e20=ser.ewm(span=20,adjust=False).mean().to_numpy();e5=ser.ewm(span=50,adjust=False).mean().to_numpy()
        dv=pd.Series(np.log(dc)).diff().rolling(30).std().to_numpy()+1e-9
        out[ix,11]=s*np.log(dc[d]/e20[d])/dv[d];out[ix,12]=s*np.log(dc[d]/e5[d])/dv[d];out[ix,13]=s*np.log(dc[d]/dc[np.maximum(d-7,0)])
        mr=rk[co].to_numpy()[d];out[ix,14]=np.where(s>0,mr,1-mr)
        a_,b_=srt[s];out[ix,15]=np.searchsorted(a_,ms,side='right')-np.searchsorted(b_,ms,side='right')-1
        a_,b_=srt[-s];out[ix,16]=np.searchsorted(a_,ms,side='right')-np.searchsorted(b_,ms,side='right')
    for i,nm in enumerate(NEW):S[nm]=out[:,i]
    return S

def main():
    t0=time.time();L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n]
    f=OUT/'states_trend.parquet'
    if f.exists():S=pd.read_parquet(f)
    else:
        S=pd.read_parquet(OUT/'states.parquet');S=S[S.hours>=4].reset_index(drop=True);S=add_new(S,L);S.to_parquet(f)
    print('states',len(S),'built',round(time.time()-t0),'s',flush=True)
    em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg];bot=np.array([l['bot'] for l in L]);S['bot']=bot[S.leg]
    old=[c for c in MD.FEATS if c in S.columns];allf=old+NEW
    yh=S.v_hold.clip(-3,10).to_numpy();yb=((S.v_hold)>=2).astype(int).to_numpy();P=lambda j,m:LM.px(L[j]['coin'])[m,3];res={}
    for fn,(a,b) in WF.FOLDS.items():
        tr=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy()
        base=WF.replay(dep,a,b);out={'base':base};print(f'fold {fn}: train {tr.sum()} test {te.sum()} | base final {base["final"]:,.0f} DD {base["dd"]:.1f} Calmar {base["calmar"]:.2f}',flush=True)
        rng=np.random.RandomState(0);tri=np.where(tr)[0];tri=np.sort(rng.choice(tri,min(len(tri),600000),replace=False))
        for fs_name,fs in (('old',old),('old+new',allf)):
            X=S[fs].astype(np.float32).replace([np.inf,-np.inf],np.nan).to_numpy();Xtr=X[tri];Xte=X[te]
            for mode in ('pooled','per_bot'):
                ph=np.zeros(te.sum());pb=np.zeros(te.sum());ph_tr=np.zeros(len(tri));pb_tr=np.zeros(len(tri))
                groups=[None] if mode=='pooled' else ['main','c3','pa']
                for g in groups:
                    mtr=np.ones(len(tri),bool) if g is None else (S.bot.to_numpy()[tri]==g);mte=np.ones(te.sum(),bool) if g is None else (S.bot.to_numpy()[te]==g)
                    rh=HistGradientBoostingRegressor(max_depth=5,max_iter=400,learning_rate=.05,min_samples_leaf=200,random_state=0).fit(Xtr[mtr],yh[tri][mtr])
                    cb=HistGradientBoostingClassifier(max_depth=5,max_iter=400,learning_rate=.05,min_samples_leaf=200,random_state=0).fit(Xtr[mtr],yb[tri][mtr])
                    ph[mte]=rh.predict(Xte[mte]);pb[mte]=cb.predict_proba(Xte[mte])[:,1];ph_tr[mtr]=rh.predict(Xtr[mtr]);pb_tr[mtr]=cb.predict_proba(Xtr[mtr])[:,1]
                St=S[te].copy();St['ph']=ph;St['pb']=pb;un=St.unreal_R.to_numpy()
                auc=float(roc_auc_score(yh[te]>0,ph));aucb=float(roc_auc_score(yb[te],pb));ic=float(spearmanr(ph,yh[te])[0]);o={'auc_hold':auc,'auc_big':aucb,'ic_hold':ic}
                q30=np.quantile(ph_tr,.3);q10=np.quantile(ph_tr,.1);b30=np.quantile(pb_tr,.3)
                pols={'tighten30':(ph<q30,'TIGHTEN'),'protect':((un>=1)&(pb<b30),'TIGHTEN'),'cutloser':((un<=-.3)&(ph<q10),'EXIT')}
                for pn,(act,kind) in pols.items():
                    St['kind']=kind;trig=WF.triggers(St,act,dep_n,P);r=WF.replay(WF.apply(dep,trig),a,b);r['acted']=len(trig);r['pass']=WF.judge(r,base);o[pn]=r
                kinds=np.where((un>=1)&(pb<b30),'TIGHTEN',np.where((un<=-.3)&(ph<q10),'EXIT','HOLD'));St['kind']=kinds
                trig=WF.triggers(St,kinds!='HOLD',dep_n,P);r=WF.replay(WF.apply(dep,trig),a,b);r['acted']=len(trig);r['pass']=WF.judge(r,base);o['protect+cut']=r
                out[f'{fs_name}|{mode}']=o
                print(f'  {fs_name:8s} {mode:8s} AUC hold {auc:.3f} big {aucb:.3f} IC {ic:+.3f} | '+' | '.join(f'{p} {o[p]["calmar"]:.1f}/{o[p]["dd"]:.0f}{"✓" if o[p]["pass"] else ""}' for p in ('tighten30','protect','cutloser','protect+cut')),flush=True)
        res[fn]=out;(OUT/'trend_state_walkforward.json').write_text(json.dumps(res,indent=1,default=float))
    print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
