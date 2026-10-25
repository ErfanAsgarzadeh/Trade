"""Five-year paper account test ($10,000, 2021-10-05 .. 2026-10-04) of the THREE bots as shipped on 2026-10-11, plus the
"withdraw 30% of every month's profit" variant.

Differences from three_bots_replay.py (which this builds on, unchanged):
* Ghoghnous uses the shipped policy C_exhaustion_soft x1.5 (lbank_project/pa_sleeve.py): entry only when volrank < 0.354 AND
  side*(EMA50[t]-EMA50[t-6])/ATR14[t] < 0.146; exit on the raw opposite key reversal / 30-bar time stop / stop;
  planned risk = 0.4% * 1.5 * w, w = (0.75 + 0.25*clip((0.554-volrank)/0.4,0,1)) / 0.7755069444444445 (frozen at the signal bar).
* Shahin and Mojsavar are unchanged since the earlier replay (same configs), so their ledgers are reused.
* The replay can withdraw cash: at the close of the last UTC day of each month, if equity is above the previous month-end
  equity (after that month's withdrawal; $10,000 at the start), withdraw `wd` x that month's profit. Sizes follow the
  reduced equity afterwards.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import three_bots_replay as TB, pabench as PB, pa2_confluence as CF, pabench2 as Q, pa2_exits as EX, xuni as X
from high_cagr import run_suite as rs
OUT=ROOT/'high_cagr/output/ideas/five_year'
NORM=.7755069444444445;VOLMULT=1.5;BASE_RISK=.004;START_DATE=pd.Timestamp('2021-10-05')
DAYS=TB.DAYS;SEED=TB.SEED;FEE_RT=TB.FEE_RT;SLIP_ALLOW=TB.SLIP_ALLOW;LEV=TB.LEV

def pa_soft_legs():
    legs=[]
    for s in PB.OTHER20:
        d=PB.coin(s);side=Q.c1_side(d);n=len(side);g=d['sig'];vr,sl,_,_=CF.feats(d,side)
        with np.errstate(invalid='ignore'):gate=(vr<.354)&(sl<.146)&(side!=0)
        w=np.nan_to_num(np.where(gate,(.75+.25*np.clip((.554-vr)/.4,0,1))/NORM,0.))
        def run(m):
            return EX.engine_x(d['P'],d['fc'],240,side,g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],m,np.full(n,30,np.int64),
                               0.,1.,0.,3.,0.,0,0.,np.zeros(0),np.zeros(0),side.astype(np.int8),PB.FEE,PB.SLIP,PB.RISK,100.,PB.MINSTOP,250)
        A=run(gate.astype(float));B=run(w)
        assert len(A)==len(B) and np.array_equal(A[:,0],B[:,0]) and np.array_equal(A[:,1],B[:,1])
        for i,(r,rb) in enumerate(zip(A,B)):
            dist=PB.RISK*1e4/r[5]-r[6]*(2*PB.FEE+2*PB.SLIP)
            legs.append(dict(bot='pa',coin=s,side=int(r[2]),em=int(r[0]),xm=int(r[1]),entry=float(r[6]),unit=float(r[3]*1e4/r[5]),
                             stop_frac=float(dist/r[6]),risk_scale=float(VOLMULT*rb[5]/r[5]),root=('pa',s,i),is_add=False))
    return legs

@functools.lru_cache(1)
def old_ledgers():return TB.ledgers()

@functools.lru_cache(1)
def soft_pa():return pa_soft_legs()

def ledgers(pa='soft'):
    old=old_ledgers();legs=[l for l in old if l['bot']!='pa']
    return legs+(soft_pa() if pa=='soft' else [l for l in old if l['bot']=='pa'])

def month_ends():
    idx=pd.date_range(START_DATE,periods=DAYS);return np.asarray((idx+pd.Timedelta(days=1)).day==1)

def replay(risk=None,margin_cap=.8,bots=('main','c3','pa'),wd=0.,pa='soft',legs=None):
    """legs: optional custom ledger (same fields; 'skip'=True drops a root and its adds, 'risk_scale' may be rescaled)."""
    risk={**TB.DEFAULT,**(risk or {})};L=[l for l in (ledgers(pa) if legs is None else legs) if l['bot'] in bots];me=month_ends()
    ev=[(l['em'],1,i) for i,l in enumerate(L)]+[(l['xm'],0,i) for i,l in enumerate(L)]+[((d+1)*1440-1,2,d) for d in range(DAYS)]
    ev.sort(key=lambda e:(e[0],e[1]))
    realized=0.;withdrawn=0.;open_={};qty={};skipped=set();daily=np.zeros(DAYS);wdl=np.zeros(DAYS);used_d=np.zeros(DAYS);trades=[];prev=SEED
    def equity(m):
        u=0.
        for i in open_:
            l=L[i];u+=qty[i]*l['side']*(TB.closes(l['coin'])[m]-l['entry'])
        return SEED+realized+u-withdrawn
    def used():return sum(qty[i]*L[i]['entry']/LEV for i in open_)
    for m,typ,i in ev:
        if typ==0:
            if i in open_:
                l=L[i];p=qty[i]*l['unit'];realized+=p;trades.append((l['bot'],l['coin'],l['side'],l['em'],l['xm'],qty[i]*l['entry'],p));del open_[i]
        elif typ==1:
            l=L[i]
            if l['is_add'] and l['root'] in skipped:continue
            if l.get('skip'):skipped.add(l['root']);continue
            eq=equity(m)
            if eq<=0:skipped.add(l['root']);continue
            notional=risk[l['bot']]*l['risk_scale']*eq/(l['stop_frac']+FEE_RT+SLIP_ALLOW)
            free=max(0.,margin_cap*eq-used())/(1+margin_cap*LEV*FEE_RT)*LEV
            notional=min(notional,free)
            if notional<20:skipped.add(l['root']);continue
            qty[i]=notional/l['entry'];open_[i]=1
        else:
            eq=equity(m);used_d[i]=used()/eq if eq>0 else 0.
            if wd>0 and me[i]:
                prof=eq-prev
                if prof>0:wdl[i]=wd*prof;withdrawn+=wdl[i];eq-=wdl[i]
                prev=eq
            daily[i]=eq
    return dict(daily=daily,withdrawals=wdl,margin=used_d,trades=pd.DataFrame(trades,columns=['bot','coin','side','entry_min','exit_min','notional','pnl']))

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    for name,kw in (('old',dict(pa='old')),('soft',{}),('wd30',dict(wd=.3))):
        r=replay(**kw);print(name,'final',round(float(r['daily'][-1]),2),'withdrawn',round(float(r['withdrawals'].sum()),2),'trades',len(r['trades']),flush=True)
        np.save(OUT/f'daily_{name}.npy',r['daily']);np.save(OUT/f'wd_{name}.npy',r['withdrawals']);np.save(OUT/f'margin_{name}.npy',r['margin']);r['trades'].to_csv(OUT/f'trades_{name}.csv',index=False)
