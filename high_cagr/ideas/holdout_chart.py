"""Chart for holdout_test.json: the 3 candidates on 20 untouched coins."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';d=json.loads((D/'holdout_test.json').read_text())
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
fig,ax=plt.subplots(figsize=(12,5.5))
lab={'C1':'C1 RSI50 cross, 3 ATR trail, ADX<20','C2':'C2 RSI50 cross, 4.5 ATR trail, ADX<20','C3':'C3 trend pullback, 4.5 ATR trail, no weekend'}
for k,c in (('C1','#9a9893'),('C2','#eda100'),('C3','#2a78d6')):
    x=d['candidates'][k];st=x['all20']['full'];ax.plot(pd.date_range('2021-10-05',periods=len(x['curve']),freq='7D'),x['curve'],color=c,lw=2.4 if k=='C3' else 1.6,
        label=f"{lab[k]}  CAGR {st[1]:.0f}% DD {st[2]:.0f}%  {'PASS' if x['passed'] else 'fail'}")
ax.axvline(pd.Timestamp('2025-01-01'),color=INK2,ls=':');ax.text(pd.Timestamp('2025-01-15'),ax.get_ylim()[0]*1.05,'validation',color=INK2,fontsize=9)
ax.set_yscale('log');ax.set_ylabel('equity $ (log), 20 untouched coins');ax.legend(loc='upper left',fontsize=9)
ax.set_title('Final holdout: 3 candidates on 20 coins never used in the search',loc='left')
fig.tight_layout();fig.savefig(D/'charts/17_holdout.png',dpi=150)
