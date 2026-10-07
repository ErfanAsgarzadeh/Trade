"""Chart for trend_audit.csv: what the bot did during the 15 biggest trends."""
from pathlib import Path
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';T=pd.read_csv(D/'trend_audit.csv')
SURF,INK,INK2,GRID='#fcfcfb','#0b0b0b','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
top=T.reindex(T.move_pct.abs().sort_values(ascending=False).index).head(15).iloc[::-1]
cats=[('share_WITH','in the trade, with the trend','#1baf7a'),('share_FLAT:no_signal','flat: no fresh breakout yet','#9a9893'),('share_AGAINST','in a trade against the trend','#e34948'),('share_FLAT:blocked_2A','flat: ATR filter 2A blocked','#eda100')]
fig,ax=plt.subplots(figsize=(12,7.5));y=np.arange(len(top));left=np.zeros(len(top))
for col,lab,c in cats:
    v=top[col].clip(lower=0).to_numpy();ax.barh(y,v,left=left,color=c,height=.62,label=lab,edgecolor=SURF,lw=1.5);left+=v
ax.set_yticks(y,[f"{r.symbol[:-4]} {r.side} {r.start[:7]} ({r.move_pct:+.0f}%)" for r in top.itertuples()])
ax.set_xlabel('share of the trend move (% of log move; slices can exceed 100% because flat/against slices include pullbacks)')
ax.legend(loc='upper center',bbox_to_anchor=(0.45,-0.09),ncol=4);ax.grid(axis='y',visible=False)
ax.set_title('15 biggest trends: the grey part (out of the market, waiting for a new 10-bar breakout) is the main leak',loc='left')
fig.tight_layout();fig.savefig(D/'charts/11_trend_audit.png',dpi=150)
