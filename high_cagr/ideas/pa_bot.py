"""Third bot: a stand-alone PRICE-ACTION strategy next to the main bot and C3+D. Written and committed BEFORE running;
one run, no tuning afterwards.

QUESTION. Which price-action entry, if any, earns a place as a third bot that trades at the same time as the main bot
(2A+5A, 5 coins, 1.0% risk) and C3+D (10 coins, 0.4% risk) on the same account, and makes the WHOLE account better?

UNIVERSES. Deploy universe = OTHER20: the 20 tested coins that neither the main bot nor C3 trades (no symbol is ever held
by two bots; coins are fixed in advance, never chosen by profit). Generalisation universe = IN15: the bot's 5 coins +
C3's 10 coins (used only as a check, never for deployment).
PERIODS. TRAIN 2021-10-05..2024-12-31 (all choices), VALIDATION 2025-01-01..2026-10-04 (judges only).

ENTRY FAMILIES (19), coded on closed bars only, long side; shorts are the exact mirror (same code on negated prices).
a = ATR14 (Wilder) of the signal bar, trend TR = EMA20 > EMA50 and close > EMA50, pivots = 3-bar fractals usable only
after the 3 later bars closed. STOP = buy-stop entry at the level, valid for the given bars; MKT = next bar open.
 Trend continuation
  H2       Al Brooks High-2: in TR with EMA20 rising, second bar with a higher high after the last 21-bar high
           (<= 15 bars ago); signal bar closes in its upper half. STOP above signal high, 1 bar; stop min(low, prev low)-0.1a
  EMAREJ   pullback to EMA20 in TR (low <= EMA20+0.1a, close > EMA20), close in the top 40% of the bar; STOP above high
  RETEST   break and retest: close broke the last pivot high L within the last 10 bars, no close below L-0.5a since,
           signal bar tests L (low <= L+0.3a), closes above L and up; STOP above high, stop low-0.2a
  INSIDE   inside bar in TR; STOP above the mother bar high, 2 bars; stop mother low-0.1a
  FLAG     pole close[t-5]-close[t-15] >= 4a, flag = last 5 bars within 2a and above the pole's 50% retrace; STOP above
           the flag high, 3 bars; stop flag low-0.1a
  BOS      Dow structure: last two pivot highs and lows both rising; first close above the last pivot high; MKT,
           stop last pivot low-0.2a
  FVG      bullish fair-value gap (low[i] > high[i-2], displacement body >= 1a) in the last 20 bars, unfilled; signal bar
           trades into the gap and closes above its bottom, close > EMA50; STOP above high, stop min(low, gap bottom)-0.2a
 Breakout
  NR7      narrowest range of the last 7 bars, in TR; STOP above its high, 2 bars; stop its low-0.2a
  BOX      last 20 bars range < 4a and close breaks above it; MKT, stop box middle
 Reversal / failure
  PIN      pin bar at support: lower wick >= 2x body and >= 60% of range, close in the top third, low = lowest of 5 bars,
           within 0.5a of one of the last two pivot lows; STOP above high, stop low-0.1a
  ENGULF   bullish engulfing at support (same support test on min(low, prev low)); STOP above high
  DOUBLE   double bottom: last two pivot lows within 0.5a, 5..60 bars apart; first close above the neckline (highest
           high between them) within 30 bars of the second low; MKT, stop lower low-0.2a
  SFP      swing failure / liquidity sweep: low takes out the last pivot low (>= 5 bars old), close back above it in the
           upper half of the bar; STOP above high, stop low-0.1a
  FAKEY    inside bar, then a false break of its low that closes back inside the mother bar; STOP above the inside high,
           2 bars; stop low-0.1a
  TRAP     failed breakdown: one of the last 3 bars closed below the prior 20-bar low, now close back above that level
           (first close); MKT, stop lowest low since the breakdown-0.2a
  WEDGE    three falling pivot lows with shrinking pushes, newest <= 10 bars old; bull bar closing above the prior high;
           STOP above high, stop min(low, last pivot)-0.1a
  CHOCH    change of character: last two pivot highs and lows both falling; first close above the last pivot high; MKT,
           stop lowest low since the last pivot low-0.2a
  KEYREV   outside bar making a new 10-bar low, closing up and in the top 25% of its range; STOP above high
  CLIMAX   climactic bear bar (range > 2a, close < EMA20-3a), next bar bull closing above its middle; STOP above high,
           stop min(both lows)-0.1a
TIMEFRAMES 1h, 4h. EXITS (3): TP1 = fixed 1R target, TP2 = fixed 2R target (both with a 30-bar time stop at a bar
  close), TRAIL = after +1R (bar close) stop to entry + costs, then 3 ATR chandelier on closes; no target.
FILTERS (2): none | HTF = last completed higher-timeframe bar (4h for 1h, 1d for 4h) closed beyond its EMA50 on the
  trade side. -> 19 x 2 x 3 x 2 = 228 configs.
SIMULATION on real 1-minute prices (fills, stops, targets and stop-entry triggers minute by minute; a minute touching both
  stop and target counts as the stop). One position per coin, no new signal while in a trade. Taker 0.06%/side + 2 bps
  slippage on every fill (targets included) + observed funding. Risk 0.5% of a fixed 1e4 base per trade (stop
  distance + cost allowance), notional <= 1.0 x base, skip trades whose stop is < 0.4% of the fill price. Daily
  mark-to-market at UTC day close, series combined by sum (as risk_sweep / c3_portfolio).
ACCOUNT. TWO = main bot at 1.0% (risk_sweep.bot_series) + C3+D at 0.4% (risk_sweep.c3_series) = the deployed pair.
  THREE(x) = TWO + PA series at x% risk (PA series scaled by x/0.5).
SELECTION (TRAIN only):
  S1 eligible: >= 200 TRAIN trades on OTHER20 and TRAIN PA net > 0.
  S2 rank eligible configs by TRAIN Calmar of THREE(0.25); the top 5 go to validation.
VALIDATION gates (each of the 5; all must hold):
  V1 PA alone (OTHER20): validation net > 0 and validation Calmar >= 0.3
  V2 THREE(0.25) validation Calmar >= TWO validation Calmar + 0.05
  V3 THREE(0.25) full-period max DD <= TWO full max DD + 1.0 pp
  V4 IN15 generalisation: PA alone on IN15 has full-period Calmar > 0 AND validation net > 0
  V5 cost stress: PA leg at 5 bps slippage per fill (other two unchanged): THREE(0.25) full Calmar >= TWO full Calmar
  V6 causal: signals on data truncated at 40% / 70% equal the full-data signals before the cut (3 coins, both tfs)
WINNER = highest TRAIN THREE(0.25) Calmar among configs passing V1..V6. PA risk for the winner chosen on TRAIN from
  {0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5}%: highest THREE train Calmar with THREE train DD <= TWO train DD + 2 pp.
  If nothing passes, nothing is added to the bot.
Also reported (information, no decisions): best config of every family, train/validation persistence, correlations of
the PA series with the bot and C3+D, peak combined notional.
"""
from pathlib import Path
import sys,json,itertools,time
import numpy as np,pandas as pd
from numba import njit
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import xuni as X, holdout_test as H, c3bench as B, ltf_search as L
OUT=X.OUT/'pa_bot';SPLIT=X.SPLIT
OTHER20=B.OTHER20;IN15=list(rs.SYMBOLS)+B.MAIN10
FAMS=['H2','EMAREJ','RETEST','INSIDE','FLAG','BOS','FVG','NR7','BOX','PIN','ENGULF','DOUBLE','SFP','FAKEY','TRAP','WEDGE','CHOCH','KEYREV','CLIMAX']
TFS={'1h':60,'4h':240};EXITS={'TP1':1,'TP2':2,'TRAIL':3};FILTS=['none','HTF']
FEE=.0006;SLIP=.0002;RISK=.005;CAP=1.;MINSTOP=.004;HOLD=30
PA_RISKS=[.001,.0015,.002,.0025,.003,.004,.005]

