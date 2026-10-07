"""Chart for mtf_search.csv: train vs validation Calmar of 2,880 2h/3h/4h configs, coloured by correlation with the bot."""
from pathlib import Path
import json
import pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';R=pd.read_csv(D/'mtf_search.csv');R=R[R.n_train>=100];b=json.loads((D/'mtf_search.json').read_text())['bot']
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
fig,(a1,a2)=plt.subplots(1,2,figsize=(15,6.2),gridspec_kw=dict(width_ratios=[1.6,1]))
sc=a1.scatter(R.train_calmar.clip(-1,4),R.oos_calmar.clip(-1,4),c=R['corr'],cmap='coolwarm',vmin=-.2,vmax=1,s=10,alpha=.75)
a1.scatter([b['train'][0]],[b['oos'][0]],s=220,marker='*',color='#0b0b0b',zorder=3,label='your bot (2A+5A)');a1.axhline(0,color=INK2,lw=1);a1.axvline(0,color=INK2,lw=1)
a1.fill_between([b['train'][0],4],b['oos'][0],4,color='#008300',alpha=.08);a1.text(3.95,3.9,'better than the bot in BOTH',ha='right',va='top',color='#008300',fontsize=9)
a1.set_xlim(-1,4);a1.set_ylim(-1,4);a1.set_xlabel('Calmar, TRAIN 2021-10..2024');a1.set_ylabel('Calmar, VALIDATION 2025-26');a1.legend(loc='lower right')
fig.colorbar(sc,ax=a1,label='correlation of daily returns with the bot');a1.set_title('2,880 configs on 2h / 3h / 4h: the empty green corner',loc='left')
f=pd.Series(json.loads((D/'mtf_search.json').read_text())['family_both']).sort_values()
a2.barh(f.index,f.values,color=['#e34948' if k in('RSI2','BBREV','RSI2T','PULL') else '#2a78d6' for k in f.index],height=.65);a2.set_xlabel('% of configs profitable in both periods');a2.grid(axis='y',visible=False)
a2.set_title('By entry family (red = mean reversion / pullback)',loc='left')
fig.tight_layout();fig.savefig(D/'charts/15_mtf_search.png',dpi=150)
