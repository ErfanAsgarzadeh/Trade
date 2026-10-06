"""JIT minute execution kernel. No indicators use future or open candles."""
import math
import numpy as np
from numba import njit

# p: state, sign, entry, qty, SL, initialSL, trigger, cancel, expiry,
# tpEvent, R, riskBudget, cap, confirmed, tradeIndex, hardTP, signalTime
# a: balance, highWater, maxDD, dailyPnL, dailyHead, fillCount, tradeCount,
# funding, setupCount, cancelled, minStopRejected, missingFunding
# cfg: tpRR, partialPct, exitKind (0 baseline/1 A quarter/2 A confirm/3 B/4 pure),
# trailATR, trailTF (60/240 minutes), hardRR, minStop, stopPolicy(0 none/1 widen/2 reject)

@njit(cache=True)
def observe(price,p,a):
    eq=a[0]
    if p[0]>=2:
        eq+=p[1]*(price-p[2])*p[3]-(p[2]+price)*p[3]*.0012/2
    a[1]=max(a[1],eq)
    if a[1]>0:a[2]=max(a[2],(a[1]-eq)/a[1])
    return eq

@njit(cache=True)
def daily(timestamp,a,fills):
    head=int(a[4]);count=int(a[5])
    while head<count and fills[head,0]<timestamp-86400000:
        a[3]-=fills[head,6];head+=1
    a[4]=head
    return a[3]

@njit(cache=True)
def action(kind,raw,timestamp,p,a,trades,fills,cfg):
    if kind==2:
        p[0]=0;a[9]+=1;return
    if kind==1:
        if a[0]<=0 or daily(timestamp,a,fills)<=-a[0]*.02:
            p[0]=0;a[9]+=1;return
        price=raw*(1+p[1]*.0002)
        distance=p[1]*(price-p[5])
        if distance<=0:
            p[0]=0;a[9]+=1;return
        if cfg[6]>0 and cfg[7]==2 and distance/price<cfg[6]:
            p[0]=0;a[10]+=1;return
        qty=math.floor(min(p[3],min(p[11],a[0]*.005)/(distance+price*.0012),p[12]/price)*10000+1e-9)/10000
        if qty<.0001 or qty*price<5:
            p[0]=0;a[9]+=1;return
        p[0]=3 if cfg[2]==4 else 2;p[2]=price;p[3]=qty;p[10]=distance
        p[9]=0. if cfg[2]==5 else price+p[1]*cfg[0]*distance;p[13]=0
        p[15]=price+p[1]*cfg[5]*distance if cfg[5]>0 else 0
        index=int(a[6]);a[6]+=1;p[14]=index
        trades[index,0]=timestamp;trades[index,2]=p[1];trades[index,3]=price
        trades[index,4]=qty;trades[index,5]=p[5];trades[index,6]=distance;trades[index,16]=p[16]
        observe(price,p,a);return
    if kind==5:
        # B: no partial exit; BE is activated only at the 2R milestone.
        p[0]=3;p[13]=1;p[4]=max(p[4],p[2]) if p[1]==1 else min(p[4],p[2])
        trades[int(p[14]),13]=1;return
    price=raw*(1-p[1]*.0002)
    qty=p[3];partial=kind==4
    if partial:
        qty=math.floor(p[3]*cfg[1]*10000+1e-9)/10000
        remaining=p[3]-qty
        if qty<.0001 or qty*price<5 or remaining<.0001 or remaining*price<5:
            partial=False;qty=p[3]
    gross=p[1]*(price-p[2])*qty;fees=(p[2]+price)*qty*.0012/2;net=gross-fees
    a[0]+=net;a[3]+=net
    fi=int(a[5]);a[5]+=1
    fills[fi,0]=timestamp;fills[fi,1]=p[14];fills[fi,2]=qty;fills[fi,3]=price
    fills[fi,4]=gross;fills[fi,5]=fees;fills[fi,6]=net;fills[fi,7]=kind
    ti=int(p[14]);trades[ti,7]+=gross;trades[ti,8]+=fees;trades[ti,10]+=net
    if partial:
        p[3]-=qty;p[0]=3;trades[ti,13]=1
        if cfg[2]==0:p[4]=p[2];p[13]=1
        elif cfg[2]==1:p[4]=p[2]-p[1]*.25*p[10];p[13]=1
        else:p[13]=0
    else:
        trades[ti,1]=timestamp;trades[ti,11]=kind;trades[ti,12]=p[0]
        trades[ti,15]=a[0];p[0]=0
    observe(raw,p,a)

