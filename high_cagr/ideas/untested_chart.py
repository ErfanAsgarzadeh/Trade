"""Train vs validation Calmar for every new idea tried on top of 2A+5A."""
from pathlib import Path
import json
import numpy as np
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas'
SURF,INK,INK2,GRID='#fcfcfb','#0b0b0b','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
b=json.loads((D/'htf_confirm.json').read_text())['baseline_2A5A']['results'];rows=[]
for fn,tag in (('htf_confirm.json','HTF'),('untested_ideas.json','NEW'),('orderflow_test.json','FLOW')):
    for k,v in json.loads((D/fn).read_text())['variants'].items():rows.append((f'{k}',v['results']['train|2']['calmar'],v['results']['oos|2']['calmar']))
fig,ax=plt.subplots(figsize=(10,6.4))
ax.axvline(b['train|2']['calmar'],color='#9a9893',ls='--');ax.axhline(b['oos|2']['calmar'],color='#9a9893',ls='--')
ax.fill_between([b['train|2']['calmar'],3],b['oos|2']['calmar'],3,color='#008300',alpha=.07)
ax.text(2.42,2.95,'better in BOTH slices',color='#008300',fontsize=9,ha='right',va='top')
ax.scatter([b['train|2']['calmar']],[b['oos|2']['calmar']],s=170,color='#2a78d6',zorder=3,edgecolor=SURF,lw=2);ax.annotate('2A+5A (bot now)',(b['train|2']['calmar'],b['oos|2']['calmar']),xytext=(8,8),textcoords='offset points',color='#2a78d6',fontweight='bold')
for n,tr,oo in rows:
    ax.scatter(tr,oo,s=80,color='#eb6834',zorder=3,edgecolor=SURF,lw=2);ax.annotate(n,(tr,oo),xytext=(6,-4),textcoords='offset points',fontsize=9,color=INK2)
ax.set_xlim(.7,2.5);ax.set_ylim(1.5,3.0);ax.set_xlabel('Calmar, Train 2021-2024');ax.set_ylabel('Calmar, Validation 2025-2026')
ax.set_title('Every new idea vs the bot default: none lands in the green corner',loc='left')
fig.tight_layout();fig.savefig(D/'charts/9_new_ideas_train_vs_validation.png',dpi=150)
