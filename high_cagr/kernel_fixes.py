"""Ablation kernel: high_cagr.kernel plus three optional, default-off loss-driver fixes.
With every new switch at its default this is bit-identical to high_cagr.kernel.
 #1 cluster cap   same_side_cap / max_new_per_bar (new root entries only; adds are exempt)
 #2 stale guard   stale_bars/stale_mfe/stale_cols: tighten the Donchian10 trail to a shorter channel
 #P pilot entry  pilot_frac<1: root takes that share of the risk; the rest is added (leg 2, same stop)
                 once base MFE reaches pilot_trigger R, as a stop order at that level
 #4 profit floor  floor_on (stop >= entry +/- 0.25R once base MFE>=2R), pyr_risk_mult, pyr_safe
bars columns 0..3 are the original (low line, atr, close, high line); 4/5 and 6/7 are the
3- and 4-bar channel low/high used by the stale guard. MFE is measured on the minute
path points the engine already uses (open, adverse extreme, favourable extreme, close).
"""
import math
import numpy as np
from numba import njit

@njit(cache=True,nogil=True)
def equity(balance,p,marks):
 out=balance
 for s in range(len(p)):
  for leg in range(3):
   if p[s,leg,0]:out+=p[s,leg,0]*(marks[s]-p[s,leg,1])*p[s,leg,2]-(marks[s]+p[s,leg,1])*p[s,leg,2]*.0006
 return out

@njit(cache=True,nogil=True)
def close_symbol(slip,s,raw,ts,reason,p,t,balance,daily,nd):
 for leg in range(3):
  if not p[s,leg,0]:continue
  sign,entry,qty=p[s,leg,0],p[s,leg,1],p[s,leg,2];exit_price=raw*(1-sign*slip);k=int(p[s,leg,5])
  gross=sign*(exit_price-entry)*qty;fee=(entry+exit_price)*qty*.0006
  t[k,2]=ts;t[k,8]=exit_price;t[k,9]=gross;t[k,10]=fee;t[k,12]+=gross-fee;t[k,13]=reason
  balance+=gross-fee;daily[nd,0]=ts;daily[nd,1]=gross-fee;nd+=1;p[s,leg,:]=0
 return balance,nd

