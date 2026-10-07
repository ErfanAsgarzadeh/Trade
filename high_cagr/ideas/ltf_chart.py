"""Chart for ltf_search.csv: every 30m/1h config, TRAIN vs VALIDATION CAGR, by family type."""
from pathlib import Path
import pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';R=pd.read_csv(D/'ltf_search.csv');R=R[R.n_train>=150]
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
typ=R.fam.map(lambda f:'mean reversion (RSI2, Bollinger fade)' if f in('RSI2T','RSI2','BBREV') else ('pullback in trend' if f=='PULL' else 'trend following'))
fig,axs=plt.subplots(1,2,figsize=(14,6),sharey=True)
for ax,tf in zip(axs,('30m','1h')):
    ax.axhline(0,color=INK2,lw=1);ax.axvline(0,color=INK2,lw=1);ax.fill_between([0,70],0,70,color='#008300',alpha=.07)
    for t,c in (('mean reversion (RSI2, Bollinger fade)','#e34948'),('pullback in trend','#eda100'),('trend following','#2a78d6')):
        m=(R.tf==tf)&(typ==t);ax.scatter(R[m].train_ret_cagr.clip(-100,70),R[m].oos_cagr.clip(-100,70),s=14,color=c,alpha=.7,label=f'{t} ({m.sum()})')
    ax.set_xlim(-100,70);ax.set_ylim(-100,70);ax.set_title(f'{tf}: {((R.tf==tf)&(R.train_ret_cagr>0)&(R.oos_cagr>0)).sum()} configs profitable in both periods',loc='left');ax.set_xlabel('CAGR %, TRAIN 2021-10..2024')
axs[0].set_ylabel('CAGR %, VALIDATION 2025-26');axs[0].legend(loc='lower right',fontsize=9)
fig.suptitle('840 strategy configs on 30m / 1h, taker costs (green = profitable in both)',x=.01,ha='left',fontweight='bold')
fig.tight_layout();fig.savefig(D/'charts/14_ltf_search.png',dpi=150)
