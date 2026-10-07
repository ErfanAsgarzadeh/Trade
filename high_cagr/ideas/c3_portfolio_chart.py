"""Chart for c3_portfolio: coin count (part 1) and the bot + C3 risk frontier (part 2)."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[2]/'high_cagr/output/ideas';J=json.loads((D/'c3_portfolio.json').read_text());P=pd.read_csv(D/'c3_portfolio_grid.csv')
SURF,INK2,GRID='#fcfcfb','#52514e','#e6e5e0'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.grid':True,'grid.color':GRID,'axes.spines.top':False,'axes.spines.right':False,'xtick.color':INK2,'ytick.color':INK2,'axes.titleweight':'bold','legend.frameon':False})
fig,(a1,a2)=plt.subplots(1,2,figsize=(15,6),gridspec_kw=dict(width_ratios=[1,1.5]))
N=[x['N'] for x in J['part1']];a1.bar(np.array(N)-1,[x['budget']['oos'][0] for x in J['part1']],2,color='#2a78d6',label='Validation Calmar (same total risk budget)')
a1.bar(np.array(N)+1,[x['budget']['train'][0] for x in J['part1']],2,color='#9a9893',label='Train Calmar')
a1.set_xticks(N,[f'top {n}' for n in N]);a1.set_ylabel('Calmar (CAGR / max DD), C3 alone');a1.legend(loc='upper right');a1.grid(axis='x',visible=False)
a1.set_title('C3: more coins = weaker coins, not better',loc='left')
m=P.peak<=3;a2.scatter(P[m].fu_dd,P[m].fu_cagr,s=12,color='#2a78d6',alpha=.45,label='bot + C3 combinations (margin OK)')
a2.scatter(P[~m].fu_dd,P[~m].fu_cagr,s=12,color='#e34948',alpha=.35,label='needs > 60% margin (not allowed)')
for lab,q,c in (('bot alone',P[(P.mb==1)&(P.rc==0)].iloc[0],'#0b0b0b'),('PICK: bot + C3 0.15%',pd.Series(J['pick']),'#008300'),('previous: C3 0.25%',P[(P.mb==1)&(P.rc==.0025)&(P.N==10)&(P.K==0)].iloc[0],'#eda100')):
    a2.scatter([q.fu_dd],[q.fu_cagr],s=180,marker='*',color=c,zorder=3,edgecolor=SURF);a2.annotate(f'{lab}\n{q.fu_cagr:.0f}%/yr, DD {q.fu_dd:.0f}%',(q.fu_dd,q.fu_cagr),xytext=(8,-4),textcoords='offset points',fontsize=9,color=c)
a2.set_xlim(8,45);a2.set_ylim(0,170);a2.set_xlabel('max drawdown %, full 5 years');a2.set_ylabel('CAGR %, full 5 years');a2.legend(loc='lower right',fontsize=9)
a2.set_title('Bot + C3: return vs drawdown (pick made on train only)',loc='left')
fig.tight_layout();fig.savefig(D/'charts/18_c3_portfolio.png',dpi=150)