@njit(cache=True,nogil=True)
def simulate(prices,funding,signals,bars,start,begin,end,risk,slots,entry_minutes,
             pyramid=False,close_only=False,reverse=False,proxy=.0001,
             engaged=.60,sizing_slip=.0004,legacy_cap=0.,
             same_side_cap=0,max_new_per_bar=0,stale_bars=0,stale_mfe=.40,stale_cols=4,
             floor_on=False,floor_trigger=2.,floor_lock=.25,pyr_risk_mult=.5,pyr_safe=False,slip=.0002,
             vol_max_pct=0.,vol_mid_pct=0.,vol_mid_mult=1.,thr_trigger=0.,thr_resume=0.,thr_mult=1.,
             pilot_frac=1.,pilot_trigger=.5):
 ns=len(prices);capacity=signals.shape[1]*ns+10
 p=np.zeros((ns,3,7));trades=np.zeros((capacity,21));daily=np.zeros((capacity,2));marks=np.zeros(ns)
 eligible_ts=np.full(ns,-1.);added=np.zeros(ns)
 mfe=np.zeros(ns);opened=np.zeros(ns);floored=np.zeros(ns);cap_rejects=0;stale_events=0;pyr_safe_rejects=0;floor_events=0;vol_rejects=0;throttled=False;throttled_units=0;pilot_rem=np.zeros(ns);pilot_adds=0
 curve=np.full(((end-begin+59)//60+2,3),np.nan)
 balance=10000.;peak=10000.;dd=0.;nt=0;nd=0;first_daily=0
 rejects=0;slotreject=0;marginreject=0;proxies=0;maxopen=0;maxmargin=0.;maxgross=0.;adds=0
 margin_sum=0.;ratio_sum=0.;active_count=0;active_ratio=0.;position_sum=0.
 for i in range(begin,end):
  ts=start+i*60000
  for s in range(ns):
   marks[s]=prices[s,i,0]
   for leg in range(3):
    if not p[s,leg,0]:continue
    k=int(p[s,leg,5]);flow=0.
    if np.isfinite(funding[s,i]):flow=-p[s,leg,0]*marks[s]*p[s,leg,2]*funding[s,i]
    elif ts>=1790812800000 and ts%28800000==0:
     flow=-marks[s]*p[s,leg,2]*proxy;proxies+=1;trades[k,16]+=1
    balance+=flow;trades[k,11]+=flow;trades[k,12]+=flow
  eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  for s in range(ns):
   if p[s,0,0] and p[s,0,0]*(marks[s]-p[s,0,3])<=0:
    balance,nd=close_symbol(slip,s,marks[s],ts,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
  if ts%(entry_minutes*60000)==0:
   b=i//entry_minutes
   for s in range(ns):
    if not p[s,0,0]:continue
    sign=p[s,0,0];line=bars[s,b,0] if sign==1 else bars[s,b,3]
    if stale_bars>0 and (ts-opened[s])//(entry_minutes*60000)>=stale_bars and mfe[s]<stale_mfe:
     line=bars[s,b,stale_cols] if sign==1 else bars[s,b,stale_cols+1];stale_events+=1;trades[int(p[s,0,5]),20]+=1
    if sign*(bars[s,b,2]-line)<0:
     balance,nd=close_symbol(slip,s,marks[s],ts+3000,7,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
    elif not close_only:
     stop=max(p[s,0,3],line) if sign==1 else min(p[s,0,3],line)
     for leg in range(3):
      if p[s,leg,0]:p[s,leg,3]=stop
     if sign*(marks[s]-stop)<=0:
      balance,nd=close_symbol(slip,s,marks[s],ts+3000,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
   order=np.argsort(-signals[:,b,3],kind='mergesort');newcount=0
   while first_daily<nd and daily[first_daily,0]<ts+3000-86400000:first_daily+=1
   dailypnl=0.
   for j in range(first_daily,nd):dailypnl+=daily[j,1]
   for index in range(ns):
    s=order[index];sign=signals[s,b,0];trigger=signals[s,b,1];stop=signals[s,b,2]
    if not sign:continue
    scale=False;leg=0
    if p[s,0,0]:
     if (not pyramid or added[s] or sign!=p[s,0,0] or eligible_ts[s]<0 or eligible_ts[s]>=ts
         or sign*(marks[s]-p[s,0,1])<2*p[s,0,4]
         or sign*(p[s,0,3]-p[s,0,1])<p[s,0,1]*(.0012+sizing_slip)):continue
     scale=True;leg=1;stop=p[s,0,3]
    active=0;reserved=0.;gross_notional=0.
    for j in range(ns):
     if p[j,0,0]:active+=1
     for k in range(3):
      if p[j,k,0]:reserved+=p[j,k,6];gross_notional+=p[j,k,2]*marks[j]
    if not scale and active>=slots:slotreject+=1;continue
    if not scale and same_side_cap>0:
     same=0
     for j in range(ns):
      if p[j,0,0]==sign:same+=1
     if same>=same_side_cap:cap_rejects+=1;continue
    if not scale and max_new_per_bar>0 and newcount>=max_new_per_bar:cap_rejects+=1;continue
    eq=equity(balance,p,marks)
    if eq<=0 or dailypnl<=-eq*.02:continue
    dist=sign*(trigger-stop)
    if stop<=0 or dist<=0 or dist/trigger<.012:rejects+=1;continue
    if thr_trigger>0:
     if not throttled and eq<peak*(1-thr_trigger):throttled=True
     elif throttled and eq>=peak*(1-thr_resume):throttled=False
    vol_mult=1.
    if not scale and vol_max_pct>0 and dist/trigger>vol_max_pct:vol_rejects+=1;continue
    if not scale and vol_mid_pct>0 and dist/trigger>vol_mid_pct:vol_mult=vol_mid_mult
    unit_risk=(risk*pyr_risk_mult if scale else risk*vol_mult)*(thr_mult if throttled else 1.)
    full_risk=unit_risk
    if not scale and pilot_frac<1.:unit_risk=unit_risk*pilot_frac
    if throttled:throttled_units+=1
    if legacy_cap>0:cap=eq*legacy_cap
    else:cap=eq*engaged/slots*5
    planned=math.floor(min(eq*unit_risk/(dist+trigger*(.0012+sizing_slip)),cap/trigger)*10000+1e-9)/10000
    entry=marks[s]*(1+sign*slip);dist=sign*(entry-stop)
    if dist<=0 or dist/entry<.012:rejects+=1;continue
    available=max(0.,eq*(1. if legacy_cap>0 else engaged)-reserved)*5
    qty=math.floor(min(planned,eq*unit_risk/(dist+entry*(.0012+sizing_slip)),cap/entry,available/entry)*10000+1e-9)/10000
    if qty<.0001 or qty*entry<5:marginreject+=1;continue
    if scale and pyr_safe:
     x=stop*(1-sign*slip);combined=sign*qty*(x-entry)-.0006*qty*(entry+x)
     for k in (0,2):
      if p[s,k,0]:combined+=sign*p[s,k,2]*(x-p[s,k,1])-.0006*p[s,k,2]*(p[s,k,1]+x)
     if combined<0:pyr_safe_rejects+=1;continue
    p[s,leg,0]=sign;p[s,leg,1]=entry;p[s,leg,2]=qty;p[s,leg,3]=stop;p[s,leg,4]=dist;p[s,leg,5]=nt;p[s,leg,6]=entry*qty/5
    trades[nt,0]=s;trades[nt,1]=ts+3000;trades[nt,3]=sign;trades[nt,4]=entry;trades[nt,5]=qty;trades[nt,6]=stop;trades[nt,7]=dist;trades[nt,14]=eq;trades[nt,15]=(dist+entry*(.0012+sizing_slip))*qty
    trades[nt,17]=int(p[s,0,5]) if scale else nt;trades[nt,18]=leg
    if scale:added[s]=1;adds+=1
    else:eligible_ts[s]=-1.;added[s]=0;mfe[s]=0.;opened[s]=ts;floored[s]=0.;newcount+=1;pilot_rem[s]=eq*full_risk*(1.-pilot_frac) if pilot_frac<1. else 0.
    nt+=1
    maxopen=max(maxopen,active+(0 if scale else 1));maxmargin=max(maxmargin,(reserved+p[s,leg,6])/eq);maxgross=max(maxgross,(gross_notional+entry*qty)/eq)
    oldmark=marks[s];marks[s]=entry;eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak);marks[s]=oldmark
  for phase in range(3):
   endoffset=20000 if phase==0 else (40000 if phase==1 else 59999)
   for s in range(ns):
    o,h,l,c=prices[s,i,0],prices[s,i,1],prices[s,i,2],prices[s,i,3]
    if not p[s,0,0]:marks[s]=c;continue
    adverse=(p[s,0,0]==1)!=reverse
    low_first=l if adverse else h;high_second=h if adverse else l
    first=o if phase==0 else (low_first if phase==1 else high_second)
    last=low_first if phase==0 else (high_second if phase==1 else c)
    sl=p[s,0,3]
    if p[s,0,0]*(last-sl)<=0:
     fraction=min(1.,max(0.,abs((sl-first)/(last-first)))) if first!=last else 0.
     before=0 if phase==0 else (20000 if phase==1 else 40000)
     fillts=int(ts+before+(endoffset-before)*fraction)
     marks[s]=sl;eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
     balance,nd=close_symbol(slip,s,sl,fillts,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
    marks[s]=last
    if p[s,0,0]:
     favourable=p[s,0,0]*(last-p[s,0,1])/p[s,0,4]
     if favourable>mfe[s]:mfe[s]=favourable;trades[int(p[s,0,5]),19]=favourable
     if pilot_rem[s]>0 and p[s,2,0]==0 and mfe[s]>=pilot_trigger:
      sign=p[s,0,0];lvl=p[s,0,1]+sign*pilot_trigger*p[s,0,4];fillraw=first if sign*(first-lvl)>=0 else lvl
      entry=fillraw*(1+sign*slip);stop=p[s,0,3];dist=sign*(entry-stop);rem=pilot_rem[s];pilot_rem[s]=0.
      if dist>0 and dist/entry>=.012:
       eq=equity(balance,p,marks);reserved=0.;notional=0.
       for j in range(ns):
        for k in range(3):
         if p[j,k,0]:reserved+=p[j,k,6]
       for k in range(3):
        if p[s,k,0]:notional+=p[s,k,1]*p[s,k,2]
       cap=eq*legacy_cap if legacy_cap>0 else eq*engaged/slots*5
       available=max(0.,eq*(1. if legacy_cap>0 else engaged)-reserved)*5
       qty=math.floor(min(rem/(dist+entry*(.0012+sizing_slip)),max(0.,cap-notional)/entry,available/entry)*10000+1e-9)/10000
       if qty>=.0001 and qty*entry>=5:
        p[s,2,0]=sign;p[s,2,1]=entry;p[s,2,2]=qty;p[s,2,3]=stop;p[s,2,4]=dist;p[s,2,5]=nt;p[s,2,6]=entry*qty/5
        trades[nt,0]=s;trades[nt,1]=ts+endoffset;trades[nt,3]=sign;trades[nt,4]=entry;trades[nt,5]=qty;trades[nt,6]=stop;trades[nt,7]=dist;trades[nt,14]=eq
        trades[nt,15]=(dist+entry*(.0012+sizing_slip))*qty;trades[nt,17]=int(p[s,0,5]);trades[nt,18]=2;nt+=1;pilot_adds+=1
        maxmargin=max(maxmargin,(reserved+p[s,2,6])/eq)
     if floor_on and not floored[s] and mfe[s]>=floor_trigger:
      floor=p[s,0,1]+p[s,0,0]*floor_lock*p[s,0,4];floored[s]=1.;floor_events+=1
      for leg in range(3):
       if p[s,leg,0]:p[s,leg,3]=max(p[s,leg,3],floor) if p[s,0,0]==1 else min(p[s,leg,3],floor)
    if pyramid and p[s,0,0] and eligible_ts[s]<0 and not added[s]:
     sign=p[s,0,0]
     if sign*(last-p[s,0,1])>=2*p[s,0,4] and sign*(p[s,0,3]-p[s,0,1])>=p[s,0,1]*(.0012+sizing_slip):eligible_ts[s]=ts+endoffset
   eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  reserved=0.;active=0
  for s in range(ns):
   if p[s,0,0]:active+=1
   for leg in range(3):
    if p[s,leg,0]:reserved+=p[s,leg,6]
  ratio=reserved/eq if eq>0 else 0.;margin_sum+=reserved;ratio_sum+=ratio;position_sum+=active
  if active:active_count+=1;active_ratio+=ratio
  if (i-begin+1)%60==0:
   row=(i-begin+1)//60;curve[row,0]=ts+59999;curve[row,1]=eq;curve[row,2]=balance
 for s in range(ns):
  if p[s,0,0]:balance,nd=close_symbol(slip,s,prices[s,end-1,3],start+end*60000-1,8,p,trades,balance,daily,nd)
 peak=max(peak,balance);dd=max(dd,(peak-balance)/peak);curve[-1]=np.array([start+end*60000-1,balance,balance])
 return np.array([balance,dd,rejects,slotreject,marginreject,proxies,maxopen,maxmargin,maxgross,adds,ratio_sum/(end-begin),active_ratio/max(1,active_count),position_sum/(end-begin),cap_rejects,stale_events,pyr_safe_rejects,floor_events,vol_rejects,throttled_units,pilot_adds]),trades[:nt],curve
