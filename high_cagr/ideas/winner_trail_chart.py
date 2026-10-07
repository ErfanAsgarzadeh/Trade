"""Charts for winner_trail.json + winner_trail_sensitivity.json."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas'
SURF,INK,INK2,GRID='#fcfcfb','#0b0b0b','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
b=json.loads((D/'htf_confirm.json').read_text())['baseline_2A5A'];w=json.loads((D/'winner_trail.json').read_text())['variants'];s=json.loads((D/'winner_trail_sensitivity.json').read_text())
fig=plt.figure(figsize=(15,9));g=fig.add_gridspec(2,2,height_ratios=[1.15,1])
a1=fig.add_subplot(g[0,:]);a2=fig.add_subplot(g[1,0]);a3=fig.add_subplot(g[1,1])
for n,c,col,lw in (('2A+5A (bot now)',b['curve'],'#9a9893',1.8),('WIDE20_5R: 20-bar trail after 5R',w['WIDE20_5R']['curve'],'#eb6834',2),('TIGHT4_5R: 4-bar trail after 5R',w['TIGHT4_5R']['curve'],'#2a78d6',2)):
    a=np.array(c);a1.plot(pd.to_datetime(a[:,0],unit='ms'),a[:,1],color=col,lw=lw,label=f'{n}  (${a[-1,1]-1e4:,.0f})')
a1.set_yscale('log');a1.legend(loc='upper left');a1.set_title('Equity, start $10k (log). The wide trail gains almost all of its edge in 2024',loc='left')
a1.axvline(pd.Timestamp('2025-01-01'),color=INK2,ls=':');a1.text(pd.Timestamp('2025-01-15'),11000,'validation →',color=INK2,fontsize=9)
chans=['3bar','4bar','15bar','20bar'];rs=[3,4,5,6,8]
for ax,key,title in ((a2,'oos|2','Validation 2025-26 Calmar (bot now 2.44)'),(a3,'full|2','Full-period Calmar (bot now 1.96)')):
    M=np.array([[s[f'{c}@{r}R']['results'][key]['calmar'] for r in rs] for c in chans]);base=b['results'][key]['calmar']
    im=ax.imshow(M-base,cmap='RdBu',vmin=-.8,vmax=.8,aspect='auto')
    for i in range(len(chans)):
        for j in range(len(rs)):
            p=s[f'{chans[i]}@{rs[j]}R']['verdict']['passed'];ax.text(j,i,f'{M[i,j]:.2f}'+(' ✓' if p else ''),ha='center',va='center',fontsize=10,color=INK)
    ax.set_xticks(range(len(rs)),[f'after {r}R' for r in rs]);ax.set_yticks(range(len(chans)),[f'{c} trail' for c in chans]);ax.grid(False);ax.set_title(title,loc='left')
fig.text(.01,.01,'Heatmaps: blue = better than the bot, red = worse; ✓ = passes all 4 pre-declared gates. Neighbourhood grid is post-hoc.',color=INK2,fontsize=9)
fig.tight_layout(rect=(0,.03,1,1));fig.savefig(D/'charts/10_winner_trail.png',dpi=150)
