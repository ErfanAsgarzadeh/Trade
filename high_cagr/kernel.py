"""Minute execution, shared equity, one optional risk-funded scale-in per symbol.
Costs match the frozen engine. The new sizing allowance reserves 4bps slippage
without charging it a second time. Stops/fees/funding include both units.
"""
import math
import numpy as np
from numba import njit

@njit(cache=True,nogil=True)
def equity(balance,p,marks):
 out=balance
 for s in range(len(p)):
  for leg in range(2):
   if p[s,leg,0]:out+=p[s,leg,0]*(marks[s]-p[s,leg,1])*p[s,leg,2]-(marks[s]+p[s,leg,1])*p[s,leg,2]*.0006
 return out

@njit(cache=True,nogil=True)
def close_symbol(s,raw,ts,reason,p,t,balance,daily,nd):
 for leg in range(2):
  if not p[s,leg,0]:continue
  sign,entry,qty=p[s,leg,0],p[s,leg,1],p[s,leg,2];exit_price=raw*(1-sign*.0002);k=int(p[s,leg,5])
  gross=sign*(exit_price-entry)*qty;fee=(entry+exit_price)*qty*.0006
  t[k,2]=ts;t[k,8]=exit_price;t[k,9]=gross;t[k,10]=fee;t[k,12]+=gross-fee;t[k,13]=reason
  balance+=gross-fee;daily[nd,0]=ts;daily[nd,1]=gross-fee;nd+=1;p[s,leg,:]=0
 return balance,nd

