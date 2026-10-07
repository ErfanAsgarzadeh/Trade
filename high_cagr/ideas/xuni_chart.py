"""Chart for xuni.csv: 5-coin selection metric vs result on 10 other coins, plus the bot on both universes."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';R=pd.read_csv(D/'xuni.csv');J=json.loads((D/'xuni.json').read_text())
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
typ=R.fam.map(lambda f:'ORB' if f.startswith('ORB') else ('mean reversion' if f in('RSI2T','RSI2','BBREV') else ('pullback' if f=='PULL' else 'trend')))
fig,(a1,a2)=plt.subplots(1,2,figsize=(15,6))
for t,c in (('mean reversion','#e34948'),('pullback','#eda100'),('trend','#2a78d6')):
    m=(typ==t)&R.five_train.notna();a1.scatter(R[m].five_train.clip(-1,4),R[m].full.clip(-1,2),s=8,alpha=.55,color=c,label=f'{t} ({m.sum()})')
a1.axhline(0,color=INK2,lw=1);a1.axvline(0,color=INK2,lw=1)
a1.scatter([J['bot5']['train'][0]],[J['bot10']['full'][0]],marker='*',s=260,color='#0b0b0b',zorder=3,label='your bot')
a1.set_xlabel('Calmar on YOUR 5 coins, train period (how configs were picked)');a1.set_ylabel('Calmar on 10 OTHER coins, full 5 years')
a1.set_title(f"Ranking transfers (Spearman {J['spearman']:.2f}), levels do not",loc='left');a1.legend(loc='upper left',fontsize=9);a1.set_xlim(-1,4);a1.set_ylim(-1,2)
a2.bar(['5 coins\n(yours)','10 other\ncoins'],[J['bot5']['full'][1],J['bot10']['full'][1]],color=['#2a78d6','#9a9893'],width=.5)
for i,(g,d) in enumerate(((J['bot5']['full'][1],J['bot5']['full'][2]),(J['bot10']['full'][1],J['bot10']['full'][2]))):a2.text(i,max(g,0)+1,f'CAGR {g:.1f}%\nmax DD {d:.0f}%',ha='center',fontsize=11)
a2.set_ylim(0,55);a2.set_ylabel('CAGR %, 2021-10..2026-10');a2.grid(axis='x',visible=False);a2.set_title('Your bot (2A+5A), same settings, two universes',loc='left')
fig.tight_layout();fig.savefig(D/'charts/16_cross_universe.png',dpi=150)
