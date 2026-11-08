"""In-trade monitoring study, pre-declared before any 2025-26 number of it was looked at.
IDEA. At every 4h close while a position is open, re-score it ("does holding from here beat exiting now?") and react when the score
drops. Label for a state (leg, bar): future = final net R - unrealised R now; cont = future > 0. Score = P(cont) from a model
fit on TRAIN legs (entry < 2024-01-01); percentiles come from out-of-fold train states (grouped by leg).
State features: the 48 market criteria at that bar (criteria_lib.at) + unrealised R, max favourable / adverse excursion in R,
give-back from the peak, bars held, ATR now / ATR at entry.
REACTIONS (price-path exact on 1-minute data, costs as the bots: 0.06% fee per side, 2 bps slippage per fill, funding):
  EXIT    close the whole position at that 4h close
  TIGHTEN stop moves to 0.5 R below the 4h close (long; above for short), never looser than the stop it has; the original exit
          logic still runs, so whichever happens first closes the trade
  HALF    close half at that 4h close, the rest keeps the original exit
TRIGGERS. Learned: bottom 10 / 20 / 30 % of TRAIN state scores (first bar where it happens, from bar 2 of the trade).
Classic rule-based reactions for comparison (frozen now): BE1 / BE2 (stop to entry + 0.25R after +1R / +2R), CHAND (exit when the
close falls 3 ATR from the best close), TIME (exit at bar 20 if below +0.5R), EMA20 (exit when the close crosses to the wrong side
of EMA20 while in profit), GIVEBACK (exit when half of a >= 1R peak is gone), ADVERSE (exit when below -0.7R and the 6-bar EMA20
slope is against the trade).
Everything is replayed on the same $10,000 engine from 2025-01-01 (TEST) and 2024 (information). Accept rule unchanged.
"""
import sys,json,warnings,functools
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import win_prob_model as W, five_year_report as FY, criteria_lib as C, pabench as PB
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/live_monitor';FEE=.0006;SLIP=.0002
DYN=['unreal_R','mfe_R','mae_R','giveback','bars','atr_ratio']

@functools.lru_cache(None)
def px(s):return PB._px(s)
@functools.lru_cache(None)
def bars(s):return PB._bars(s)
@functools.lru_cache(None)
def fc(s):return PB.coin(s)['fc']

def exit_unit(l,m,xraw,with_slip=True):
    s=l['side'];xp=xraw*(1-s*SLIP) if with_slip else xraw;e=l['entry'];f=fc(l['coin'])
    return s*(xp-e)-(e+xp)*FEE-s*e*(f[m+1]-f[l['em']])

