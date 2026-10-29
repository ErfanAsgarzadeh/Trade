"""Win-rate study: exit-management variants applied to the shipped legs on the real minute path, and the shared-account
replay of any modified ledger.

A variant can only make a leg exit EARLIER (or close part of it earlier) than the original engine did, so it is
evaluated exactly on 1m bars: after the leg's best excursion reaches `arm` R (from the next minute on) a protective
stop sits at entry + `lock` R; if a later minute (before the original exit minute) trades through it the leg exits
there (gap: at the minute open). Optional partial: `pfrac` of the size closes at `ptarget` R if that is touched first.
Costs as the engines: fee 0.06%/side, slippage 2 bps per fill, funding from the cumulative funding series.
"""
from pathlib import Path
import sys,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import five_year_report as FY, xuni as X
from high_cagr.ideas.winrate import ledger as LG
FEE=.0006;SLIP=.0002

def _net(l,m_exit,xraw,qfrac):
    d=LG.coin(l['coin']);s=l['side'];e=l['entry'];xp=xraw*(1-s*SLIP)
    fund=-s*e*(d['fc'][m_exit+1]-d['fc'][l['em']])
    return qfrac*(s*(xp-e)-(e+xp)*FEE+fund)

def modify(l,arm=0.,lock=0.,pfrac=0.,ptarget=0.,bots=('main','c3','pa')):
    """Return (new leg dict, info) for one leg."""
    if l['bot'] not in bots or (arm<=0 and pfrac<=0):return l,None
    P=LG.coin(l['coin'])['P'];s=l['side'];e=l['entry'];risk=e*l['stop_frac'];em,xm=l['em'],l['xm']
    if xm-em<2:return l,None
    seg=P[em:xm];op,hi,lo=seg[:,0],seg[:,1],seg[:,2]
    fav=(hi-e) if s==1 else (e-lo)
    unit=l['unit'];new_xm=xm;rest=1.;part=0.;tag=None
    # partial target
    if pfrac>0:
        lvl=e+s*ptarget*risk;hit=np.nonzero((hi>=lvl) if s==1 else (lo<=lvl))[0]
        if len(hit):
            j=hit[0];xraw=max(op[j],lvl) if s==1 else min(op[j],lvl);part=_net(l,em+j,xraw,pfrac);rest=1-pfrac;tag='partial'
    if arm>0:
        armed=np.nonzero(fav>=arm*risk)[0]
        if len(armed):
            j0=armed[0]+1;lvl=e+s*lock*risk
            if j0<len(seg):
                cross=np.nonzero((lo[j0:]<=lvl) if s==1 else (hi[j0:]>=lvl))[0]
                if len(cross):
                    j=j0+cross[0];xraw=min(op[j],lvl) if s==1 else max(op[j],lvl)
                    new=part+_net(l,em+j,xraw,rest);new_xm=em+j;tag=(tag or '')+'+lock'
                    nl=dict(l);nl['unit']=new;nl['xm']=int(new_xm);return nl,tag
    if pfrac>0 and tag:
        nl=dict(l);nl['unit']=part+rest*unit;return nl,tag
    return l,None

def modified_legs(legs,**kw):
    out=[];n=0
    for l in legs:
        nl,t=modify(l,**kw);out.append(nl);n+=t is not None
    return out,n

def replay_legs(legs,**kw):
    """five_year_report.replay on an arbitrary ledger (same sizing, shared margin cap, daily marks)."""
    old=FY.ledgers
    try:
        FY.ledgers=lambda pa='soft':legs
        return FY.replay(**kw)
    finally:
        FY.ledgers=old

def account_stats(r):
    daily=r['daily'];rr=np.diff(np.concatenate([[FY.SEED],daily]))/np.concatenate([[FY.SEED],daily[:-1]]);st=X.stats(rr)
    t=r['trades'];t=t.assign(win=t.pnl>0)
    wr={b:float(g.win.mean()*100) for b,g in t.groupby('bot')};wr['all']=float(t.win.mean()*100)
    tr=t.entry_min<LG.SPLIT_MIN;wr['train']=float(t.win[tr].mean()*100);wr['valid']=float(t.win[~tr].mean()*100)
    gp=t.pnl[t.pnl>0].sum();gl=-t.pnl[t.pnl<0].sum()
    yrs=pd.Series(daily,index=pd.date_range('2021-10-05',periods=len(daily))).resample('YE').last()
    yearly=(yrs/yrs.shift(1).fillna(FY.SEED)-1)*100
    return dict(final=float(daily[-1]),cagr=st['full'][1],dd=st['full'][2],calmar=st['full'][0],train=st['train'],valid=st['oos'],
                trades=int(len(t)),win_rate=wr,pf=float(gp/gl) if gl>0 else np.inf,yearly={str(k.year):round(float(v),1) for k,v in yearly.items()})
