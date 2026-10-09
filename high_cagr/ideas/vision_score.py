"""Blind chart-scoring test: would a visual 1-10 score before entry have flagged the losing trades? Written BEFORE running.

Sample: main bot (2A+5A) root trades from the VALIDATION period (entry >= 2025-01-01), random seed 7: 40 losers (net R<0)
and 40 winners (net R>0). One PNG per trade, shuffled ids, showing ONLY what was known at the signal bar: last 120 closed
4h candles up to the signal bar, Ichimoku cloud (current), Donchian-10 channel, EMA50, and an arrow with the trade side.
No symbol, no dates, no price axis (prices normalised), no outcome. The id->trade key is written only after scoring.
Scorers: 4 subagents, 20 images each, same rubric (score 1-10 = how likely the trade ends in profit), no other files.
Pre-declared read-out:
  - share of losers scored < 5 and share of winners scored < 5 (a coin flip gives about the same share for both)
  - AUC of score vs outcome (0.5 = no skill)
  - effect of "skip if score < 5" on the validation trades: net R kept vs net R of all 80 sampled trades
Verdict "useful" only if losers<5 share exceeds winners<5 share by >= 20 pp AND skipped trades have negative total R.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg');import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc, conviction_2x as CV, ltf_search as L
OUT=bench.OUT/'vision_score'

def render(f,r,side,path):
    w=f.iloc[r-119:r+1];o,h,l,c=(w[k].to_numpy() for k in ('open','high','low','close'));ref=c[-1];n=len(w);x=np.arange(n)
    fig,ax=plt.subplots(figsize=(9,5),dpi=90);ax.set_facecolor('white')
    kt,kb=w.kumo_top.to_numpy()/ref,w.kumo_bottom.to_numpy()/ref;ax.fill_between(x,kb,kt,color='#9bb7e0',alpha=.35,lw=0,label='Ichimoku cloud')
    ax.plot(x,w.donchian_high_10.to_numpy()/ref,c='#888',lw=.8,ls='--',label='Donchian 10');ax.plot(x,w.donchian_low_10.to_numpy()/ref,c='#888',lw=.8,ls='--')
    ax.plot(x,w.ema50.to_numpy()/ref,c='#d08a00',lw=1.1,label='EMA50')
    for i in range(n):
        col='#2a9d55' if c[i]>=o[i] else '#d1495b';ax.vlines(i,l[i]/ref,h[i]/ref,color=col,lw=.7);ax.add_patch(plt.Rectangle((i-.35,min(o[i],c[i])/ref),.7,max(abs(c[i]-o[i])/ref,1e-5),color=col))
    y=c[-1]/ref;ax.annotate('LONG' if side>0 else 'SHORT',xy=(n-1,y),xytext=(n+4,y*(1-.04*side)),color='g' if side>0 else 'r',fontsize=11,fontweight='bold',arrowprops=dict(arrowstyle='->',color='g' if side>0 else 'r'))
    ax.set_xlim(-2,n+14);ax.set_yticks([]);ax.set_xticks([]);ax.legend(loc='upper left',fontsize=8);ax.set_title('4h candles, last bar = signal bar (entry at next open)',fontsize=9)
    fig.tight_layout();fig.savefig(path);plt.close(fig)

def build(keydir):
    ctx=bench.load();base=hc.build(ctx,None);F=CV.feats(ctx);P=CV.ledger(ctx,base,F);va=P[~P.train]
    rng=np.random.default_rng(7);los=va[va.R<0].sample(40,random_state=7);win=va[va.R>0].sample(40,random_state=8)
    S=pd.concat([los,win]).sample(frac=1,random_state=9).reset_index(drop=True);ids=[f'c{int(i):03d}' for i in rng.permutation(900)[:len(S)]+100]
    img=OUT/'images';img.mkdir(parents=True,exist_ok=True)
    for i,r in zip(ids,S.itertuples()):render(ctx['frames'][r.sym],ctx['ix'][r.sym][r.b],r.side,img/f'{i}.png')
    key=dict(zip(ids,[dict(sym=r.sym,side=int(r.side),R=float(r.R),entry=int(r.entry)) for r in S.itertuples()]))
    Path(keydir).mkdir(parents=True,exist_ok=True);(Path(keydir)/'key.json').write_text(json.dumps(key));print(len(ids),'images ->',img)

def evaluate(keyfile,scorefile):
    key=json.loads(Path(keyfile).read_text());sc=json.loads(Path(scorefile).read_text())
    rows=[dict(id=i,score=float(sc[i]),**key[i]) for i in key if i in sc];D=pd.DataFrame(rows);D['loss']=D.R<0
    lo=D[D.loss];wi=D[~D.loss];a=float(((lo.score.values[:,None]<wi.score.values[None,:]).mean()+.5*(lo.score.values[:,None]==wi.score.values[None,:]).mean()))
    skip=D[D.score<5];res=dict(n=len(D),losers_below5=float((lo.score<5).mean()*100),winners_below5=float((wi.score<5).mean()*100),auc=a,
        R_all=float(D.R.sum()),R_kept=float(D[D.score>=5].R.sum()),R_skipped=float(skip.R.sum()),n_skipped=len(skip),
        mean_score_losers=float(lo.score.mean()),mean_score_winners=float(wi.score.mean()))
    res['useful']=bool(res['losers_below5']-res['winners_below5']>=20 and res['R_skipped']<0)
    D.to_csv(OUT/'scored.csv',index=False);(OUT/'result.json').write_text(json.dumps(dict(notes=__doc__,**res),indent=1));print(json.dumps(res,indent=1))
if __name__=='__main__':
    (build if sys.argv[1]=='build' else evaluate)(*sys.argv[2:])
