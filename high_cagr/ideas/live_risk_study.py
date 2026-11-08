"""In-trade RISK scaling by the live score, pre-declared before any number of it was looked at.
Score = the in-trade state model of live_monitor_study.py (logistic on 48 criteria + unrealised R, excursion, give-back, bars held, ATR
change; fit on TRAIN legs only; percentile from TRAIN out-of-fold states). At every 4h close of an open position (from bar 2):
  score below LO  (first time)  -> CUT: close a fraction of the position (risk goes down)
  score above HI  (first time)  -> ADD: open an extra piece of mult x the original size at that close (risk goes up)
Each of the two reactions happens at most once per position; a later cut shrinks every piece that is open. Added pieces keep
the original exit logic (exit time and price), costs as the bots: 0.06% fee per side, 2 bps slippage, funding.
SCENARIOS (fixed now, all three bots together): cut30 (cut 50% below 30th pct), add70 (+50% above 70th pct), both30_70 (both),
both20_80, both_add100 (cut 50% / add +100%, 30/70), cut_all (cut 100% = exit below 30th, +50% above 70th).
PER BOT (only that bot's positions are scaled): both30_70 and both_add100. Judged on TEST 2025-01..2026-10; 2024 shown for information.
Accept rule as before: Calmar > current AND max DD not worse than current + 2 pp. Margin cap (80%) and sizing are the replay engine's.
"""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import live_monitor_study as LM, win_prob_model as W, five_year_report as FY
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/live_risk';FEE=LM.FEE;SLIP=LM.SLIP

def piece_unit(l,e,m_in,xp,m_out):
    s=l['side'];f=LM.fc(l['coin']);return s*(xp-e)-(e+xp)*FEE-s*e*(f[m_out+1]-f[m_in])
def orig_exit_price(l):
    s=l['side'];e=l['entry'];f=LM.fc(l['coin']);fd=f[l['xm']+1]-f[l['em']]
    return (l['unit']+s*e+e*FEE+s*e*fd)/(s-FEE)

def build_legs(L,sts,pct_by_leg,lo,hi,cut,mult,bots,use_cut=True,use_add=True):
    out=[];nc=na=0
    for j,l in enumerate(L):
        if l['bot'] not in bots or j not in sts:out.append(l);continue
        s=l['side'];xp0=orig_exit_price(l);pieces=[dict(scale=1.,e=l['entry'],m_in=l['em'],first=True)];segs=[];ucut=uadd=False
        for st,p in zip(sts[j],pct_by_leg[j]):
            if st['k']<2:continue
            if use_cut and not ucut and p<lo:
                ucut=True;nc+=1;xp=st['close']*(1-s*SLIP)
                for pc in pieces:
                    segs.append(dict(scale=pc['scale']*cut,e=pc['e'],m_in=pc['m_in'],m_out=st['m'],xp=xp,first=pc['first']));pc['scale']*=(1-cut)
                pieces=[pc for pc in pieces if pc['scale']>1e-9]
            elif use_add and not uadd and p>hi:
                uadd=True;na+=1;pieces.append(dict(scale=mult,e=st['close']*(1+s*SLIP),m_in=st['m']+1,first=False))
            if not pieces:break
        for pc in pieces:segs.append(dict(scale=pc['scale'],e=pc['e'],m_in=pc['m_in'],m_out=l['xm'],xp=xp0,first=pc['first']))
        for g in segs:
            first=g['first'];out.append(dict(l,entry=g['e'],em=l['em'] if first else g['m_in'],xm=g['m_out'],unit=piece_unit(l,g['e'],g['m_in'],g['xp'],g['m_out']),
                                             risk_scale=l['risk_scale']*g['scale'],is_add=l['is_add'] or not first))
    return out,nc,na

def metrics(legs,start,end=None):
    r=W.run_period(legs,[1.]*len(legs),start,end);r.pop('daily');return r
def judge(r,b):return r['calmar']>b['calmar'] and r['dd']>=b['dd']-2

