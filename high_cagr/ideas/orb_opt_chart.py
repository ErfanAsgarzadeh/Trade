"""Chart for orb_opt.json: every trigger and filter, TRAIN vs VALIDATION return."""
from pathlib import Path
import json
import numpy as np
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';d=json.loads((D/'orb_opt.json').read_text())
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
fig,ax=plt.subplots(figsize=(10,6.5))
ax.axhline(0,color=INK2,lw=1);ax.axvline(0,color=INK2,lw=1);ax.fill_between([0,80],0,80,color='#008300',alpha=.07);ax.text(78,76,'profitable in BOTH',color='#008300',ha='right',va='top',fontsize=9)
g=d['stage1'];ax.scatter([x['train']['ret'] for x in g],[x['oos']['ret'] for x in g],s=40,color='#9a9893',label=f'{len(g)} entry triggers (no filter)')
s=d['singles'];ax.scatter([x['train']['ret'] for x in s],[x['oos']['ret'] for x in s],s=50,color='#2a78d6',label=f'{len(s)} single filters on the best trigger')
f=d['final'];ax.scatter([f['orb']['train']['ret']],[f['orb']['oos']['ret']],s=180,color='#e34948',zorder=3,edgecolor=SURF,lw=2,label='best TRAIN combination (4 filters)')
ax.annotate('train +54%  →  validation −24%',(f['orb']['train']['ret'],f['orb']['oos']['ret']),xytext=(-150,-30),textcoords='offset points',color='#e34948',fontsize=10,arrowprops=dict(arrowstyle='->',color='#e34948'))
ax.set_xlim(-100,80);ax.set_ylim(-80,80);ax.set_xlabel('return %, TRAIN 2021-10..2024 (used for selection)');ax.set_ylabel('return %, VALIDATION 2025-2026 (never used)')
ax.legend(loc='lower right');ax.set_title('ORB A optimisation: nothing is profitable in both periods',loc='left')
fig.tight_layout();fig.savefig(D/'charts/13_orb_optimisation.png',dpi=150)