def states(l):
    """closed-4h-bar states of a leg: list of dict(m=close minute, b=bar, ...) while the leg is open."""
    s=l['side'];e=l['entry'];sd=e*l['stop_frac'];P=px(l['coin']);b=bars(l['coin']);em,xm=l['em'],l['xm'];b0=em//240
    seg=P[em:xm+1];hi=np.maximum.accumulate(seg[:,1]);lo=np.minimum.accumulate(seg[:,2]);out=[]
    best=-1e18;
    for k,bb in enumerate(range(b0,(xm+1)//240+1)):
        m=(bb+1)*240-1
        if m>=xm:break
        i=m-em;c=P[m,3]
        fav=(hi[i]-e) if s>0 else (e-lo[i]);adv=(e-lo[i]) if s>0 else (hi[i]-e);rn=s*(c-e)/sd
        best=max(best,s*c)
        out.append(dict(m=m,b=bb,k=k+1,close=c,unreal_R=rn,mfe_R=fav/sd,mae_R=adv/sd,giveback=fav/sd-rn,bars=k+1,atr_ratio=b['atr'][bb]/b['atr'][max(b0-1,0)],best_close=s*best))
    return out

def build(L):
    rows=[];meta=[]
    for j,l in enumerate(L):
        Rf=l['unit']/(l['entry']*l['stop_frac'])
        for st in states(l):
            f=C.at(l['coin'],st['b'],l['side'],l['stop_frac'],l['bot']);f.update({d:st[d] for d in DYN})
            rows.append(f);meta.append((j,st['m'],st['b'],st['k'],Rf-st['unreal_R'],l['em']))
    X=pd.DataFrame(rows)[C.ALL+DYN].astype(float).replace([np.inf,-np.inf],np.nan);M=pd.DataFrame(meta,columns=['leg','m','b','k','future','em']);return X,M

def apply_reaction(L,trig,kind):
    """trig: dict leg index -> state (the first triggering state). returns the modified legs list."""
    out=[]
    for j,l in enumerate(L):
        st=trig.get(j)
        if st is None:out.append(l);continue
        s=l['side'];e=l['entry'];sd=e*l['stop_frac'];m=st['m']
        if kind=='EXIT':
            out.append(dict(l,xm=m,unit=exit_unit(l,m,st['close'])));continue
        if kind=='HALF':
            a=dict(l,xm=m,unit=exit_unit(l,m,st['close']),risk_scale=l['risk_scale']*.5);bb=dict(l,risk_scale=l['risk_scale']*.5,is_add=True);out+= [a,bb];continue
        # TIGHTEN / BE-type: stop level given in absolute price by st['stop'] (None -> 0.5R below close)
        stop=st.get('stop');stop=stop if stop is not None else st['close']-s*.5*sd
        P=px(l['coin']);seg=P[m+1:l['xm']+1]
        if len(seg)==0:out.append(l);continue
        hit=(seg[:,2]<=stop) if s>0 else (seg[:,1]>=stop)
        if not hit.any() or (s>0 and stop<=e-sd) or (s<0 and stop>=e+sd) and False:out.append(l);continue
        i=int(np.argmax(hit));mx=m+1+i;op=seg[i,0];xraw=min(op,stop) if s>0 else max(op,stop)
        out.append(dict(l,xm=mx,unit=exit_unit(l,mx,xraw)))
    return out

def first_trigger(M,X,mask,state_fn=None):
    t={};sub=M[mask].sort_values(['leg','m'])
    for r in sub.itertuples():
        if r.leg not in t:t[r.leg]=r
    return t

def rule_triggers(L,name):
    """classic rules: returns dict leg-> dict(m, close, [stop])"""
    t={}
    for j,l in enumerate(L):
        s=l['side'];e=l['entry'];sd=e*l['stop_frac'];b=bars(l['coin']);sts=states(l)
        for st in sts:
            rn=st['unreal_R'];c=st['close'];hit=False;stop=None
            if name=='BE1' and st['mfe_R']>=1:hit=True;stop=e+s*.25*sd
            elif name=='BE2' and st['mfe_R']>=2:hit=True;stop=e+s*.25*sd
            elif name=='CHAND':
                a=b['atr'][st['b']];hit=st['k']>=2 and s*(c-st['best_close']*s)<=-3*a if False else (st['k']>=2 and (st['best_close']-s*c)>=3*a)
            elif name=='TIME':hit=st['k']>=20 and rn<.5
            elif name=='EMA20':hit=st['k']>=2 and rn>0 and s*(c-b['e20'][st['b']])<0
            elif name=='GIVEBACK':hit=st['mfe_R']>=1 and st['giveback']>=.5*st['mfe_R']
            elif name=='ADVERSE':
                sl=(b['e20'][st['b']]-b['e20'][st['b']-6])*s;hit=st['k']>=2 and rn<-.7 and sl<0
            if hit:
                t[j]=dict(m=st['m'],close=c,stop=stop,rn=rn);break
    return t
def kind_of(name):return 'TIGHTEN' if name in ('BE1','BE2') else 'EXIT'

def replay(legs,start,end=None):
    r=W.run_period(legs,[1.]*len(legs),start,end);r.pop('daily');return r
def judge(res,base):return res['calmar']>base['calmar'] and res['dd']>=base['dd']-2

def main():
    OUT.mkdir(parents=True,exist_ok=True);L=FY.ledgers('soft');print('legs',len(L),flush=True)
    # validate the early-exit P&L formula on legs that exit at a 4h close (opp-exit / time stop)
    chk=[(l['unit'],exit_unit(l,l['xm'],px(l['coin'])[l['xm'],3])) for l in L if l['bot']=='pa' and (l['xm']+1)%240==0][:300]
    a=np.array(chk);print('formula check on',len(a),'close-exits: mean abs error in % of entry:',np.mean(np.abs(a[:,0]-a[:,1])/np.array([l['entry'] for l in L if l['bot']=='pa' and (l['xm']+1)%240==0][:300]))*100,flush=True)
    X,M=build(L);print('states',len(X),flush=True)
    em=M.em.to_numpy();tr=em<W.TRAIN_END;gap=(em>=W.TRAIN_END)&(em<W.TEST_START);te=em>=W.TEST_START
    y=(M.future>0).astype(int).to_numpy();Xf=X.fillna(X[tr].median());A=Xf.to_numpy();grp=M.leg.to_numpy();idx=np.where(tr)[0]
    base_t=replay(L,W.TEST_START);base_g=replay(L,W.TRAIN_END,W.TEST_START);print('base test',round(base_t['calmar'],2),round(base_t['dd'],1),round(base_t['final']),flush=True)
    res={'base':dict(test=base_t,y2024=base_g),'models':{},'reactions':{}}
    models={'logit':lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=3000)),
            'gbm':lambda:HistGradientBoostingClassifier(max_depth=3,max_iter=150,learning_rate=.05,min_samples_leaf=100,random_state=0)}
    pcts={}
    for nm,mkm in models.items():
        oof=np.zeros(len(M))
        for a,b in GroupKFold(5).split(idx,groups=grp[idx]):oof[idx[b]]=mkm().fit(A[idx[a]],y[idx[a]]).predict_proba(A[idx[b]])[:,1]
        p=mkm().fit(A[tr],y[tr]).predict_proba(A)[:,1];p[tr]=oof[tr];srt=np.sort(oof[tr]);pct=np.searchsorted(srt,p,side='right')/len(srt);pcts[nm]=pct
        res['models'][nm]=dict(auc_train_oof=float(roc_auc_score(y[tr],oof[tr])),auc_2024=float(roc_auc_score(y[gap],p[gap])),auc_test=float(roc_auc_score(y[te],p[te])),cont_rate_test=float(y[te].mean()))
        print('state model',nm,res['models'][nm],flush=True)
    jobs=[(f'ML-{nm}-{kind}-{q}',nm,kind,q) for nm in models for kind in ('EXIT','TIGHTEN','HALF') for q in (.1,.2,.3)]
    for key,nm,kind,q in jobs:
        trig=first_trigger(M,X,(pcts[nm]<q)&(M.k.to_numpy()>=2))
        trig={j:dict(m=r.m,close=px(L[j]['coin'])[r.m,3],stop=None,rn=None) for j,r in trig.items()}
        out={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            Lm=apply_reaction(L,{j:t for j,t in trig.items()},kind);r=replay(Lm,a,b);r['legs_reacted']=int(sum(1 for j in trig if (L[j]['em']>=a and (b is None or L[j]['em']<b))));out[per]=r
        res['reactions'][key]=out;t=out['test'];g=out['y2024']
        print(f"{key:22s} TEST final {t['final']:>9,.0f} DD {t['dd']:6.1f} Calmar {t['calmar']:5.2f} reacted {t['legs_reacted']:4d} {'PASS' if judge(t,base_t) else '    '} | 2024 Calmar {g['calmar']:5.2f} DD {g['dd']:6.1f} {'PASS' if judge(g,base_g) else ''}",flush=True)
    for name in ('BE1','BE2','CHAND','TIME','EMA20','GIVEBACK','ADVERSE'):
        trig=rule_triggers(L,name);kind=kind_of(name);out={}
        for per,(a,b) in {'test':(W.TEST_START,None),'y2024':(W.TRAIN_END,W.TEST_START)}.items():
            Lm=apply_reaction(L,trig,kind);r=replay(Lm,a,b);r['legs_reacted']=int(sum(1 for j in trig if (L[j]['em']>=a and (b is None or L[j]['em']<b))));out[per]=r
        res['reactions'][f'RULE-{name}']=out;t=out['test'];g=out['y2024']
        print(f"RULE-{name:16s} TEST final {t['final']:>9,.0f} DD {t['dd']:6.1f} Calmar {t['calmar']:5.2f} reacted {t['legs_reacted']:4d} {'PASS' if judge(t,base_t) else '    '} | 2024 Calmar {g['calmar']:5.2f} DD {g['dd']:6.1f} {'PASS' if judge(g,base_g) else ''}",flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
