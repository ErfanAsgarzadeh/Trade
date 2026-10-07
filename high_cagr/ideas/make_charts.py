"""Charts for the five-idea test (reads high_cagr/output/ideas/*.json)."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'high_cagr/output/ideas';OUT=D/'charts';OUT.mkdir(parents=True,exist_ok=True)
BLUE,ORANGE,AQUA,YELLOW,MAGENTA,GREEN,VIOLET,RED='#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#4a3aa7','#e34948'
INK,INK2,MUTED,GRID,SURF='#0b0b0b','#52514e','#8a8984','#e6e5e0','#fcfcfb';BASE='#9a9893'
plt.rcParams.update({'figure.facecolor':SURF,'axes.facecolor':SURF,'axes.edgecolor':GRID,'axes.labelcolor':INK2,'xtick.color':INK2,'ytick.color':INK2,
 'axes.grid':True,'grid.color':GRID,'grid.linewidth':.8,'axes.spines.top':False,'axes.spines.right':False,'font.size':10,'axes.titlesize':11,'axes.titleweight':'bold','axes.titlecolor':INK,'legend.frameon':False})
TITLES={'idea1_volume':'1 Volume filter','idea2_atr_regime':'2 ATR regime filter','idea3_time_stop':'3 Time stop','idea4_confirmation':'4 Breakout confirmation','idea5_giveback':'5 Giveback protection','combo_all5':'All 5 combined (pre-declared)'}
LABEL={('idea1_volume','A'):'skip vol<1.5',('idea1_volume','B'):'half risk vol<1.5',('idea2_atr_regime','A'):'skip ATRrel<1',('idea2_atr_regime','B'):'half risk ATRrel<1',
 ('idea3_time_stop','A'):'12h, MFE<0.5R',('idea3_time_stop','B'):'24h, MFE<0.5R',('idea4_confirmation','A'):'wait 1 bar',('idea4_confirmation','B'):'penetration>=0.25ATR',
 ('idea5_giveback','A'):'BE+0.1R after 1R',('idea5_giveback','B'):'close 1/3 at 1.5R',('idea5_giveback','C'):'4-bar trail after 2R',('combo_all5','BEST'):'best variant of each'}
base=json.loads((D/'baseline.json').read_text());ideas={n:json.loads((D/f'{n}.json').read_text()) for n in TITLES}
post=json.loads((D/'posthoc_atr_combos.json').read_text())
def curve(c):
    a=np.array(c);return pd.to_datetime(a[:,0],unit='ms'),a[:,1]
def dd(eq):peak=np.maximum.accumulate(eq);return (eq/peak-1)*100
rows=[]
for n,d in ideas.items():
    for v,x in d['variants'].items():
        r=x['results'];rows.append(dict(idea=n,var=v,label=f"{n[4] if n!='combo_all5' else 'C'}{v if n!='combo_all5' else ''}  {LABEL[(n,v)]}",cagr=r['full|2']['cagr'],dd=r['full|2']['dd'],calmar=r['full|2']['calmar'],
             tr=r['train|2']['calmar'],oos=r['oos|2']['calmar'],c5=r['full|5']['calmar'],net=r['full|2']['net'],pf=r['full|2']['pf'],passed=x['passed'],
             nft=r['full|2']['no_follow_through']['loss'],gb=r['full|2']['giveback_ge1r']['loss'],loss=r['full|2']['loss_sum'],curve=x['curve']))
R=pd.DataFrame(rows);b=base['full|2']
R.drop(columns='curve').to_csv(D/'summary.csv',index=False)

# 1. Calmar of every variant vs baseline
fig,ax=plt.subplots(figsize=(9,6.2));o=R.iloc[::-1]
cols=[GREEN if p else BASE for p in o.passed];ax.barh(o.label,o.calmar,color=cols,height=.62)
ax.axvline(b['calmar'],color=RED,lw=2,ls='--');ax.text(b['calmar']+.02,len(o)-.45,f"baseline {b['calmar']:.2f}",color=RED,fontsize=9)
for y,(c,p) in enumerate(zip(o.calmar,o.passed)):ax.text(c+.02,y,f"{c:.2f}"+('  PASS' if p else ''),va='center',fontsize=9,color=INK,bbox=dict(fc=SURF,ec='none',pad=1))
ax.set_xlabel('Calmar = CAGR / max drawdown (full period, 2bps slippage)');ax.set_title('Calmar of every tested variant (green = passed all 4 pre-declared gates)',loc='left');ax.grid(axis='y',visible=False)
fig.tight_layout();fig.savefig(OUT/'1_calmar_all_variants.png',dpi=150);plt.close(fig)

# 2. CAGR vs Max DD
fig,ax=plt.subplots(figsize=(9,6))
ax.scatter([b['dd']],[b['cagr']],s=160,color=RED,zorder=3,edgecolor=SURF,lw=2);ax.annotate('BASELINE',(b['dd'],b['cagr']),xytext=(8,6),textcoords='offset points',color=RED,fontweight='bold')
for _,r in R.iterrows():
    ax.scatter(r.dd,r.cagr,s=90,color=GREEN if r.passed else BASE,zorder=3,edgecolor=SURF,lw=2);ax.annotate(r.label.split('  ')[0],(r.dd,r.cagr),xytext=(6,-3),textcoords='offset points',fontsize=9,color=INK2)
xs=np.linspace(15,45,10)
for k in (1,1.5,2):ax.plot(xs,k*xs,color=MUTED,lw=.8,ls=':');x0=min(44,47/k);ax.text(x0,k*x0+.6,f'Calmar {k}',fontsize=8,color=MUTED,ha='right')
ax.set_xlim(15,45);ax.set_ylim(15,50);ax.set_xlabel('Max drawdown % (lower is better)');ax.set_ylabel('CAGR % (higher is better)')
ax.set_title('Return vs drawdown, full 5 years (up-left is better)',loc='left');fig.tight_layout();fig.savefig(OUT/'2_cagr_vs_dd.png',dpi=150);plt.close(fig)

# 3. Equity small multiples: best variant of each idea vs baseline
bt,beq=curve(base['curve']);fig,axs=plt.subplots(2,3,figsize=(13,7),sharex=True,sharey=True)
for ax,n in zip(axs.flat,TITLES):
    d=ideas[n];v=max(d['variants'],key=lambda k:d['variants'][k]['results']['full|2']['calmar']);t,eq=curve(d['variants'][v]['curve'])
    ax.plot(bt,beq,color=BASE,lw=1.6,label='baseline');ax.plot(t,eq,color=BLUE,lw=2,label=f'{v}: {LABEL[(n,v)]}');ax.set_yscale('log')
    ax.set_title(TITLES[n],loc='left');ax.legend(fontsize=8,loc='upper left')
for ax in axs[:,0]:ax.set_ylabel('Equity $ (log)')
fig.suptitle('Equity curve: best variant of each idea vs baseline (start $10,000)',x=.01,ha='left',fontweight='bold');fig.tight_layout();fig.savefig(OUT/'3_equity_small_multiples.png',dpi=150);plt.close(fig)

# 4. Equity + drawdown: baseline, idea 2A, combo, post-hoc 2A+5A
sel=[('baseline',base['curve'],BASE),('2A ATR regime filter',ideas['idea2_atr_regime']['variants']['A']['curve'],BLUE),
     ('All 5 combined',ideas['combo_all5']['variants']['BEST']['curve'],ORANGE),('2A+5A (post-hoc)',post['variants']['2A+5A']['curve'],VIOLET)]
fig,(a1,a2)=plt.subplots(2,1,figsize=(11,7.5),sharex=True,gridspec_kw=dict(height_ratios=[2,1]))
for name,c,col in sel:
    t,eq=curve(c);a1.plot(t,eq,color=col,lw=2 if name!='baseline' else 1.6,label=f'{name}  (${eq[-1]-1e4:,.0f})');a2.plot(t,dd(eq),color=col,lw=1.5)
a1.set_yscale('log');a1.set_ylabel('Equity $ (log)');a1.legend(loc='upper left');a1.set_title('Equity and drawdown: baseline vs the strongest candidates',loc='left')
a2.set_ylabel('Drawdown %');a2.axvline(pd.Timestamp('2025-01-01'),color=MUTED,ls=':');a2.text(pd.Timestamp('2025-01-10'),-38,'validation slice →',fontsize=8,color=MUTED)
fig.tight_layout();fig.savefig(OUT/'4_equity_drawdown_top.png',dpi=150);plt.close(fig)

# 5. Train vs validation Calmar
fig,ax=plt.subplots(figsize=(11,5.2));o=R.copy();x=np.arange(len(o));w=.38
ax.bar(x-w/2,o.tr,w-.04,color=BLUE,label='Train 2021-2024');ax.bar(x+w/2,o.oos,w-.04,color=ORANGE,label='Validation 2025-2026')
ax.axhline(base['train|2']['calmar'],color=BLUE,ls='--',lw=1.2);ax.axhline(base['oos|2']['calmar'],color=ORANGE,ls='--',lw=1.2)
ax.text(-.6,base['train|2']['calmar']+.03,'baseline train',color=BLUE,fontsize=8,bbox=dict(fc=SURF,ec='none',pad=1));ax.text(-.6,base['oos|2']['calmar']-.1,'baseline validation',color=ORANGE,fontsize=8,bbox=dict(fc=SURF,ec='none',pad=1))
ax.set_xticks(x,[l.split('  ')[0] for l in o.label]);ax.set_ylabel('Calmar');ax.legend(loc='upper right');ax.set_xlim(-.7,len(o)-.4);ax.grid(axis='x',visible=False)
ax.set_title('Is the gain stable? Calmar in each slice (dashed = baseline)',loc='left');fig.tight_layout();fig.savefig(OUT/'5_train_vs_validation.png',dpi=150);plt.close(fig)

# 6. Loss anatomy
fig,ax=plt.subplots(figsize=(11,5.2));o=pd.concat([pd.DataFrame([dict(label='BASE',nft=b['no_follow_through']['loss'],gb=b['giveback_ge1r']['loss'],loss=b['loss_sum'])]),R[['label','nft','gb','loss']]])
x=np.arange(len(o));lab=[l.split('  ')[0] for l in o.label]
ax.bar(x,-o.nft/1e3,.62,color=RED,label='No follow-through (MFE<0.5R)');ax.bar(x,-o.gb/1e3,.62,bottom=-o.nft/1e3+.3,color=YELLOW,label='Gave back >=1R')
ax.bar(x,-(o.loss-o.nft-o.gb)/1e3,.62,bottom=-(o.nft+o.gb)/1e3+.6,color=BASE,label='Other losses')
ax.set_xticks(x,lab);ax.set_ylabel('Sum of losing positions, $k');ax.legend(loc='upper right');ax.grid(axis='x',visible=False)
ax.set_title('Where the losses went (full period; lower bar = less total loss)',loc='left');fig.tight_layout();fig.savefig(OUT/'6_loss_anatomy.png',dpi=150);plt.close(fig)

# 7. ATR filter sensitivity heatmap
s=json.loads((D/'posthoc_atr_sensitivity.json').read_text())['variants'];thr=sorted({v['variant']['thr'] for v in s.values()});win=sorted({v['variant']['win'] for v in s.values()})
M=np.array([[next(x['results']['full|2']['calmar'] for x in s.values() if x['variant']['thr']==t and x['variant']['win']==w) for t in thr] for w in win])
fig,ax=plt.subplots(figsize=(8,3.6));im=ax.imshow(M,cmap='Blues',vmin=.8,vmax=2.0,aspect='auto')
for i in range(len(win)):
    for j in range(len(thr)):ax.text(j,i,f'{M[i,j]:.2f}',ha='center',va='center',color='white' if M[i,j]>1.5 else INK,fontsize=10)
ax.set_xticks(range(len(thr)),[f'>= {t}' for t in thr]);ax.set_xlabel('ATR / median ATR threshold');ax.set_yticks(range(len(win)),[f'median of {w} bars' for w in win]);ax.grid(False)
ax.set_title(f"ATR filter neighbourhood, Calmar (baseline {b['calmar']:.2f}; 1.0/60 = tested idea)",loc='left');fig.colorbar(im,ax=ax,shrink=.8)
fig.tight_layout();fig.savefig(OUT/'7_atr_sensitivity.png',dpi=150);plt.close(fig)
print('charts in',OUT)
