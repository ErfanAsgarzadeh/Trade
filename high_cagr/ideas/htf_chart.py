"""Chart for htf_confirm.json."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';d=json.loads((D/'htf_confirm.json').read_text())
SURF,INK,INK2,GRID='#fcfcfb','#0b0b0b','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
runs=[('2A+5A (bot now)',d['baseline_2A5A'],'#2a78d6')]+[(k,v,c) for (k,v),c in zip(d['variants'].items(),['#eb6834','#1baf7a','#4a3aa7','#eda100'])]
fig,(a1,a2,a3)=plt.subplots(1,3,figsize=(15,4.8),gridspec_kw=dict(width_ratios=[2.2,1,1]))
for n,r,c in runs:
    a=np.array(r['curve']);a1.plot(pd.to_datetime(a[:,0],unit='ms'),a[:,1],color=c,lw=2.2 if n.startswith('2A') else 1.6,label=n)
a1.set_yscale('log');a1.set_title('Equity (start $10k, log)',loc='left');a1.legend(loc='upper left',fontsize=9)
names=[n.split(' ')[0] for n,_,_ in runs];cols=[c for *_,c in runs];f=[r['results']['full|2'] for _,r,_ in runs]
x=np.arange(len(runs))
a2.bar(x,[v['win'] for v in f],color=cols,width=.65);a2.set_ylim(40,50);a2.set_xticks(x,names,rotation=30,ha='right');a2.set_title('Win rate % (unchanged)',loc='left');a2.grid(axis='x',visible=False)
for i,v in enumerate(f):a2.text(i,v['win']+.15,f"{v['win']:.1f}",ha='center',fontsize=9,color=INK)
a3.bar(x,[v['calmar'] for v in f],color=cols,width=.65);a3.set_xticks(x,names,rotation=30,ha='right');a3.set_title('Calmar (CAGR / maxDD)',loc='left');a3.grid(axis='x',visible=False)
for i,v in enumerate(f):a3.text(i,v['calmar']+.03,f"{v['calmar']:.2f}",ha='center',fontsize=9,color=INK)
fig.suptitle('Higher-timeframe confirmation on top of 2A+5A, 5 symbols, 2021-10 to 2026-10',x=.01,ha='left',fontweight='bold')
fig.tight_layout();fig.savefig(D/'charts/8_htf_confirmation.png',dpi=150)
