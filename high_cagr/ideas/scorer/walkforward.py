"""Position scorer walk-forward (PREDECLARED.md): ENTRY and HOLD models, fixed policies, shared-account replay per fold."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.scorer import data as D
from high_cagr.ideas.frisk import dd_engine as DE
from scipy.stats import spearmanr
EMB=14*1440;START=pd.Timestamp('2021-10-05')
def mn(s):return int((pd.Timestamp(s)-START).total_seconds()//60)
FOLDS={'2023':(mn('2023-01-01'),mn('2024-01-01')),'2024':(mn('2024-01-01'),mn('2025-01-01')),'2025-26':(mn('2025-01-01'),None)}
HOLD_F=['unreal','mfe','mae','giveback','bars','rem']

def model():
    from xgboost import XGBRegressor
    return XGBRegressor(n_estimators=300,max_depth=3,learning_rate=.03,subsample=.8,colsample_bytree=.8,min_child_weight=20,reg_lambda=5.,tree_method='hist',n_jobs=4,random_state=7)

def fit_pct(X,y,groups,tr,te):
    """Fit on tr, return percentiles of the te predictions against out-of-fold predictions of tr (5 folds grouped by coin)."""
    from sklearn.model_selection import GroupKFold
    Xt,yt,g=X[tr],y[tr],groups[tr];oof=np.zeros(len(yt))
    for a,b in GroupKFold(5).split(Xt,yt,g):oof[b]=model().fit(Xt[a],yt[a]).predict(Xt[b])
    m=model().fit(Xt,yt);p=m.predict(X[te]);s=np.sort(oof);return np.searchsorted(s,p,side='right')/len(s),p

def xmat(df,cols):
    X=df[cols].astype(float).copy()
    for b in ('main','c3','pa'):X['bot_'+b]=(df.bot==b).astype(float)
    return X.to_numpy()

def apply_actions(L,acts):
    """acts: id -> (minute, frac). Returns the modified deployed legs."""
    out=[]
    for l in L:
        a=acts.get(l['id'])
        if a is None:out.append(l);continue
        m,fr=a;u=D.exit_unit(l,m,fr);n=dict(l,unit=u)
        if fr>=1:n['xm']=int(m)
        out.append(n)
    return out

def replay(L,a,b,mult=None):
    mult=np.ones(len(L)) if mult is None else mult
    r=DE.period(L,mult,a,b);r.pop('daily');w=[l for l,k in zip(L,mult) if l['em']>=a and (b is None or l['em']<b) and k>0]
    r['win']=float(np.mean([l['unit']>0 for l in w])*100);return r

def main():
    L=D.build_legs();ET=D.entry_table(L);ST=D.state_table(L);byid={l['id']:l for l in L};dep=[l for l in L if not l['aug']]
    ecols=[c for c in ET.columns if c.startswith('f_')];Xe=xmat(ET,ecols);ye=ET.R.clip(-1.5,8).to_numpy();ge=ET.coin.to_numpy()
    S=ST.merge(ET[['id','bot','coin','em','xm','aug','is_add']],on='id');scols=HOLD_F+[c for c in ST.columns if c.startswith('f_')];Xs=xmat(S,scols);ys=S.v_hold.clip(-3,8).to_numpy();gs=S.coin.to_numpy()
    res={}
    for fn,(a,b) in FOLDS.items():
        hi=b if b else 10**9
        tr=(ET.xm<a-EMB).to_numpy()&~ET.is_add.to_numpy();te=((ET.em>=a)&(ET.em<hi)&~ET.aug).to_numpy()
        pe,raw=fit_pct(Xe,ye,ge,tr,te);T=ET[te].assign(pct=pe,pred=raw);epct=dict(zip(T.id,T.pct));rootp=dict(zip(T[~T.is_add].root,T[~T.is_add].pct))
        from sklearn.metrics import roc_auc_score
        skill={'entry_auc_win':{bt:float(roc_auc_score(g.R>0,g.pct)) for bt,g in T[~T.is_add].groupby('bot')},'entry_spearman':{bt:float(spearmanr(g.pct,g.R)[0]) for bt,g in T[~T.is_add].groupby('bot')}}
        trs=(S.xm<a-EMB).to_numpy();tes=((S.em>=a)&(S.em<hi)&~S.aug).to_numpy()
        ph,_=fit_pct(Xs,ys,gs,trs,tes);H=S[tes].assign(pct=ph).sort_values(['id','m'])
        skill['hold_spearman']={bt:float(spearmanr(g.pct,g.v_hold)[0]) for bt,g in H.groupby('bot')};skill['train_roots']=int(tr.sum());skill['train_states']=int(trs.sum())
        Lf=[l for l in dep];base=replay(Lf,a,b);out={'base':base,'skill':skill}
        def emult(kind):
            m=np.ones(len(Lf))
            for i,l in enumerate(Lf):
                if not (a<=l['em']<hi):continue
                p=rootp.get(l['root'],epct.get(l['id'],.5))
                if kind=='M_only':m[i]=.5+D.mom(l['coin'],l['side'],l['em'])
                elif kind=='E_skip20':m[i]=0. if p<.2 else 1.
                elif kind=='E_size':m[i]=.5+p
                elif kind=='E_both':m[i]=0. if p<.2 else .5+p
            return m
        def acts(kind):
            A={}
            for i,g in H.groupby('id'):
                if kind=='T_cut':h=g[(g.pct<.10)&(g.unreal<=0)];fr=1.
                elif kind=='T_exit10':h=g[g.pct<.10];fr=1.
                else:h=g[g.pct<.20];fr=.5
                if len(h):A[i]=(int(h.m.iloc[0]),fr)
            return A
        EM={k:emult(k) for k in ('M_only','E_skip20','E_size','E_both')};TA={k:acts(k) for k in ('T_cut','T_exit10','T_half20')}
        for k,m in EM.items():out[k]=replay(Lf,a,b,m)
        for k,A in TA.items():out[k]=dict(replay(apply_actions(Lf,A),a,b),acted=len(A))
        out['_E']=EM;out['_T']=TA;res[fn]=out
        ok=lambda r:r['calmar']>=base['calmar'] and -r['dd']<=-base['dd']+2
        print(f"fold {fn}: train roots {skill['train_roots']} states {skill['train_states']} | entry AUC {json.dumps({k:round(v,3) for k,v in skill['entry_auc_win'].items()})} hold IC {json.dumps({k:round(v,3) for k,v in skill['hold_spearman'].items()})}",flush=True)
        for k,r in out.items():
            if k in ('skill','_E','_T'):continue
            if k!='base':r['pass']=bool(ok(r))
            print(f"   {k:9s} CAGR {r['cagr']:6.1f} DD {r['dd']:6.1f} Calmar {r['calmar']:5.2f} WR {r['win']:.1f} trades {r['trades']} {'acted '+str(r['acted']) if 'acted' in r else ''} {'PASS' if r.get('pass') else ''}",flush=True)
    names=[k for k in res['2023'] if k not in ('base','skill','_E','_T')];passed={k:all(res[f][k]['pass'] for f in res) for k in names}
    score=lambda k:sum(res[f][k]['calmar'] for f in res);be=max([k for k in names if k[0] in 'EM' and passed[k]],key=score,default=None);bt=max([k for k in names if k[0]=='T' and passed[k]],key=score,default=None)
    print('PASSED in every fold:',[k for k,v in passed.items() if v],'| best entry',be,'| best in-trade',bt)
    if be and bt:
        for fn,(a,b) in FOLDS.items():
            o=res[fn];Lm=apply_actions([l for l in dep],o['_T'][bt]);r=replay(Lm,a,b,o['_E'][be]);r['pass']=bool(r['calmar']>=o['base']['calmar'] and -r['dd']<=-o['base']['dd']+2);o['combined']=r
            print(f"   combined {fn}: CAGR {r['cagr']:.1f} DD {r['dd']:.1f} Calmar {r['calmar']:.2f} WR {r['win']:.1f} {'PASS' if r['pass'] else ''}")
    for f in res:res[f].pop('_E');res[f].pop('_T')
    (D.OUT/'walkforward.json').write_text(json.dumps(dict(folds=res,passed=passed,best_entry=be,best_in_trade=bt),indent=1,default=float))
if __name__=='__main__':main()
