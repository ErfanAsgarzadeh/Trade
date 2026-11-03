"""Trade success-probability model (meta-labeling) for the three bots, pre-declared before the test period was looked at.

DATA. Every entry of the shipped three-bot ledger (five_year_report.ledgers('soft'): Shahin, Mojsavar, Ghoghnous soft x1.5).
Label = the trade's net P&L per unit (fees, slippage, funding) > 0. Pyramid adds are not scored: they follow their root.
SPLIT (by entry time). TRAIN 2021-10-05 .. 2023-12-31 (fit + every threshold), 2024 = untouched gap (shown for
information), TEST 2025-01-01 .. 2026-10-04 (judge only).

FEATURES (causal: the last CLOSED 4h bar before the entry minute, signed by the trade side so that + = "with the trade"):
  trend200 side*(close/EMA200-1)      trend50 side*(close/EMA50-1)       slope50 side*(EMA50[b]-EMA50[b-6])/ATR
  ret20    side*20-bar return          ret120  side*120-bar return         vol     ATR14/close
  volrank  share of the previous 500 bars with lower ATR/close         rangepos position in the 60-bar range (1 = at
  the extreme in the trade direction)   btc200 / btc6  BTC vs its EMA200 and 6-bar return, signed   breadth side*(share
  of the 35 coins above their EMA50 - 0.5)   stop  stop distance / entry   bot one-hot (Mojsavar, Ghoghnous; Shahin = base)
MODELS. Primary (decides): logistic regression, standardised features, C=0.3. Comparison only: gradient boosting
(depth 3, 200 trees, lr 0.05, min leaf 40). Score percentiles come from 5-fold out-of-fold TRAIN predictions.
SCENARIOS (fixed now; replayed on one $10,000 account that starts empty on 2025-01-01, same engine as the 5-year test):
  base          all trades
  skip20/30/40/50  no entry when the score is in the bottom 20/30/40/50% of TRAIN scores
  size_lin      risk x (0.5 + pct)            pct = TRAIN percentile of the score (average multiplier 1 on TRAIN)
  size_strong   risk x (0.25 + 1.5 pct)
  skip30_size   skip the bottom 30%, the rest risk x (0.5 + pct)
Accept rule (fixed now): a scenario is "better" only if on TEST its Calmar is above base AND its max drawdown is not
worse than base + 2 pp. Neither the features nor any number above was changed after the test results were seen.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import five_year_report as FY, pabench as PB, pa2_confluence as CF
from high_cagr import run_suite as rs
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/win_prob'
START=pd.Timestamp('2021-10-05')
def minute(day):return int((pd.Timestamp(day)-START).total_seconds()//60)
TRAIN_END=minute('2024-01-01');TEST_START=minute('2025-01-01')
FEATS=['trend200','trend50','slope50','ret20','ret120','vol','volrank','rangepos','btc200','btc6','breadth','stop','bot_c3','bot_pa']
COINS=sorted(set(PB.ALL35))

@functools.lru_cache(None)
def bars(s):
    d=PB.coin(s);c=d['c'];a=d['atr'];v=a/c
    hi=pd.Series(d['h']).rolling(60).max().to_numpy();lo=pd.Series(d['l']).rolling(60).min().to_numpy()
    return dict(c=c,e50=d['e50'],e200=d['e200'],atr=a,vol=v,vr=CF.prank(np.ascontiguousarray(v),500),hi=hi,lo=lo)

@functools.lru_cache(1)
def breadth():
    n=min(len(bars(s)['c']) for s in COINS)
    return np.mean([bars(s)['c'][:n]>bars(s)['e50'][:n] for s in COINS],axis=0)

def features(L):
    B=bars('BTCUSDT');br=breadth();rows=[]
    for l in L:
        s=l['side'];b=l['em']//240-1;x=bars(l['coin']);c=x['c'][b]
        def ret(k):return s*(c/x['c'][b-k]-1) if b-k>=0 else np.nan
        rng=x['hi'][b]-x['lo'][b];pos=(c-x['lo'][b])/rng if rng>0 else .5
        bc=B['c'][b]
        rows.append(dict(trend200=s*(c/x['e200'][b]-1),trend50=s*(c/x['e50'][b]-1),slope50=s*(x['e50'][b]-x['e50'][b-6])/x['atr'][b],
            ret20=ret(20),ret120=ret(120),vol=x['vol'][b],volrank=x['vr'][b],rangepos=pos if s>0 else 1-pos,
            btc200=s*(bc/B['e200'][b]-1),btc6=s*(bc/B['c'][b-6]-1),breadth=s*(br[b]-.5) if b<len(br) else np.nan,stop=l['stop_frac'],
            bot_c3=float(l['bot']=='c3'),bot_pa=float(l['bot']=='pa')))
    return pd.DataFrame(rows,columns=FEATS)

def models():
    return {'logit':make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=2000)),
            'gbm':HistGradientBoostingClassifier(max_depth=3,max_iter=200,learning_rate=.05,min_samples_leaf=40,random_state=0)}

def fill(X,med):return X.fillna(med)

def scenarios(pct):
    return {'base':np.ones_like(pct),
        **{f'skip{q}':(pct>=q/100).astype(float) for q in (20,30,40,50)},
        'size_lin':.5+pct,'size_strong':.25+1.5*pct,'skip30_size':np.where(pct>=.3,.5+pct,0.)}

def run_period(L,mult,start_min,end_min=None):
    legs=[]
    for l,m in zip(L,mult):
        if l['em']<start_min or (end_min is not None and l['em']>=end_min):continue
        legs.append(dict(l,risk_scale=l['risk_scale']*m,skip=m<=0))
    r=FY.replay(legs=legs);d0=start_min//1440;d1=len(r['daily']) if end_min is None else end_min//1440
    d=r['daily'][d0:d1];t=r['trades'];yrs=len(d)/365.25
    dd=(d/np.maximum.accumulate(d)-1).min()*100;cagr=((d[-1]/FY.SEED)**(1/yrs)-1)*100
    w=t[t.pnl>0];pf=w.pnl.sum()/-t[t.pnl<=0].pnl.sum()
    return dict(final=float(d[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else np.inf,trades=int(len(t)),win=float(len(w)/max(1,len(t))*100),pf=float(pf),daily=d)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    L=FY.ledgers('soft');roots=[i for i,l in enumerate(L) if not l['is_add']]
    R=[L[i] for i in roots];X=features(R);y=np.array([l['unit']>0 for l in R],int);em=np.array([l['em'] for l in R])
    tr=em<TRAIN_END;gap=(em>=TRAIN_END)&(em<TEST_START);te=em>=TEST_START
    med=X[tr].median();Xf=fill(X,med)
    print('roots',len(R),'train',tr.sum(),'2024',gap.sum(),'test',te.sum(),'train win',y[tr].mean().round(3),'test win',y[te].mean().round(3),flush=True)
    res={'n':dict(train=int(tr.sum()),gap=int(gap.sum()),test=int(te.sum())),'win':dict(train=float(y[tr].mean()),gap=float(y[gap].mean()),test=float(y[te].mean())),'models':{}}
    scores={}
    for name,mk in models().items():
        oof=np.zeros(tr.sum());Xt=Xf[tr].to_numpy();yt=y[tr]
        for a,b in KFold(5).split(Xt):
            m=models()[name].fit(Xt[a],yt[a]);oof[b]=m.predict_proba(Xt[b])[:,1]
        m=models()[name].fit(Xt,yt);p=m.predict_proba(Xf.to_numpy())[:,1];p[tr]=oof
        srt=np.sort(oof);pct=np.searchsorted(srt,p,side='right')/len(srt)
        scores[name]=dict(p=p,pct=pct)
        q=pd.qcut(pct[te],5,labels=False,duplicates='drop')
        buckets=[dict(q=int(k),n=int((q==k).sum()),win=float(y[te][q==k].mean()),p=float(p[te][q==k].mean()),unit=float(np.mean([R[i]['unit']*R[i]['entry']/R[i]['entry'] for i in np.where(te)[0][q==k]]))) for k in range(int(q.max())+1)]
        qt=pd.cut(pct[te],[0,.2,.4,.6,.8,1.0001],labels=False,include_lowest=True)
        fixed=[dict(q=int(k),n=int((qt==k).sum()),win=float(y[te][qt==k].mean()) if (qt==k).any() else None) for k in range(5)]
        per_bot={b:dict(auc=float(roc_auc_score(y[te][np.array([R[i]['bot']==b for i in np.where(te)[0]])],p[te][np.array([R[i]['bot']==b for i in np.where(te)[0]])]))) for b in ('main','c3','pa')}
        res['models'][name]=dict(auc_train_oof=float(roc_auc_score(y[tr],oof)),auc_2024=float(roc_auc_score(y[gap],p[gap])),auc_test=float(roc_auc_score(y[te],p[te])),
            test_buckets_by_train_pct=fixed,per_bot=per_bot)
        if name=='logit':res['coef']=dict(zip(FEATS,m[-1].coef_[0].round(4).tolist()))
        print(name,{k:(round(v,3) if isinstance(v,float) else v) for k,v in res['models'][name].items() if k.startswith('auc')},flush=True)
        print('  test win by TRAIN-score quintile',[(b['n'],round(b['win'],3) if b['win'] is not None else None) for b in fixed],flush=True)
    # map each leg (adds follow their root) to its multiplier, replay TEST and 2024
    root_pct={}
    for name in scores:
        rp={L[i]['root']:scores[name]['pct'][k] for k,i in enumerate(roots)}
        root_pct[name]=np.array([rp[l['root']] for l in L])
    res['scen']={}
    for name in scores:
        res['scen'][name]={}
        for per,(a,b) in {'test':(TEST_START,None),'y2024':(TRAIN_END,TEST_START)}.items():
            out={}
            for sc,mult in scenarios(root_pct[name]).items():
                r=run_period(L,mult,a,b);
                if per=='test':np.save(OUT/f'daily_{name}_{sc}.npy',r['daily'])
                r.pop('daily');out[sc]=r
                print(name,per,f'{sc:12s}',f"final {r['final']:>12,.0f} CAGR {r['cagr']:6.1f}% DD {r['dd']:6.1f}% Calmar {r['calmar']:5.2f} trades {r['trades']:4d} win {r['win']:4.1f}% PF {r['pf']:.2f}",flush=True)
            res['scen'][name][per]=out
    pd.DataFrame(dict(bot=[l['bot'] for l in R],coin=[l['coin'] for l in R],em=em,win=y,p_logit=scores['logit']['p'],pct_logit=scores['logit']['pct'],p_gbm=scores['gbm']['p'],pct_gbm=scores['gbm']['pct'])).join(X).to_csv(OUT/'scored_trades.csv',index=False)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