# ---------------------------------------------------------------- data
def prep_dir(s):return ROOT/'high_cagr/prepared' if s in rs.SYMBOLS else X.PREP
def load_coin(s):
    p=np.load(prep_dir(s)/s/'prices.npy',mmap_mode='r');f=np.load(prep_dir(s)/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0
    return np.ascontiguousarray(p,dtype=np.float64),np.concatenate([[0.],np.cumsum(f)])

# ---------------------------------------------------------------- features (causal)
def ema(x,n):return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()
def atr14(h,l,c):
    pc=np.roll(c,1);pc[0]=c[0];tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)));return L.wilder(tr,14)

@njit(cache=True)
def last_pivots(h,l,k):
    """For every bar t: values/indices of the last 3 CONFIRMED pivot highs/lows (pivot i usable from bar i+k)."""
    n=len(h);PH=np.full((n,3),np.nan);PHI=np.full((n,3),-1.);PL=np.full((n,3),np.nan);PLI=np.full((n,3),-1.)
    hv=np.full(3,np.nan);hi=np.full(3,-1.);lv=np.full(3,np.nan);li=np.full(3,-1.)
    for t in range(n):
        i=t-k
        if i>=k:
            isH=True;isL=True
            for j in range(i-k,i+k+1):
                if h[j]>h[i]:isH=False
                if l[j]<l[i]:isL=False
            if isH:
                hv[2]=hv[1];hi[2]=hi[1];hv[1]=hv[0];hi[1]=hi[0];hv[0]=h[i];hi[0]=i
            if isL:
                lv[2]=lv[1];li[2]=li[1];lv[1]=lv[0];li[1]=li[0];lv[0]=l[i];li[0]=i
        PH[t]=hv;PHI[t]=hi;PL[t]=lv;PLI[t]=li
    return PH,PHI,PL,PLI