@njit(cache=True,nogil=True)
def simulate(prices,funding,signals,bars,start,begin,end,risk,slots,entry_minutes,
             pyramid=False,close_only=False,reverse=False,proxy=.0001,
             engaged=.60,sizing_slip=.0004,legacy_cap=0.):
 ns=len(prices);capacity=signals.shape[1]*ns+10
 p=np.zeros((ns,2,7));trades=np.zeros((capacity,19));daily=np.zeros((capacity,2));marks=np.zeros(ns)
 eligible_ts=np.full(ns,-1.);added=np.zeros(ns)
 curve=np.full(((end-begin+59)//60+2,3),np.nan)
 balance=10000.;peak=10000.;dd=0.;nt=0;nd=0;first_daily=0
 rejects=0;slotreject=0;marginreject=0;proxies=0;maxopen=0;maxmargin=0.;maxgross=0.;adds=0
 margin_sum=0.;ratio_sum=0.;active_count=0;active_ratio=0.;position_sum=0.
 for i in range(begin,end):
  ts=start+i*60000
  for s in range(ns):
   marks[s]=prices[s,i,0]
   for leg in range(2):
    if not p[s,leg,0]:continue
    k=int(p[s,leg,5]);flow=0.
    if np.isfinite(funding[s,i]):flow=-p[s,leg,0]*marks[s]*p[s,leg,2]*funding[s,i]
    elif ts>=1790812800000 and ts%28800000==0:
     flow=-marks[s]*p[s,leg,2]*proxy;proxies+=1;trades[k,16]+=1
    balance+=flow;trades[k,11]+=flow;trades[k,12]+=flow
  eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  for s in range(ns):
   if p[s,0,0] and p[s,0,0]*(marks[s]-p[s,0,3])<=0:
    balance,nd=close_symbol(s,marks[s],ts,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
  if ts%(entry_minutes*60000)==0:
   b=i//entry_minutes
   for s in range(ns):
    if not p[s,0,0]:continue
    sign=p[s,0,0];line=bars[s,b,0] if sign==1 else bars[s,b,3]
    if sign*(bars[s,b,2]-line)<0:
     balance,nd=close_symbol(s,marks[s],ts+3000,7,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
    elif not close_only:
     stop=max(p[s,0,3],line) if sign==1 else min(p[s,0,3],line)
     for leg in range(2):
      if p[s,leg,0]:p[s,leg,3]=stop
     if sign*(marks[s]-stop)<=0:
      balance,nd=close_symbol(s,marks[s],ts+3000,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
   order=np.argsort(-signals[:,b,3],kind='mergesort')
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
     for k in range(2):
      if p[j,k,0]:reserved+=p[j,k,6];gross_notional+=p[j,k,2]*marks[j]
    if not scale and active>=slots:slotreject+=1;continue
    eq=equity(balance,p,marks)
    if eq<=0 or dailypnl<=-eq*.02:continue
    dist=sign*(trigger-stop)
    if stop<=0 or dist<=0 or dist/trigger<.012:rejects+=1;continue
    unit_risk=risk*.5 if scale else risk
    if legacy_cap>0:cap=eq*legacy_cap
    else:cap=eq*engaged/slots*5
    planned=math.floor(min(eq*unit_risk/(dist+trigger*(.0012+sizing_slip)),cap/trigger)*10000+1e-9)/10000
    entry=marks[s]*(1+sign*.0002);dist=sign*(entry-stop)
    if dist<=0 or dist/entry<.012:rejects+=1;continue
    available=max(0.,eq*(1. if legacy_cap>0 else engaged)-reserved)*5
    qty=math.floor(min(planned,eq*unit_risk/(dist+entry*(.0012+sizing_slip)),cap/entry,available/entry)*10000+1e-9)/10000
    if qty<.0001 or qty*entry<5:marginreject+=1;continue
    p[s,leg,0]=sign;p[s,leg,1]=entry;p[s,leg,2]=qty;p[s,leg,3]=stop;p[s,leg,4]=dist;p[s,leg,5]=nt;p[s,leg,6]=entry*qty/5
    trades[nt,0]=s;trades[nt,1]=ts+3000;trades[nt,3]=sign;trades[nt,4]=entry;trades[nt,5]=qty;trades[nt,6]=stop;trades[nt,7]=dist;trades[nt,14]=eq;trades[nt,15]=(dist+entry*(.0012+sizing_slip))*qty
    trades[nt,17]=int(p[s,0,5]) if scale else nt;trades[nt,18]=leg
    if scale:added[s]=1;adds+=1
    else:eligible_ts[s]=-1.;added[s]=0
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
     balance,nd=close_symbol(s,sl,fillts,3,p,trades,balance,daily,nd);eligible_ts[s]=-1.;added[s]=0
    marks[s]=last
    if pyramid and p[s,0,0] and eligible_ts[s]<0 and not added[s]:
     sign=p[s,0,0]
     if sign*(last-p[s,0,1])>=2*p[s,0,4] and sign*(p[s,0,3]-p[s,0,1])>=p[s,0,1]*(.0012+sizing_slip):eligible_ts[s]=ts+endoffset
   eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  reserved=0.;active=0
  for s in range(ns):
   if p[s,0,0]:active+=1
   for leg in range(2):
    if p[s,leg,0]:reserved+=p[s,leg,6]
  ratio=reserved/eq if eq>0 else 0.;margin_sum+=reserved;ratio_sum+=ratio;position_sum+=active
  if active:active_count+=1;active_ratio+=ratio
  if (i-begin+1)%60==0:
   row=(i-begin+1)//60;curve[row,0]=ts+59999;curve[row,1]=eq;curve[row,2]=balance
 for s in range(ns):
  if p[s,0,0]:balance,nd=close_symbol(s,prices[s,end-1,3],start+end*60000-1,8,p,trades,balance,daily,nd)
 peak=max(peak,balance);dd=max(dd,(peak-balance)/peak);curve[-1]=np.array([start+end*60000-1,balance,balance])
 return np.array([balance,dd,rejects,slotreject,marginreject,proxies,maxopen,maxmargin,maxgross,adds,ratio_sum/(end-begin),active_ratio/max(1,active_count),position_sum/(end-begin)]),trades[:nt],curve