@njit(cache=True)
def point(price,timestamp,p,a,trades,fills,cfg):
    if p[0]==0:return
    if p[0]==1:
        if timestamp>=p[8] or p[1]*(price-p[7])<=0:action(2,price,timestamp,p,a,trades,fills,cfg)
        elif p[1]*(price-p[6])>=0:action(1,price,timestamp,p,a,trades,fills,cfg)
        return
    if p[1]*(price-p[4])<=0:
        action(3,price,timestamp,p,a,trades,fills,cfg);return
    if p[0]==2 and p[9]>0 and p[1]*(price-p[9])>=0:
        action(5 if cfg[2]==3 else 4,price,timestamp,p,a,trades,fills,cfg)
    if p[0]>=2 and p[15]>0 and p[1]*(price-p[15])>=0:
        action(6,price,timestamp,p,a,trades,fills,cfg)

@njit(cache=True)
def segment(first,last,start,end,p,a,trades,fills,cfg):
    current=first
    for _ in range(6):
        if p[0]==0 or current==last:break
        best=math.inf;level=0.;kind=0
        if p[0]==1:
            levels=np.array([p[6],p[7],0.])
            kinds=np.array([1,2,0])
        else:
            levels=np.array([p[4],p[9] if p[0]==2 else 0.,p[15]])
            kinds=np.array([3,5 if cfg[2]==3 else 4,6])
        for j in range(3):
            x=levels[j];k=kinds[j]
            if x<=0 or k==0 or x==current:continue
            if min(current,last)<=x<=max(current,last):
                favorable=p[1]*(last-current)>0
                if favorable==(k==1 or k==4 or k==5 or k==6):
                    distance=abs(x-current)
                    if distance<best:best=distance;level=x;kind=k
        if kind==0:break
        fraction=abs((level-first)/(last-first)) if last!=first else 0.
        timestamp=int(start+(end-start)*fraction)
        action(kind,level,timestamp,p,a,trades,fills,cfg)
        current=level
    observe(last,p,a)