@njit(cache=True)
def detect(fam,o,h,l,c,a,e20,e50,PH,PHI,PL,PLI):
    """Long signals of family `fam` on (possibly negated) bars. Returns kind (0 none, 1 stop-entry, 2 market),
    level, stop, valid bars."""
    n=len(c);kind=np.zeros(n,np.int8);lev=np.full(n,np.nan);stp=np.full(n,np.nan);val=np.ones(n,np.int64)
    for t in range(60,n):
        A=a[t]
        if not A>0:continue
        rng=max(h[t]-l[t],1e-12);tr=e20[t]>e50[t] and c[t]>e50[t]
        k=0;L_=np.nan;S=np.nan;v=1
        if fam==0:   # H2
            if tr and e20[t]>e20[t-5] and h[t]>h[t-1] and c[t]>(h[t]+l[t])/2:
                p=t-20
                for j in range(t-20,t+1):
                    if h[j]>=h[p]:p=j
                if p<=t-2 and t-p<=15:
                    cnt=0
                    for j in range(p+1,t+1):
                        if h[j]>h[j-1]:cnt+=1
                    if cnt==2:k=1;L_=h[t];S=min(l[t],l[t-1])-.1*A
        elif fam==1: # EMAREJ
            if tr and e20[t]>e20[t-5] and l[t]<=e20[t]+.1*A and c[t]>e20[t] and (c[t]-l[t])/rng>=.6:k=1;L_=h[t];S=l[t]-.1*A
        elif fam==2: # RETEST
            Lv=PH[t,0]
            if Lv==Lv and l[t]<=Lv+.3*A and c[t]>Lv and c[t]>o[t]:
                b=-1
                for j in range(t-1,t-11,-1):
                    if j<=PHI[t,0]:break
                    if c[j]>Lv and c[j-1]<=Lv:b=j;break
                if b>0:
                    ok=True
                    for j in range(b,t+1):
                        if c[j]<Lv-.5*A:ok=False
                    if ok:k=1;L_=h[t];S=l[t]-.2*A
        elif fam==3: # INSIDE
            if tr and h[t]<h[t-1] and l[t]>l[t-1]:k=1;L_=h[t-1];S=l[t-1]-.1*A;v=2
        elif fam==4: # FLAG
            pole=c[t-5]-c[t-15]
            if pole>=4*A:
                fh=h[t-4];fl=l[t-4]
                for j in range(t-4,t+1):
                    fh=max(fh,h[j]);fl=min(fl,l[j])
                if fh-fl<=2*A and fl>c[t-15]+.5*pole:k=1;L_=fh;S=fl-.1*A;v=3
        elif fam==5: # BOS
            if PH[t,1]==PH[t,1] and PL[t,1]==PL[t,1] and PH[t,0]>PH[t,1] and PL[t,0]>PL[t,1] and c[t]>PH[t,0] and c[t-1]<=PH[t,0]:
                k=2;S=PL[t,0]-.2*A
        elif fam==6: # FVG
            if c[t]>e50[t]:
                for i in range(t-1,t-21,-1):
                    if l[i]>h[i-2] and c[i-1]-o[i-1]>=a[i-1]:
                        filled=False
                        for j in range(i+1,t):
                            if l[j]<=l[i]:filled=True
                        if not filled and l[t]<=l[i] and c[t]>h[i-2]:k=1;L_=h[t];S=min(l[t],h[i-2])-.2*A
                        break
        elif fam==7: # NR7
            if tr:
                m=True
                for j in range(t-6,t):
                    if h[j]-l[j]<=rng:m=False
                if m:k=1;L_=h[t];S=l[t]-.2*A;v=2
        elif fam==8: # BOX
            bh=h[t-20];bl=l[t-20]
            for j in range(t-20,t):
                bh=max(bh,h[j]);bl=min(bl,l[j])
            if bh-bl<4*a[t-1] and c[t]>bh:k=2;S=(bh+bl)/2
        elif fam==9 or fam==10: # PIN / ENGULF at support
            lo=l[t] if fam==9 else min(l[t],l[t-1]);sup=False
            for q in range(2):
                if PL[t,q]==PL[t,q] and abs(lo-PL[t,q])<=.5*A:sup=True
            if sup:
                if fam==9:
                    body=abs(c[t]-o[t]);wick=min(o[t],c[t])-l[t];low5=True
                    for j in range(t-4,t):
                        if l[j]<l[t]:low5=False
                    if wick>=2*body and wick>=.6*rng and (c[t]-l[t])/rng>=2/3 and low5:k=1;L_=h[t];S=l[t]-.1*A
                elif c[t-1]<o[t-1] and c[t]>o[t-1] and o[t]<=c[t-1] and c[t]-o[t]>o[t-1]-c[t-1]:k=1;L_=h[t];S=lo-.1*A
        elif fam==11: # DOUBLE
            if PL[t,1]==PL[t,1] and abs(PL[t,0]-PL[t,1])<=.5*A:
                i1=int(PLI[t,0]);i2=int(PLI[t,1])
                if 5<=i1-i2<=60 and t-i1<=30:
                    nk=h[i2]
                    for j in range(i2,i1+1):nk=max(nk,h[j])
                    if c[t]>nk and c[t-1]<=nk:k=2;S=min(PL[t,0],PL[t,1])-.2*A
        elif fam==12: # SFP
            Lv=PL[t,0]
            if Lv==Lv and t-PLI[t,0]>=5 and l[t]<Lv and c[t]>Lv and l[t-1]>=Lv and c[t]>(h[t]+l[t])/2:k=1;L_=h[t];S=l[t]-.1*A
        elif fam==13: # FAKEY
            if h[t-1]<h[t-2] and l[t-1]>l[t-2] and l[t]<l[t-1] and c[t]>l[t-1] and h[t]<=h[t-2]:k=1;L_=h[t-1];S=l[t]-.1*A;v=2
        elif fam==14: # TRAP
            for j in range(t-1,t-4,-1):
                lv=l[j-20]
                for q in range(j-20,j):lv=min(lv,l[q])
                if c[j]<lv:
                    first=True
                    for q in range(j+1,t):
                        if c[q]>lv:first=False
                    if first and c[t]>lv:
                        lo=l[j]
                        for q in range(j,t+1):lo=min(lo,l[q])
                        k=2;S=lo-.2*A
                    break
        elif fam==15: # WEDGE
            if PL[t,2]==PL[t,2] and t-PLI[t,0]<=10:
                d1=PL[t,2]-PL[t,1];d2=PL[t,1]-PL[t,0]
                if d1>0 and d2>0 and d2<d1 and c[t]>o[t] and c[t]>h[t-1]:k=1;L_=h[t];S=min(l[t],PL[t,0])-.1*A
        elif fam==16: # CHOCH
            if PH[t,1]==PH[t,1] and PL[t,1]==PL[t,1] and PH[t,0]<PH[t,1] and PL[t,0]<PL[t,1] and c[t]>PH[t,0] and c[t-1]<=PH[t,0]:
                lo=l[t]
                for q in range(int(PLI[t,0]),t+1):lo=min(lo,l[q])
                k=2;S=lo-.2*A
        elif fam==17: # KEYREV
            lo10=True
            for j in range(t-10,t):
                if l[j]<l[t]:lo10=False
            if h[t]>h[t-1] and l[t]<l[t-1] and lo10 and c[t]>c[t-1] and (c[t]-l[t])/rng>=.75:k=1;L_=h[t];S=l[t]-.1*A
        elif fam==18: # CLIMAX
            if h[t-1]-l[t-1]>2*a[t-1] and c[t-1]<e20[t-1]-3*a[t-1] and c[t]>o[t] and c[t]>(h[t-1]+l[t-1])/2:k=1;L_=h[t];S=min(l[t],l[t-1])-.1*A
        if k>0:kind[t]=k;lev[t]=L_;stp[t]=S;val[t]=v
    return kind,lev,stp,val

