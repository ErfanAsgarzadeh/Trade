"""Continuous 2023-01-01 .. 2026-10-04 account chart: three bots alone vs three bots + bot 4 (G2) at 0.15% and 0.25% risk per
trade, and G2 alone at 0.5%. G2 is walk-forward: each year's trades are chosen by a model trained only on trades that exited
before that year (same as bot4_f2.py)."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,matplotlib.ticker as mt
from high_cagr.ideas import bot4_f2 as G, bot4_failures as BF, h4_ai_bot as H4, ml_walkforward as WF, win_prob_model as W, five_year_report as FY
OUT=ROOT/'high_cagr/output/ideas/bot4_f2'
def main():
    pbc=BF.candidates(True,0.);pbu=BF.candidates(False,0.);brc=G.brk_candidates(True)
    for l in pbu:l['rule']=2
    L=pbc+brc+pbu;X=H4.features(L);R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in L]);y=(R>=2).astype(int)
    em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);rule=np.array([l['rule'] for l in L]);legs=[]
    for fn,(a,b) in WF.FOLDS.items():
        tr=xm<a;A=X.fillna(X[tr].median()).to_numpy();p=BF.gbm().fit(A[tr],y[tr]).predict_proba(A)[:,1];pc=BF.pct_of(p[tr&(rule==1)],p)
        legs+=[L[i] for i in np.where((em>=a)&((em<b) if b else True)&(rule==1)&(pc>=.7))[0]]
    a=WF.FOLDS['2023'][0];dep=FY.ledgers('soft');x=None;curves={};stats={}
    for name,lg in {'Three bots (current)':dep,'Three bots + bot 4 at 0.15%':dep+[dict(l,risk_scale=.3) for l in legs],
                    'Three bots + bot 4 at 0.25%':dep+[dict(l,risk_scale=.5) for l in legs],'Bot 4 (G2) alone at 0.5%':legs}.items():
        r=W.run_period(lg,[1.]*len(lg),a);d=r.pop('daily');curves[name]=d;stats[name]=r
        x=pd.date_range('2023-01-01',periods=len(d))
        s=pd.Series(d,index=x).resample('YE').last();yr=(s/s.shift(1).fillna(10000.)-1)*100;r['yearly']={str(k.year):round(float(v),1) for k,v in yr.items()}
        print(f'{name:30s} final {r["final"]:>10,.0f} CAGR {r["cagr"]:6.1f}% DD {r["dd"]:6.1f}% Calmar {r["calmar"]:5.2f} trades {r["trades"]:5d} | yearly {r["yearly"]}',flush=True)
    cols={'Three bots (current)':'#6b7280','Three bots + bot 4 at 0.15%':'#2563eb','Three bots + bot 4 at 0.25%':'#0d9488','Bot 4 (G2) alone at 0.5%':'#d97706'}
    fig,(ax,ax2)=plt.subplots(2,1,figsize=(11,7.5),sharex=True,gridspec_kw=dict(height_ratios=[3,1.3]))
    for k,d in curves.items():
        ax.plot(x,d,color=cols[k],lw=2 if 'current' in k or '0.15' in k else 1.4,label=f'{k}: ${d[-1]:,.0f}');dd=(d/np.maximum.accumulate(d)-1)*100;ax2.plot(x,dd,color=cols[k],lw=1.1)
    ax.set_yscale('log');ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v,_:f'${v/1000:,.0f}k'));ax.legend(frameon=False,loc='upper left',fontsize=9)
    ax.set_title('One $10,000 account, 2023-01-01 .. 2026-10-04 (bot 4 chosen walk-forward each year)',loc='left',fontsize=11,fontweight='bold')
    for yv in ('2024-01-01','2025-01-01'):ax.axvline(pd.Timestamp(yv),color='#d1d5db',lw=.8);ax2.axvline(pd.Timestamp(yv),color='#d1d5db',lw=.8)
    ax2.set_ylabel('drawdown %');ax2.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.grid(alpha=.3);ax2.grid(alpha=.3)
    for a_ in (ax,ax2):a_.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(OUT/'g2_with_bots_2023_2026.png',dpi=130);(OUT/'g2_chart_stats.json').write_text(json.dumps(stats,indent=1,default=float))
if __name__=='__main__':main()