@njit(cache=True)
def simulate(prices,start_ms,begin,end,sig_indices,sig_values,entry_bars,htf_bars,funding,cfg,entry_minutes,path_reverse=False,trace=False,validity=np.empty(0,dtype=np.int64),funding_proxy=.0001):
    capacity=len(sig_indices)+10
    trades=np.zeros((capacity,17));fills=np.zeros((capacity*3,8))
    p=np.zeros(17);a=np.zeros(12);a[0]=10000.;a[1]=10000.
    curve=np.full((len(prices)//60+2,2),np.nan)
    i=begin
    unknown_start=1790812800000 # 2026-10-01 UTC
    while i<end:
        if p[0]==0:
            k=np.searchsorted(sig_indices,i)
            if k>=len(sig_indices) or sig_indices[k]>=end:break
            i=int(sig_indices[k])
        timestamp=start_ms+i*60000
        opening,high,low,close=prices[i,0],prices[i,1],prices[i,2],prices[i,3]
        if p[0]>=2:
            if not np.isnan(funding[i]):
                flow=-p[1]*opening*p[3]*funding[i]
                a[0]+=flow;a[7]+=flow;trades[int(p[14]),9]+=flow;trades[int(p[14]),10]+=flow
            elif timestamp>=unknown_start and timestamp%28800000==0:
                # A disclosed adverse funding proxy for the unarchived four days.
                flow=-opening*p[3]*funding_proxy
                a[0]+=flow;a[7]+=flow;a[11]+=1
                trades[int(p[14]),9]+=flow;trades[int(p[14]),10]+=flow
        if p[0]==1 and len(validity)>0 and timestamp%(entry_minutes*60000)==0:
            allowed=validity[i//entry_minutes];bit=1 if p[1]==1 else 2
            if allowed & bit == 0:action(2,opening,timestamp+3000,p,a,trades,fills,cfg)
        point(opening,timestamp,p,a,trades,fills,cfg)
        if timestamp%(entry_minutes*60000)==0:
            eb=entry_bars[i//entry_minutes]
            if p[0]==3:
                if cfg[2]==2 and p[13]==0 and p[1]*(eb[2]-p[2])>=2*p[10]:
                    p[13]=1;p[4]=max(p[4],p[2]) if p[1]==1 else min(p[4],p[2])
        if p[0]==3 and timestamp%(int(cfg[4])*60000)==0:
            tb=entry_bars[i//entry_minutes] if int(cfg[4])==entry_minutes else htf_bars[i//240]
            line=tb[0] if p[1]==1 else tb[3]
            if p[1]*(tb[2]-line)<0:
                action(7,opening,timestamp+3000,p,a,trades,fills,cfg)
            elif (cfg[2]!=2 or p[13]==1) and cfg[9]==0:
                candidate=line-p[1]*cfg[3]*tb[1]
                p[4]=max(p[4],candidate) if p[1]==1 else min(p[4],candidate)
                point(opening,timestamp+3000,p,a,trades,fills,cfg)
        if p[0]==0 and timestamp%(entry_minutes*60000)==0:
            k=np.searchsorted(sig_indices,i)
            if k<len(sig_indices) and sig_indices[k]==i and a[0]>0 and daily(timestamp+3000,a,fills)>-a[0]*.02:
                sign,trigger,stop=sig_values[k,0],sig_values[k,1],sig_values[k,2]
                distance=sign*(trigger-stop)
                if cfg[6]>0 and distance/trigger<cfg[6]:
                    if cfg[7]==2:a[10]+=1;i+=1;continue
                    if cfg[7]==1:stop=trigger-sign*cfg[6]*trigger;distance=sign*(trigger-stop)
                qty=math.floor(min(a[0]*.005/(distance+trigger*.0012),a[0]*.5/trigger)*10000+1e-9)/10000
                if qty>=.0001 and qty*trigger>=5:
                    p[0]=1;p[1]=sign;p[2]=trigger;p[3]=qty;p[4]=stop;p[5]=stop;p[6]=trigger;p[7]=stop
                    p[8]=timestamp+entry_minutes*60000 if cfg[8]==0 else 9.e15;p[11]=a[0]*.005;p[12]=a[0]*.5;p[16]=timestamp
                    a[8]+=1
                    if sig_values[k,3]==0:action(1,opening,timestamp+3000,p,a,trades,fills,cfg)
                    else:point(opening,timestamp+3000,p,a,trades,fills,cfg)
        if p[0]>0:
            adverse=(p[1]==1)!=path_reverse
            mid1=low if adverse else high;mid2=high if adverse else low
            segment(opening,mid1,timestamp,timestamp+20000,p,a,trades,fills,cfg)
            segment(mid1,mid2,timestamp+20000,timestamp+40000,p,a,trades,fills,cfg)
            segment(mid2,close,timestamp+40000,timestamp+59999,p,a,trades,fills,cfg)
        eq=observe(close,p,a)
        if trace and ((i+1)%60==0 or p[0]==0):
            curve[(i+1+59)//60,0]=eq;curve[(i+1+59)//60,1]=a[0]
        i+=1
    if p[0]==1:action(2,prices[end-1,3],start_ms+end*60000-1,p,a,trades,fills,cfg)
    elif p[0]>=2:action(8,prices[end-1,3],start_ms+end*60000-1,p,a,trades,fills,cfg)
    if trace:curve[(end+59)//60,0]=a[0];curve[(end+59)//60,1]=a[0]
    return a,trades[:int(a[6])],fills[:int(a[5])],curve