def bars_of(p,bm):
    o,h,l,c=L.bars(p,bm);return o,h,l,c

def htf_side(p,bm):
    """+1/-1/0 per bar of timeframe bm: last COMPLETED higher bar (4h for 1h, 1d for 4h) close vs its EMA50."""
    hb=240 if bm==60 else 1440;_,_,_,ch=L.bars(p,hb);up=np.where(ch>ema(ch,50),1,-1).astype(np.int8)
    n=len(p)//bm;close_min=(np.arange(n)+1)*bm;last=close_min//hb-1     # higher bars fully closed by this bar's close
    out=np.zeros(n,np.int8);ok=last>=50;out[ok]=up[np.minimum(last[ok],len(up)-1)];return out

def signals(p,bm,fam):
    """Combined long/short signal arrays for one coin/timeframe: side, kind, level, stop, valid."""
    o,h,l,c=bars_of(p,bm);a=atr14(h,l,c);n=len(c)
    side=np.zeros(n,np.int8);kind=np.zeros(n,np.int8);lev=np.full(n,np.nan);stp=np.full(n,np.nan);val=np.ones(n,np.int64)
    for sg in (1,-1):
        oo,hh,ll,cc=(o,h,l,c) if sg==1 else (-o,-l,-h,-c)
        e20,e50=ema(cc,20),ema(cc,50);PH,PHI,PL,PLI=last_pivots(hh,ll,3)
        k,lv,st,v=detect(FAMS.index(fam),oo,hh,ll,cc,a,e20,e50,PH,PHI,PL,PLI)
        m=(k>0)&(side==0);side[m]=sg;kind[m]=k[m];lev[m]=sg*lv[m];stp[m]=sg*st[m];val[m]=v[m]
    return dict(side=side,kind=kind,lev=lev,stp=stp,val=val,atr=a,c=c)

