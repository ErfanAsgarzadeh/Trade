"""Copied unchanged (apart from this line) from branch claude/optimistic-newton-ovy9ap @ 19e8b43 (high_cagr/ideas/dd_engine.py).
Shared-account replay with dynamic (path-dependent) risk control, for the drawdown study.
Identical to five_year_report.replay when ctrl is empty (checked in dd_lab.py). Every control uses only information known at
the moment it acts (account equity marked to the current close, open positions, past daily equity, a daily multiplier array
g whose value for day d was computed from data up to the close of day d-1).
ctrl keys (all optional):
  scale      constant risk multiplier
  ddt        (d0, d1, floor): risk x1 while the account drawdown from its high-water mark is < d0, falling linearly to `floor`
             at d1 and beyond (drawdown measured at each entry, marked to market; high-water mark from daily closes and entries)
  heat       max total open risk (sum of entry risk $ / equity); a new trade is shrunk to fit, skipped below 25% of plan
  side_heat  same cap for open risk on the trade's side (long or short)
  vt         (target daily vol, lookback days, lo, hi): risk x clip(target / realised vol of daily account returns, lo, hi)
  eqma       (N days, mult): risk x mult while equity is below its N-day average
  g          array[DAYS] daily multiplier (regime / AI model), applied to entries of day d
  breaker    (x, cut): at a daily close, if drawdown > x, cut every open position by `cut` (once per drawdown episode,
             re-armed at a new high-water mark); the cut part is closed at that close with 0.06% fee + 2 bps
  bots       dict bot -> extra multiplier
  gb         dict bot -> array[DAYS]: per-bot daily multiplier (per-bot AI), multiplied with g
  ddopen     (d0, d1, floor[, N]): optional N = drawdown measured from the highest daily close of the last N days
             (instead of the all-time high-water mark), so the brake releases as the account recovers; hard drawdown brake that also acts on OPEN positions - the multiplier f(dd) (as ddt) is applied
             to new trades and, at each daily close, open positions are cut to f(dd)/f_at_entry when lower (works with gopen)
  ddnew      False: the brake acts only on positions that are open when it deepens (a position is cut by f_now/f_at_entry);
             new trades are not shrunk by it, so the account can catch the recovery
  botdd      (N, thr, mult): per-bot losing streak control - if the sum of the R results (pnl / entry risk $) of that bot's
             last N CLOSED trades is below thr, its new trades get x mult
  gopen      True: open positions follow g too - at the close of day d, a position opened with g-multiplier k is cut to
             g[d+1]/k of its size when g[d+1] < k (never increased); the cut part is closed at that close like the breaker
"""
import numpy as np,pandas as pd
from high_cagr.ideas import three_bots_replay as TB, five_year_report as FY
FEE_RT=FY.FEE_RT;SLIP=FY.SLIP_ALLOW;LEV=FY.LEV;SEED=FY.SEED;DAYS=FY.DAYS