def main():
    OUT.mkdir(parents=True,exist_ok=True);L=FY.ledgers('soft');X,M=LM.build(L);em=M.em.to_numpy();tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START
    y=(M.future>0).astype(int).to_numpy();Xf=X.fillna(X[tr].median());A=Xf.to_numpy();grp=M.leg.to_numpy();idx=np.where(tr)[0]
    mkm=lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=3000));oof=np.zeros(len(M))
    for a,b in GroupKFold(5).split(idx,groups=grp[idx]):oof[idx[b]]=mkm().fit(A[idx[a]],y[idx[a]]).predict_proba(A[idx[b]])[:,1]
    p=mkm().fit(A[tr],y[tr]).predict_proba(A)[:,1];p[tr]=oof[tr];pct=np.searchsorted(np.sort(oof[tr]),p,side='right')/tr.sum()
    pct=np.searchsorted(np.sort(oof[tr]),p,side='right')/len(oof[tr])
    print('state AUC train/2024/test',round(roc_auc_score(y[tr],oof[tr]),3),round(roc_auc_score(y[gap],p[gap]),3),round(roc_auc_score(y[te],p[te]),3),flush=True)
    sts={};pbl={}
    for j,l in enumerate(L):sts[j]=LM.states(l)
    # align score rows to states (build() iterates legs and states in the same order)
    k=0
    for j in range(len(L)):
        n=len(sts[j]);pbl[j]=pct[k:k+n];k+=n
    assert k==len(pct)
    base_t=metrics(L,W.TEST_START);base_g=metrics(L,W.TRAIN_END,W.TEST_START);res={'base':dict(test=base_t,y2024=base_g),'runs':{}}
    print('current bots: TEST final',round(base_t['final']),'DD',round(base_t['dd'],1),'Calmar',round(base_t['calmar'],2),'| 2024 DD',round(base_g['dd'],1),'Calmar',round(base_g['calmar'],2),flush=True)
    ALL=('main','c3','pa')
    runs={'cut30':dict(lo=.3,hi=2,cut=.5,mult=0,bots=ALL,use_add=False),'add70':dict(lo=-1,hi=.7,cut=0,mult=.5,bots=ALL,use_cut=False),
          'both30_70':dict(lo=.3,hi=.7,cut=.5,mult=.5,bots=ALL),'both20_80':dict(lo=.2,hi=.8,cut=.5,mult=.5,bots=ALL),
          'both_add100':dict(lo=.3,hi=.7,cut=.5,mult=1.,bots=ALL),'cut_all':dict(lo=.3,hi=.7,cut=1.,mult=.5,bots=ALL)}
    for b in ALL:
        runs[f'bot_{b}_both30_70']=dict(lo=.3,hi=.7,cut=.5,mult=.5,bots=(b,));runs[f'bot_{b}_both_add100']=dict(lo=.3,hi=.7,cut=.5,mult=1.,bots=(b,))
    for name,kw in runs.items():
        Lm,nc,na=build_legs(L,sts,pbl,**kw);out={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():out[per]=metrics(Lm,a,b)
        out['cuts']=nc;out['adds']=na;res['runs'][name]=out;t=out['test'];g=out['y2024']
        print(f"{name:22s} TEST final {t['final']:>9,.0f} DD {t['dd']:6.1f} Calmar {t['calmar']:5.2f} {'PASS' if judge(t,base_t) else '    '} | 2024 DD {g['dd']:6.1f} Calmar {g['calmar']:5.2f} {'PASS' if judge(g,base_g) else '    '} | cuts {nc} adds {na}",flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
    # curves for the report
    np.save(OUT/'daily_base.npy',W.run_period(L,[1.]*len(L),W.TEST_START)['daily'])
    for name in ('both30_70','both_add100','cut30','add70'):
        Lm,_,_=build_legs(L,sts,pbl,**runs[name]);np.save(OUT/f'daily_{name}.npy',W.run_period(Lm,[1.]*len(Lm),W.TEST_START)['daily'])
if __name__=='__main__':main()