# ---------------------------------------------------------------- minute engine
@njit(cache=True)
def engine(P,fcum,bm,side,kind,lev,stp,val,atr,cbar,mode,fee,slip,risk,cap,minstop,hold,warm):
    nb=len(side);nm=P.shape[0];out=np.zeros((nb,9));k=0;free=0
    for t in range(warm,nb-1):
        s=side[t]
        if s==0:continue
        m0=(t+1)*bm
        if m0<free or m0>=nm:continue
        em=-1;raw=0.
        if kind[t]==2:em=m0;raw=P[m0,0]
        else:
            lv=lev[t];mend=min((t+1+val[t])*bm,nm)
            for m in range(m0,mend):
                if (s==1 and P[m,2]<=stp[t]) or (s==-1 and P[m,1]>=stp[t]):
                    if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):break     # stop level traded first: cancel
                if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        if em<0:continue
        entry=raw*(1+s*slip);stop=stp[t];dist=s*(entry-stop)
        if not dist/entry>=minstop:continue
        qty=min(risk*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        tp=entry+s*(1. if mode==1 else 2.)*dist if mode<=2 else 0.
        be=entry*(1+s*(2*fee+2*slip));best=-1e300 if s==1 else 1e300;armed=False
        x=-1;xraw=0.;eb=em//bm
        for m in range(em,nm):
            hi=P[m,1];lo=P[m,2];op=P[m,0] if m>em else raw
            if s==1:
                if lo<=stop:xraw=min(op,stop);x=m;break
                if mode<=2 and hi>=tp:xraw=max(op,tp);x=m;break
            else:
                if hi>=stop:xraw=max(op,stop);x=m;break
                if mode<=2 and lo<=tp:xraw=min(op,tp);x=m;break
            if (m+1)%bm==0:                       # bar close
                b=m//bm;cl=P[m,3]
                if mode<=2 and b-eb>=hold:xraw=cl;x=m;break
                if mode==3:
                    best=max(best,cl) if s==1 else min(best,cl)
                    if s*(best-entry)>=dist:armed=True
                    if armed:
                        ns=best-s*3*atr[b]
                        if s*(be-ns)>0:ns=be
                        if s*(ns-stop)>0:stop=ns
        if x<0:x=nm-1;xraw=P[nm-1,3]
        xp=xraw*(1-s*slip);fund=-s*raw*qty*(fcum[x+1]-fcum[em])
        net=s*(xp-entry)*qty-(entry+xp)*qty*fee+fund
        out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=qty;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*qty*fee-fund;k+=1
        free=x+1
    return out[:k]

@njit(cache=True)
def m2m(T,c,days):
    """Daily mark-to-market (fraction of the 1e4 base) from minute-indexed trades; mark = minute close at UTC day end."""
    r=np.zeros(days)
    for i in range(len(T)):
        e,x,side,qty,ent,xp,cost=int(T[i,0]),int(T[i,1]),T[i,2],T[i,5],T[i,6],T[i,7],T[i,8]
        de=min(e//1440,days-1);dx=min(x//1440,days-1);prev=ent
        for d in range(de,dx):
            mark=c[min((d+1)*1440-1,len(c)-1)];r[d]+=side*qty*(mark-prev)/1e4;prev=mark
        r[dx]+=(side*qty*(xp-prev)-cost)/1e4
    return r

# ---------------------------------------------------------------- runs
def run_coin(p,fc,sigs,bm,fam,ex,flt,htf,slip=SLIP):
    g=sigs[(bm,fam)];side=g['side'].copy()
    if flt=='HTF':side[side!=htf[bm]]=0
    return engine(p,fc,bm,side,g['kind'],g['lev'],g['stp'],g['val'],g['atr'],g['c'],EXITS[ex],FEE,slip,RISK,CAP,MINSTOP,HOLD,250)

def universe(coins,days,configs,slip=SLIP):
    """Daily series and train/valid trade counts of every config on a coin list."""
    R={cf:np.zeros(days) for cf in configs};N={cf:[0,0] for cf in configs};split_min=SPLIT*1440
    for s in coins:
        p,fc=load_coin(s);c1=np.ascontiguousarray(p[:,3]);htf={bm:htf_side(p,bm) for bm in TFS.values()};sigs={}
        for cf in configs:
            tf,fam,ex,flt=cf;bm=TFS[tf]
            if (bm,fam) not in sigs:sigs[(bm,fam)]=signals(p,bm,fam)
            T=run_coin(p,fc,sigs,bm,fam,ex,flt,htf,slip)
            if len(T):R[cf]+=m2m(T,c1,days);N[cf][0]+=int((T[:,0]<split_min).sum());N[cf][1]+=int((T[:,0]>=split_min).sum())
        print('  coin',s,flush=True)
    return R,N

def causal_check(coins=('LINKUSDT','CRVUSDT','LTCUSDT'),cuts=(.4,.7)):
    for s in coins:
        p,_=load_coin(s)
        for bm in TFS.values():
            for fam in FAMS:
                full=signals(p,bm,fam)
                for q in cuts:
                    nm=int(len(p)*q)//1440*1440;part=signals(p[:nm],bm,fam);k=len(part['side'])
                    for key in ('side','kind','lev','stp','val'):
                        a_=np.nan_to_num(full[key][:k].astype(float),nan=-9e9);b_=np.nan_to_num(part[key].astype(float),nan=-9e9)
                        if not np.array_equal(a_,b_):return dict(causal=False,coin=s,bm=bm,fam=fam,cut=q,key=key)
    return dict(causal=True)

def two_bots(days):
    from high_cagr.ideas import risk_sweep as RS
    bot=RS.bot_series(.01);c3=RS.c3_series(.004);assert len(bot)==days==len(c3);return bot,c3

def st(r):return X.stats(r)
def row(cf,r,n,two,x=.0025):
    a=st(r);t3=st(two+r*(x/RISK))
    return dict(tf=cf[0],fam=cf[1],exit=cf[2],filter=cf[3],n_train=n[0],n_valid=n[1],
                pa_train_cal=a['train'][0],pa_train_cagr=a['train'][1],pa_train_dd=a['train'][2],pa_valid_cal=a['oos'][0],pa_valid_cagr=a['oos'][1],
                pa_full_cal=a['full'][0],pa_full_cagr=a['full'][1],pa_full_dd=a['full'][2],
                pa_train_net=float(r[:SPLIT].sum()),pa_valid_net=float(r[SPLIT:].sum()),
                three_train_cal=t3['train'][0],three_valid_cal=t3['oos'][0],three_full_cal=t3['full'][0],three_full_cagr=t3['full'][1],three_full_dd=t3['full'][2])

def main():
    t0=time.time();OUT.mkdir(parents=True,exist_ok=True)
    days=len(np.load(X.PREP/OTHER20[0]/'prices.npy',mmap_mode='r'))//1440
    configs=list(itertools.product(TFS,FAMS,EXITS,FILTS));print('configs',len(configs),flush=True)
    cz=causal_check();print('causal',cz,flush=True)
    bot,c3=two_bots(days);two=bot+c3;T2=st(two);res=dict(notes=__doc__,causal=cz,two=T2,bot=st(bot),c3=st(c3))
    print('TWO (bot 1% + C3+D 0.4%):',{k:[round(v,2) for v in x] for k,x in T2.items()},flush=True)
    R,N=universe(OTHER20,days,configs);print('OTHER20 done',round(time.time()-t0),'s',flush=True)
    rows=[row(cf,R[cf],N[cf],two) for cf in configs];D=pd.DataFrame(rows)
    D['corr_bot']=[float(np.corrcoef(R[cf],bot)[0,1]) if R[cf].std()>0 else 0. for cf in configs]
    D['corr_c3']=[float(np.corrcoef(R[cf],c3)[0,1]) if R[cf].std()>0 else 0. for cf in configs]
    D.to_csv(OUT/'all_configs.csv',index=False)
    el=D[(D.n_train>=200)&(D.pa_train_net>0)];top=el.sort_values('three_train_cal',ascending=False).head(5)
    print(f'\neligible {len(el)} of {len(D)}; TWO train Calmar {T2["train"][0]:.2f} valid {T2["oos"][0]:.2f} full {T2["full"][0]:.2f} DD {T2["full"][2]:.1f}%',flush=True)
    cand=[tuple(x) for x in top[['tf','fam','exit','filter']].to_numpy()]
    R15,N15=universe(IN15,days,cand);R5,_=universe(OTHER20,days,cand,slip=.0005)
    res['candidates']={}
    for cf in cand:
        r=R[cf];a=st(r);t3=st(two+r*.5);g=st(R15[cf]);t35=st(two+R5[cf]*.5)
        V=dict(V1=bool(r[SPLIT:].sum()>0 and a['oos'][0]>=.3),V2=bool(t3['oos'][0]>=T2['oos'][0]+.05),V3=bool(t3['full'][2]<=T2['full'][2]+1.),
               V4=bool(g['full'][0]>0 and R15[cf][SPLIT:].sum()>0),V5=bool(t35['full'][0]>=T2['full'][0]),V6=bool(cz['causal']))
        key='|'.join(cf);res['candidates'][key]=dict(pa=a,three=t3,in15=g,three_5bps=t35,n=N[cf],gates=V,passed=all(V.values()))
        print(f"CAND {key}: PA train {a['train'][0]:.2f} valid {a['oos'][0]:.2f} (CAGR {a['oos'][1]:.1f}%) | THREE train {t3['train'][0]:.2f} valid {t3['oos'][0]:.2f} full {t3['full'][0]:.2f} DD {t3['full'][2]:.1f}% | IN15 full {g['full'][0]:.2f} | 5bps {t35['full'][0]:.2f} | {V} PASS={all(V.values())}",flush=True)
    passed=[cf for cf in cand if res['candidates']['|'.join(cf)]['passed']]
    if passed:
        w=passed[0];r=R[w];grid=[]
        for x in PA_RISKS:
            t3=st(two+r*(x/RISK));grid.append(dict(risk=x,train=t3['train'],oos=t3['oos'],full=t3['full']))
        ok=[g_ for g_ in grid if g_['train'][2]<=T2['train'][2]+2.];pick=max(ok,key=lambda g_:g_['train'][0]) if ok else None
        res['winner']=dict(config='|'.join(w),risk_grid=grid,risk_pick=pick)
        print('WINNER','|'.join(w),'risk pick',pick,flush=True)
    else:
        res['winner']=None;print('NO CONFIG PASSES - nothing is added to the bot',flush=True)
    # information: best config per family (by TRAIN THREE Calmar among eligible, else by train PA Calmar)
    fam_best=[]
    for fam in FAMS:
        d=D[D.fam==fam];e=d[(d.n_train>=200)&(d.pa_train_net>0)];b=(e if len(e) else d).sort_values('three_train_cal' if len(e) else 'pa_train_cal',ascending=False).iloc[0]
        fam_best.append(b.to_dict())
    res['family_best']=fam_best;res['persistence_spearman']=float(D.pa_train_cal.rank().corr(D.pa_valid_cal.rank()))
    res['share_positive_both']=float(((D.pa_train_net>0)&(D.pa_valid_net>0)).mean())
    np.savez(OUT/'series.npz',bot=bot,c3=c3,**{'|'.join(cf):R[cf] for cf in cand})
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
    print('\nbest per family:');print(pd.DataFrame(fam_best)[['fam','tf','exit','filter','n_train','n_valid','pa_train_cal','pa_valid_cal','pa_full_cagr','three_train_cal','three_valid_cal','corr_bot','corr_c3']].round(2).to_string(index=False))
    print('spearman train/valid',round(res['persistence_spearman'],2),'share positive both',round(res['share_positive_both'],2),'time',round(time.time()-t0),'s')
if __name__=='__main__':main()