def replay(legs,ctrl=None,margin_cap=.8,start_day=0):
    c=ctrl or {};risk=TB.DEFAULT;L=legs
    ev=[(l['em'],1,i) for i,l in enumerate(L)]+[(l['xm'],0,i) for i,l in enumerate(L)]+[((d+1)*1440-1,2,d) for d in range(start_day,DAYS)]
    ev.sort(key=lambda e:(e[0],e[1]))
    realized=0.;open_={};qty={};rk={};skipped=set();daily=np.zeros(DAYS);trades=[];hwm=SEED;armed=True;ncut=0;gk={};fdd_e={};go=c.get('gopen');dop=c.get('ddopen');dnew=c.get('ddnew',True);bdd=c.get('botdd');bR={}
    g=c.get('g');gb=c.get('gb') or {};ddt=c.get('ddt');heat=c.get('heat');sheat=c.get('side_heat');vt=c.get('vt');eqma=c.get('eqma');brk=c.get('breaker');bm=c.get('bots',{});sc=c.get('scale',1.)
    def equity(m):
        u=0.
        for i in open_:
            l=L[i];u+=qty[i]*l['side']*(TB.closes(l['coin'])[m]-l['entry'])
        return SEED+realized+u
    def fdd(eq,day):
        if not dop:return 1.
        d0,d1,fl=dop[:3];ref=hwm
        if len(dop)>3 and day-start_day>0:ref=max(eq,daily[max(start_day,day-dop[3]):day].max())
        dd=1-eq/ref;return 1. if dd<=d0 else max(fl,1-(1-fl)*(dd-d0)/max(d1-d0,1e-9))
    def used():return sum(qty[i]*L[i]['entry']/LEV for i in open_)
    for m,typ,i in ev:
        if typ==0:
            if i in open_:
                l=L[i];p=qty[i]*l['unit'];realized+=p;bR.setdefault(l['bot'],[]).append(p/max(rk[i],1e-9));trades.append((l['bot'],l['coin'],l['side'],l['em'],l['xm'],qty[i]*l['entry'],p));del open_[i];del rk[i];gk.pop(i,None);fdd_e.pop(i,None)
        elif typ==1:
            l=L[i]
            if l['is_add'] and l['root'] in skipped:continue
            if l.get('skip'):skipped.add(l['root']);continue
            eq=equity(m)
            if eq<=0:skipped.add(l['root']);continue
            hwm=max(hwm,eq);d=m//1440;k=sc*bm.get(l['bot'],1.)
            gv=(g[d] if g is not None else 1.)*(gb[l['bot']][d] if l['bot'] in gb else 1.)*(fdd(eq,d) if dnew else 1.);k*=gv
            if bdd:
                h=bR.get(l['bot'],[])
                if len(h)>=bdd[0] and sum(h[-bdd[0]:])<bdd[1]:k*=bdd[2]
            if ddt:
                dd=1-eq/hwm;d0,d1,fl=ddt;k*=1. if dd<=d0 else max(fl,1-(1-fl)*(dd-d0)/max(d1-d0,1e-9))
            if vt and d-start_day>vt[1]:
                x=daily[d-vt[1]:d];r=x[1:]/x[:-1]-1;s=r.std()
                if s>0:k*=float(np.clip(vt[0]/s,vt[2],vt[3]))
            if eqma and d-start_day>eqma[0]:
                if eq<daily[d-eqma[0]:d].mean():k*=eqma[1]
            if k<=0:skipped.add(l['root']);continue
            per=l['stop_frac']+FEE_RT+SLIP;notional=risk[l['bot']]*l['risk_scale']*k*eq/per;plan=notional
            if heat:notional=min(notional,max(0.,heat*eq-sum(rk.values()))/per)
            if sheat:notional=min(notional,max(0.,sheat*eq-sum(v for j,v in rk.items() if L[j]['side']==l['side']))/per)
            if notional<.25*plan:skipped.add(l['root']);continue
            free=max(0.,margin_cap*eq-used())/(1+margin_cap*LEV*FEE_RT)*LEV
            notional=min(notional,free)
            if notional<20:skipped.add(l['root']);continue
            qty[i]=notional/l['entry'];open_[i]=1;rk[i]=notional*per;gk[i]=gv;fdd_e[i]=fdd(eq,d)
        else:
            eq=equity(m)
            if eq>hwm:hwm=eq;armed=True
            if brk and armed and 1-eq/hwm>brk[0] and open_:
                for j in list(open_):
                    l=L[j];px=TB.closes(l['coin'])[m];cq=qty[j]*brk[1]
                    realized+=cq*(l['side']*(px-l['entry'])-(l['entry']+px)*.0006-px*2e-4);qty[j]-=cq;rk[j]*=1-brk[1]
                armed=False;ncut+=1;eq=equity(m)
            if (go or dop) and i+1<DAYS and open_:
                fd=fdd(eq,i)
                for j in list(open_):
                    bj=L[j]['bot'];gn=((g[i+1] if g is not None else 1.)*(gb[bj][i+1] if bj in gb else 1.) if go else gk[j]/(max(fdd_e[j],1e-9) if dnew else 1.))*(fd if dnew else min(1.,fd/max(fdd_e[j],1e-9)))
                    if gn<gk[j]-1e-9:
                        l=L[j];px=TB.closes(l['coin'])[m];f=1-gn/gk[j];cq=qty[j]*f
                        realized+=cq*(l['side']*(px-l['entry'])-(l['entry']+px)*.0006-px*2e-4);qty[j]-=cq;rk[j]*=1-f;gk[j]=gn;fdd_e[j]=fd
                eq=equity(m)
            daily[i]=eq
    return dict(daily=daily,ncut=ncut,trades=pd.DataFrame(trades,columns=['bot','coin','side','entry_min','exit_min','notional','pnl']))

def period(legs,mult,a,b,ctrl=None):
    lg=[]
    for l,m in zip(legs,mult):
        if l['em']<a or (b is not None and l['em']>=b):continue
        lg.append(dict(l,risk_scale=l['risk_scale']*m,skip=m<=0))
    r=replay(lg,ctrl,start_day=a//1440);d=r['daily'][a//1440:(b//1440 if b else DAYS)];return stats(d,a//1440,r['trades'],r['ncut'])

def stats(d,d0,t=None,ncut=0):
    yrs=len(d)/365.25;dd=(d/np.maximum.accumulate(d)-1).min()*100;cagr=((d[-1]/SEED)**(1/yrs)-1)*100
    idx=pd.date_range(FY.START_DATE+pd.Timedelta(days=d0),periods=len(d));s=pd.Series(d,idx);yd={}
    for y,x in s.groupby(s.index.year):
        prev=s[s.index<pd.Timestamp(f'{y}-01-01')];st=prev.iloc[-1] if len(prev) else SEED;v=np.concatenate([[st],x.values])
        yd[str(y)]=dict(dd=float((v/np.maximum.accumulate(v)-1).min()*100),ret=float((v[-1]/v[0]-1)*100))
    me=s.resample('ME').last();mo=(me/me.shift(1).fillna(SEED)-1)*100
    return dict(final=float(d[-1]),cagr=float(cagr),dd=float(dd),calmar=float(cagr/-dd) if dd<0 else np.inf,years=yd,mpos=float((mo>0).mean()*100),mworst=float(mo.min()),
                trades=int(len(t)) if t is not None else 0,ncut=ncut,daily=d)
