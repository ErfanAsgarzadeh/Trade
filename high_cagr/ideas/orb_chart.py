"""Chart for orb_intraday.json."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';d=json.loads((D/'orb_intraday.json').read_text())
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
b=np.array(json.loads((D/'htf_confirm.json').read_text())['baseline_2A5A']['curve'])
fig,ax=plt.subplots(figsize=(12,5.5));ax.plot(pd.to_datetime(b[:,0],unit='ms'),b[:,1],color='#2a78d6',lw=2.2,label='4h bot alone (2A+5A)')
for k,c in (('A','#eb6834'),('B','#e34948'),('C','#4a3aa7')):
    x=d['variants'][k]['2bps']['curve'];ax.plot(pd.to_datetime([r[0] for r in x]),[r[1] for r in x],color=c,lw=1.6,label=f'ORB {k} alone')
x=d['variants']['A']['2bps']['curve_comb'];ax.plot(pd.to_datetime([r[0] for r in x]),[r[1] for r in x],color='#eb6834',lw=1.6,ls='--',label='bot + ORB A')
ax.set_yscale('log');ax.legend(loc='lower left');ax.set_ylabel('equity $ (log)')
ax.set_title('Intraday opening-range breakout on the 5 coins: no edge even before costs',loc='left')
fig.tight_layout();fig.savefig(D/'charts/12_orb_intraday.png',dpi=150)
