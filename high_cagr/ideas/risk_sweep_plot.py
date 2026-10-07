"""Charts for risk_sweep (reads output/ideas/risk_sweep/grid.csv and series.npz)."""
from pathlib import Path
import sys
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg');import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import risk_sweep as R, xuni as X
P=pd.read_csv(R.OUT/'grid.csv');Z=np.load(R.OUT/'series.npz')
fig,ax=plt.subplots(2,2,figsize=(15,11))
for k,(kind,col,title) in enumerate((('bot','bot','Bot alone (5 coins, 2A+5A)'),('c3','c3','C3+D alone (10 coins)'))):
    q=P[P.kind==kind].sort_values(col);x=q[col]*100;a=ax[0,k];a2=a.twinx()
    a.plot(x,q.full_cagr,'o-',c='tab:green',label='CAGR full');a.plot(x,q.train_cagr,'--',c='tab:green',alpha=.5,label='CAGR train');a.plot(x,q.oos_cagr,':',c='tab:green',alpha=.8,label='CAGR valid')
    a.plot(x,q.full_dd,'s-',c='tab:red',label='max DD full');a2.plot(x,q.full_cal,'^-',c='tab:blue',label='Calmar (right)')
    for dd in (20,30):a.axhline(dd,c='tab:red',lw=.6,ls=':')
    best=q.loc[q.full_cagr.idxmax()];a.annotate(f"max growth {best[col]*100:.2f}%\nCAGR {best.full_cagr:.0f}% DD {best.full_dd:.0f}%",(best[col]*100,best.full_cagr),xytext=(-120,-10),textcoords='offset points',arrowprops=dict(arrowstyle='->'),fontsize=9)
    a.set_xlabel('risk per trade (% of equity)');a.set_ylabel('% per year / max drawdown %');a2.set_ylabel('Calmar');a.set_title(title)
    h1,l1=a.get_legend_handles_labels();h2,l2=a2.get_legend_handles_labels();a.legend(h1+h2,l1+l2,fontsize=8,loc='upper left');a.grid(alpha=.3)
b=P[P.kind=='both'];bots=sorted(b.bot.unique());c3s=sorted(b.c3.unique())
G=b.pivot(index='c3',columns='bot',values='full_cagr').loc[c3s,bots];D=b.pivot(index='c3',columns='bot',values='train_dd').loc[c3s,bots]
a=ax[1,0];im=a.imshow(G.values,origin='lower',cmap='viridis',aspect='auto');plt.colorbar(im,ax=a,label='CAGR full %')
for i in range(len(c3s)):
    for j in range(len(bots)):a.text(j,i,f"{G.values[i,j]:.0f}\n{D.values[i,j]:.0f}",ha='center',va='center',fontsize=6.5,color='w' if D.values[i,j]>25 else 'k',fontweight='bold' if D.values[i,j]<=25 else None)
cs=a.contour(D.values,levels=[20,25,30],colors=['white','orange','red'],linewidths=1.5);a.clabel(cs,fmt='DD %d%%',fontsize=8)
a.set_xticks(range(len(bots)),[f'{x*100:.2f}' for x in bots],rotation=45);a.set_yticks(range(len(c3s)),[f'{x*100:.2f}' for x in c3s])
a.set_xlabel('bot risk per trade %');a.set_ylabel('C3+D risk per trade %');a.set_title('Bot + C3+D together: CAGR (top) / train max DD (bottom) per cell')
a=ax[1,1];days=len(Z['bot_0.0075']);dates=pd.date_range('2021-10-05',periods=days,freq='D')
for lab,rb,rc,c in (('now: bot 0.75% + C3 0.15%',.0075,.0015,'k'),('DD<=20: bot 0.75% + C3 0.2%',.0075,.002,'tab:green'),('DD<=25: bot 0.75% + C3 0.3%',.0075,.003,'tab:orange'),('DD<=30: bot 1.5% + C3 0.2%',.015,.002,'tab:red')):
    r=Z[f'bot_{rb}']+Z['c3_0.001']*rc/.001 if rc==.0015 else Z[f'bot_{rb}']+Z[f'c3_{rc}']
    eq=np.cumprod(1+r);st=X.stats(r)['full'];a.plot(dates,eq,c=c,label=f"{lab} | CAGR {st[1]:.0f}% DD {st[2]:.0f}%")
a.set_yscale('log');a.axvline(pd.Timestamp('2025-01-01'),c='gray',ls='--');a.text(pd.Timestamp('2025-01-10'),1.05,'validation ->',fontsize=8)
a.set_title('Equity (log), start = 1');a.legend(fontsize=8);a.grid(alpha=.3)
plt.tight_layout();plt.savefig(R.OUT/'risk_sweep.png',dpi=110);print(R.OUT/'risk_sweep.png')
