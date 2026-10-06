"""One shared MTM equity pool; closed 4h signals; proven baseline costs.
Quantity precision is the frozen benchmark abstraction, not historical LOT_SIZE.
Mark-price liquidation and historical maintenance tiers are not reconstructed.
"""
import numpy as np, math
from numba import njit
@njit(cache=True)
def equity(balance,p,marks):
 eq=balance
 for s in range(len(p)):
  if p[s,0]:eq+=p[s,0]*(marks[s]-p[s,1])*p[s,2]-(p[s,1]+marks[s])*p[s,2]*.0006
 return eq
@njit(cache=True)
def close(s,raw,ts,reason,p,t,balance,daily,nd):
 sign,entry,qty=p[s,0],p[s,1],p[s,2];price=raw*(1-sign*.0002)
 gross=sign*(price-entry)*qty;fee=(entry+price)*qty*.0006;k=int(p[s,5])
 t[k,2]=ts;t[k,8]=price;t[k,9]=gross;t[k,10]=fee;t[k,12]+=gross-fee;t[k,13]=reason
 balance+=gross-fee;daily[nd,0]=ts;daily[nd,1]=gross-fee;nd+=1;p[s,:]=0
 return balance,nd
@njit(cache=True)
def simulate(prices,funding,signals,bars,start,begin,end,risk,cap,slots,close_only,reverse=False,proxy=.0001):
 ns=len(prices);capacity=signals.shape[1]*ns+10
 p=np.zeros((ns,7));t=np.zeros((capacity,17));daily=np.zeros((capacity,2));marks=np.zeros(ns)
 curve=np.full(((end-begin+59)//60+2,3),np.nan)
 balance=10000.;peak=10000.;dd=0.;nt=0;nd=0;reject=0;slotreject=0;marginreject=0;proxies=0;maxopen=0;maxmargin=0.;maxgross=0.
 for i in range(begin,end):
  ts=start+i*60000
  for s in range(ns):
   marks[s]=prices[s,i,0]
   if p[s,0]:
    flow=0.;k=int(p[s,5])
    if np.isfinite(funding[s,i]):flow=-p[s,0]*marks[s]*p[s,2]*funding[s,i]
    elif ts>=1790812800000 and ts%28800000==0:
     flow=-marks[s]*p[s,2]*proxy;proxies+=1;t[k,16]+=1
    balance+=flow;t[k,11]+=flow;t[k,12]+=flow
  eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  for s in range(ns):
   if p[s,0] and p[s,0]*(marks[s]-p[s,3])<=0:balance,nd=close(s,marks[s],ts,3,p,t,balance,daily,nd)
  if ts%14400000==0:
   b=i//240
   for s in range(ns):
    if not p[s,0]:continue
    sign=p[s,0];line=bars[s,b,0] if sign==1 else bars[s,b,3]
    if sign*(bars[s,b,2]-line)<0:balance,nd=close(s,marks[s],ts+3000,7,p,t,balance,daily,nd)
    elif not close_only:
     p[s,3]=max(p[s,3],line) if sign==1 else min(p[s,3],line)
     if sign*(marks[s]-p[s,3])<=0:balance,nd=close(s,marks[s],ts+3000,3,p,t,balance,daily,nd)
   order=np.argsort(-signals[:,b,3],kind='mergesort')
   for index in range(ns):
    s=order[index];sign,trigger,stop=signals[s,b,0],signals[s,b,1],signals[s,b,2]
    if not sign or p[s,0]:continue
    active=0;reserved=0.;gross=0.
    for j in range(ns):
     if p[j,0]:active+=1;reserved+=p[j,6];gross+=p[j,2]*marks[j]
    if active>=slots:slotreject+=1;continue
    eq=equity(balance,p,marks);dailypnl=0.
    for j in range(nd):
     if daily[j,0]>=ts+3000-86400000:dailypnl+=daily[j,1]
    if eq<=0 or dailypnl<=-eq*.02:continue
    dist=sign*(trigger-stop)
    if stop<=0 or dist<=0 or dist/trigger<.012:reject+=1;continue
    planned=math.floor(min(eq*risk/(dist+trigger*.0012),eq*cap/trigger)*10000+1e-9)/10000
    entry=marks[s]*(1+sign*.0002);dist=sign*(entry-stop)
    if dist<=0 or dist/entry<.012:reject+=1;continue
    available=max(0.,eq-reserved)*5
    qty=math.floor(min(planned,eq*risk/(dist+entry*.0012),eq*cap/entry,available/entry)*10000+1e-9)/10000
    if qty<.0001 or qty*entry<5:marginreject+=1;continue
    p[s,0]=sign;p[s,1]=entry;p[s,2]=qty;p[s,3]=stop;p[s,4]=dist;p[s,5]=nt;p[s,6]=entry*qty/5
    t[nt,0]=s;t[nt,1]=ts+3000;t[nt,3]=sign;t[nt,4]=entry;t[nt,5]=qty;t[nt,6]=stop;t[nt,7]=dist;t[nt,14]=eq;t[nt,15]=(dist+entry*.0012)*qty;nt+=1
    maxopen=max(maxopen,active+1);maxmargin=max(maxmargin,(reserved+p[s,6])/eq);maxgross=max(maxgross,(gross+entry*qty)/eq)
    oldmark=marks[s];marks[s]=entry;eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak);marks[s]=oldmark
  for phase in range(3):
   offsets=(20000,40000,59999)
   for s in range(ns):
    o,h,l,c=prices[s,i,0],prices[s,i,1],prices[s,i,2],prices[s,i,3]
    if not p[s,0]:marks[s]=c;continue
    adverse=(p[s,0]==1)!=reverse;path=np.array([o,l if adverse else h,h if adverse else l,c]);first,last=path[phase],path[phase+1];sl=p[s,3]
    if p[s,0]*(last-sl)<=0:
     fraction=min(1.,max(0.,abs((sl-first)/(last-first)))) if first!=last else 0.
     before=0 if phase==0 else offsets[phase-1];fillts=int(ts+before+(offsets[phase]-before)*fraction)
     marks[s]=sl;eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
     balance,nd=close(s,sl,fillts,3,p,t,balance,daily,nd)
    marks[s]=last
   eq=equity(balance,p,marks);peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
  if (i-begin+1)%60==0:
   row=(i-begin+1)//60;curve[row,0]=ts+59999;curve[row,1]=equity(balance,p,marks);curve[row,2]=balance
 for s in range(ns):
  if p[s,0]:balance,nd=close(s,prices[s,end-1,3],start+end*60000-1,8,p,t,balance,daily,nd)
 peak=max(peak,balance);dd=max(dd,(peak-balance)/peak);curve[-1]=np.array([start+end*60000-1,balance,balance])
 return np.array([balance,dd,reject,slotreject,marginreject,proxies,maxopen,maxmargin,maxgross]),t[:nt],curve
