"""Price-action checklist test (things the bot cannot see). Written and committed BEFORE any scoring; one run.

Sample: main bot (2A+5A) root trades, random seed 11: 200 TRAIN trades (entry < 2025-01-01) and 120 VALIDATION trades,
natural win/loss mix. One PNG per trade, shuffled ids: last 180 closed 4h candles up to the signal bar, Ichimoku cloud,
Donchian-10, EMA50, LONG/SHORT arrow; no symbol, dates, price axis or outcome. id->trade key written only after scoring.
Each chart is reviewed TWICE (passes A and B, different subagents, Sonnet), 25 charts per agent, yes/no answers:
  Q1 level    entry runs straight into a prior major swing high (long) / swing low (short) within ~1-2 candle ranges ahead
  Q2 double   double top (long) / double bottom (short) against the trade in the last ~40 candles near current price
  Q3 wedge    the move into the entry is the 3rd push of a wedge / clearly decelerating pushes in the trade direction
  Q4 climax   a climactic, unusually large candle in the trade direction within the last 3 candles after an extended run
  Q5 tlbreak  the trend in the trade direction already broke its trendline/channel (sign of reversal) before the entry
  Q6 range    the last ~20 candles were a tight sideways range / barb wire before the signal
Agreement: Cohen's kappa between passes per item. An answer counts as YES when both passes say yes.
Rule choice on TRAIN only: per item, mean net R of YES vs NO (n_yes >= 20). Candidate = largest |difference|; multiplier 0.5x
on YES if YES is worse, 1.5x on YES if YES is better.
VALIDATION gates (all): kappa >= 0.4; YES-vs-NO difference has the same sign in validation; weighted R >= flat R at the same
mean multiplier x 1.10. Otherwise nothing is adopted.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc, conviction_2x as CV, vision_score as VS
OUT=bench.OUT/'pa_checklist';Q=['level','double','wedge','climax','tlbreak','range']

def render(f,r,side,path):
    import matplotlib.pyplot as plt
    w=f.iloc[r-179:r+1];o,h,l,c=(w[k].to_numpy() for k in ('open','high','low','close'));ref=c[-1];n=len(w);x=np.arange(n)
    fig,ax=plt.subplots(figsize=(11,5.5),dpi=90)
    ax.fill_between(x,w.kumo_bottom.to_numpy()/ref,w.kumo_top.to_numpy()/ref,color='#9bb7e0',alpha=.35,lw=0,label='Ichimoku cloud')
    ax.plot(x,w.donchian_high_10.to_numpy()/ref,c='#888',lw=.8,ls='--',label='Donchian 10');ax.plot(x,w.donchian_low_10.to_numpy()/ref,c='#888',lw=.8,ls='--')
    ax.plot(x,w.ema50.to_numpy()/ref,c='#d08a00',lw=1.1,label='EMA50')
    for i in range(n):
        col='#2a9d55' if c[i]>=o[i] else '#d1495b';ax.vlines(i,l[i]/ref,h[i]/ref,color=col,lw=.7);ax.add_patch(plt.Rectangle((i-.35,min(o[i],c[i])/ref),.7,max(abs(c[i]-o[i])/ref,1e-5),color=col))
    y=c[-1]/ref;ax.annotate('LONG' if side>0 else 'SHORT',xy=(n-1,y),xytext=(n+5,y*(1-.04*side)),color='g' if side>0 else 'r',fontsize=11,fontweight='bold',arrowprops=dict(arrowstyle='->',color='g' if side>0 else 'r'))
    ax.set_xlim(-2,n+18);ax.set_yticks([]);ax.set_xticks([]);ax.legend(loc='upper left',fontsize=8);ax.set_title('4h candles, last bar = signal bar (entry at next open)',fontsize=9)
    fig.tight_layout();fig.savefig(path);plt.close(fig)

def build(keydir):
    import matplotlib;matplotlib.use('Agg')
    ctx=bench.load();base=hc.build(ctx,None);F=CV.feats(ctx);P=CV.ledger(ctx,base,F)
    S=pd.concat([P[P.train].sample(200,random_state=11),P[~P.train].sample(120,random_state=12)]).sample(frac=1,random_state=13).reset_index(drop=True)
    ids=[f'p{int(i):04d}' for i in np.random.default_rng(11).permutation(9000)[:len(S)]+1000]
    img=OUT/'images';img.mkdir(parents=True,exist_ok=True)
    for i,r in zip(ids,S.itertuples()):render(ctx['frames'][r.sym],ctx['ix'][r.sym][r.b],r.side,img/f'{i}.png')
    key={i:dict(sym=r.sym,side=int(r.side),R=float(r.R),train=bool(r.train)) for i,r in zip(ids,S.itertuples())}
    Path(keydir).mkdir(parents=True,exist_ok=True);(Path(keydir)/'key.json').write_text(json.dumps(key));print(len(ids),'images ->',img)

def kappa(a,b):
    a=np.asarray(a,int);b=np.asarray(b,int);po=(a==b).mean();pe=a.mean()*b.mean()+(1-a.mean())*(1-b.mean());return float((po-pe)/(1-pe)) if pe<1 else 1.

def evaluate(keyfile,passA,passB):
    key=json.loads(Path(keyfile).read_text());A=json.loads(Path(passA).read_text());B=json.loads(Path(passB).read_text())
    rows=[]
    for i,k in key.items():
        if i not in A or i not in B:continue
        rows.append(dict(id=i,**k,**{f'{q}_A':int(A[i][q]) for q in Q},**{f'{q}_B':int(B[i][q]) for q in Q},**{q:int(A[i][q] and B[i][q]) for q in Q}))
    D=pd.DataFrame(rows);tr=D[D.train];va=D[~D.train];res=dict(notes=__doc__,n_train=len(tr),n_valid=len(va),items={})
    for q in Q:
        k=kappa(D[f'{q}_A'],D[f'{q}_B']);it=dict(kappa=k)
        for nm,d in (('train',tr),('valid',va)):
            y=d[d[q]==1];no=d[d[q]==0];it[nm]=dict(n_yes=len(y),yes_R=float(y.R.mean()) if len(y) else None,no_R=float(no.R.mean()),yes_win=float((y.R>0).mean()*100) if len(y) else None,no_win=float((no.R>0).mean()*100))
        res['items'][q]=it
        t,v=it['train'],it['valid'];print(f"{q:8s} kappa {k:5.2f} | TRAIN yes {t['n_yes']:3d} R {t['yes_R'] if t['yes_R'] is not None else float('nan'):+.2f} vs no {t['no_R']:+.2f} | VALID yes {v['n_yes']:3d} R {v['yes_R'] if v['yes_R'] is not None else float('nan'):+.2f} vs no {v['no_R']:+.2f}",flush=True)
    cand={q:it['train']['yes_R']-it['train']['no_R'] for q,it in res['items'].items() if it['train']['n_yes']>=20}
    if not cand:res.update(pick=None,passed=False);print('no item with >= 20 YES in train')
    else:
        q=max(cand,key=lambda z:abs(cand[z]));mult=0.5 if cand[q]<0 else 1.5;m=np.where(va[q]==1,mult,1.);w=float((va.R*m).sum());flat=float(va.R.sum()*m.mean())
        it=res['items'][q];vd=(it['valid']['yes_R'] or 0)-it['valid']['no_R'] if it['valid']['n_yes'] else 0
        G=dict(kappa=it['kappa']>=.4,same_sign=bool(np.sign(vd)==np.sign(cand[q]) and it['valid']['n_yes']>0),weighted=bool(w>=flat*1.10 if flat>0 else w>flat))
        res.update(pick=q,multiplier=mult,valid_weighted_R=w,valid_flat_R=flat,gates=G,passed=all(G.values()))
        print(f"PICK {q} ({mult}x on YES): VALID weighted R {w:.1f} vs flat {flat:.1f} | gates {G} PASS={all(G.values())}")
    notes=[dict(id=i,note_A=A[i].get('note',''),note_B=B[i].get('note','')) for i in D.id]
    D.to_csv(OUT/'answers.csv',index=False);(OUT/'notes.json').write_text(json.dumps(notes,ensure_ascii=False,indent=0));(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':
    (build if sys.argv[1]=='build' else evaluate)(*sys.argv[2:])
