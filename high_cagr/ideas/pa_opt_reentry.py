"""pa_opt_reentry: pyramiding / re-entry in good key-reversal trends (PA sleeve).

HYPOTHESIS. Size should be added only after a trend has proven itself. A KEYREV trade that has already moved +1R in our
favour (or that is joined by a second same-direction signal while it is open) is more likely to reach the 2R target than the
unconditional signal, so a second unit risked at the moment of proof, with the whole position's stop moved to breakeven,
should add profit at little extra risk. In addition, a trade that is closed by the 30-bar time stop IN PROFIT is a slow trend;
re-entering on a continuation breakout may capture the rest of it.
MECHANISM. Own engine copy (same minute simulation as pabench.engine2, defaults reproduce pabench.run exactly - asserted in
main() on 3 coins before the run). Position = up to 2 units, all units share the time stop of the first unit.
  add_mode 1 (MFE add): when the first unit's MFE reaches add_r R a stop-order second unit is filled at entry+add_r*dist
    (slippage as usual), risk = add_frac * 0.15% (PA risk), stop of the WHOLE position moved to entry1 + costs (breakeven of
    unit 1; unit 2 therefore risks about add_r R of its own risk unit... its stop is that breakeven), target = target of unit 1.
    add_frac=0 only moves the stop to breakeven (control for the breakeven effect).
  add_mode 2 (signal add): while a position is open and its MFE >= sig_min R, the first new same-side KEYREV signal (its
    stop order, validity and signal stop as in the baseline) opens a second unit with risk add_frac and its own signal stop
    and own 2R target; unit 1 stop moves to breakeven when the add fills.
  reent (re-entry after time stop): if the first unit exits at the 30-bar time stop with a positive raw result, a buy-stop
    (sell-stop) is placed at the highest high (lowest low) of the last 3 bars up to and including the exit bar, valid
    6 bars, stop = exit close -/+ 2 ATR(exit bar), cancelled if the stop is touched first; same 2R/30-bar management, risk
    = 0.15% (full), one re-entry per root. All inputs are bars <= exit bar, causal.
DIAGNOSTIC (train only, does not select parameters): baseline trade outcome mix and how many same-side signals are skipped
while a trade is open; run with 'python pa_opt_reentry.py diag'.
VARIANTS (fixed, 8):
 A0_be_only     add_mode 1, add_r 1, add_frac 0 (breakeven control, no add)
 A_add1_half    add_mode 1, add_r 1, add_frac 0.5
 B_add1_full    add_mode 1, add_r 1, add_frac 1.0
 C_add1_half_t3 add_mode 1, add_r 1, add_frac 0.5, target 3R (shared)
 D_sig_half     add_mode 2, sig_min 0.5, add_frac 0.5
 E_sig_full     add_mode 2, sig_min 1.0, add_frac 1.0
 F_reent        reentry after winning time stop only (no add)
 G_add1h_reent  A_add1_half plus F_reent
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
from numba import njit
from high_cagr.ideas import pabench as PB

@njit(cache=True)
def rec(out,k,em,x,s,xraw,raw,xp,entry,q,dist,fcum,fee,root):
    fund=-s*raw*q*(fcum[x+1]-fcum[em])
    net=s*(xp-entry)*q-(entry+xp)*q*fee+fund
    out[k,0]=em;out[k,1]=x;out[k,2]=s;out[k,3]=net/1e4;out[k,4]=s*(xraw-raw)/dist;out[k,5]=q;out[k,6]=entry;out[k,7]=xp;out[k,8]=(entry+xp)*q*fee-fund;out[k,9]=root
    return k+1

@njit(cache=True)
def sim(P,fcum,bm,s,em,raw,entry,stop,dist,qty,tgt_r,hold,add_mode,add_r,add_frac,sig_min,side,kind,lev,stp,val,fee,slip,risk,cap,minstop,out,k,root,info):
    nm=P.shape[0];act=np.zeros(2,np.bool_);EM=np.zeros(2,np.int64);RAW=np.zeros(2);EN=np.zeros(2);ST=np.zeros(2);TG=np.zeros(2);Q=np.zeros(2);D=np.zeros(2)
    act[0]=True;EM[0]=em;RAW[0]=raw;EN[0]=entry;ST[0]=stop;Q[0]=qty;D[0]=dist;TG[0]=entry+s*tgt_r*dist if tgt_r>0 else 0.
    be=entry*(1+s*(2*fee+2*slip));mfe=0.;ebar=em//bm;tried=False;pend=False;plv=0.;pst=0.;pend_end=0
    info[0]=em;info[1]=0.;info[2]=em;info[3]=0.
    for m in range(em,nm):
        hi=P[m,1];lo=P[m,2]
        for u in range(2):
            if not act[u]:continue
            op=P[m,0] if m>EM[u] else RAW[u];xr=0.;hit=False
            if s==1:
                if lo<=ST[u]:xr=min(op,ST[u]);hit=True
                elif TG[u]>0 and hi>=TG[u]:xr=max(op,TG[u]);hit=True
            else:
                if hi>=ST[u]:xr=max(op,ST[u]);hit=True
                elif TG[u]>0 and lo<=TG[u]:xr=min(op,TG[u]);hit=True
            if hit:
                xp=xr*(1-s*slip);k=rec(out,k,EM[u],m,s,xr,RAW[u],xp,EN[u],Q[u],D[u],fcum,fee,root);act[u]=False
                if m>info[0]:info[0]=m
                if u==0:info[2]=m;info[3]=1. if s*(xr-RAW[0])>0 else 0.
        if not act[0] and not act[1]:return k
        if not act[0]:pend=False
        if act[0]:
            fav=(hi-entry)/dist if s==1 else (entry-lo)/dist
            if fav>mfe:mfe=fav
            if add_mode==1 and not tried and mfe>=add_r:
                tried=True;lvl=entry+s*add_r*dist;op=P[m,0]
                r2=max(op,lvl) if s==1 else min(op,lvl)
                if s*(be-ST[0])>0:ST[0]=be
                if add_frac>0 and not act[1]:
                    e2=r2*(1+s*slip);d2=s*(e2-ST[0])
                    if d2>0 and d2/e2>=minstop:
                        act[1]=True;EM[1]=m;RAW[1]=r2;EN[1]=e2;ST[1]=ST[0];TG[1]=TG[0];D[1]=d2
                        Q[1]=min(risk*add_frac*1e4/(d2+e2*(2*fee+2*slip)),cap*1e4/e2)
            if add_mode==2 and not tried and not pend and m>em and m%bm==0:
                t=m//bm-1
                if t<len(side) and side[t]==s and mfe>=sig_min:
                    pend=True;pst=stp[t]
                    if kind[t]==2:
                        plv=P[m,0];pend_end=min(m+bm,nm)
                    else:
                        plv=lev[t];pend_end=min((t+1+val[t])*bm,nm)
            if pend:
                if m>=pend_end:pend=False;tried=True
                else:
                    lh=(s==1 and hi>=plv) or (s==-1 and lo<=plv)
                    sh=(s==1 and lo<=pst) or (s==-1 and hi>=pst)
                    if sh and not lh:pend=False;tried=True
                    elif lh:
                        pend=False;tried=True;op=P[m,0];r2=max(op,plv) if s==1 else min(op,plv)
                        e2=r2*(1+s*slip);d2=s*(e2-pst)
                        if d2>0 and d2/e2>=minstop and not act[1]:
                            if s*(be-ST[0])>0:ST[0]=be
                            act[1]=True;EM[1]=m;RAW[1]=r2;EN[1]=e2;ST[1]=pst;D[1]=d2;TG[1]=e2+s*tgt_r*d2 if tgt_r>0 else 0.
                            Q[1]=min(risk*add_frac*1e4/(d2+e2*(2*fee+2*slip)),cap*1e4/e2)
        if (m+1)%bm==0:
            b=m//bm
            if hold>0 and b-ebar>=hold:
                cl=P[m,3]
                for u in range(2):
                    if act[u]:
                        xp=cl*(1-s*slip);k=rec(out,k,EM[u],m,s,cl,RAW[u],xp,EN[u],Q[u],D[u],fcum,fee,root);act[u]=False
                        if u==0:info[1]=1.;info[2]=m;info[3]=1. if s*(cl-RAW[0])>0 else 0.
                info[0]=m
                return k
    x=nm-1;cl=P[nm-1,3]
    for u in range(2):
        if act[u]:
            xp=cl*(1-s*slip);k=rec(out,k,EM[u],x,s,cl,RAW[u],xp,EN[u],Q[u],D[u],fcum,fee,root);info[0]=x
            if u==0:info[2]=x
    return k

@njit(cache=True)
def engine3(P,fcum,bm,side,kind,lev,stp,val,atr,h,l,c,target_r,hold,add_mode,add_r,add_frac,sig_min,reent,fee,slip,risk,cap,minstop,warm):
    nb=len(side);nm=P.shape[0];out=np.zeros((6*nb,10));k=0;free=0;root=0;info=np.zeros(4)
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
                    if not ((s==1 and P[m,1]>=lv) or (s==-1 and P[m,2]<=lv)):break
                if s==1 and P[m,1]>=lv:raw=max(P[m,0],lv);em=m;break
                if s==-1 and P[m,2]<=lv:raw=min(P[m,0],lv);em=m;break
        if em<0:continue
        entry=raw*(1+s*slip);stop=stp[t];dist=s*(entry-stop)
        if not dist/entry>=minstop:continue
        qty=min(risk*1e4/(dist+entry*(2*fee+2*slip)),cap*1e4/entry)
        k=sim(P,fcum,bm,s,em,raw,entry,stop,dist,qty,target_r,hold,add_mode,add_r,add_frac,sig_min,side,kind,lev,stp,val,fee,slip,risk,cap,minstop,out,k,root,info)
        free=int(info[0])+1
        if reent>0 and info[1]==1. and info[3]==1.:
            b=int(info[2])//bm
            if b>=3 and b<nb:
                lvl=max(h[b],h[b-1],h[b-2]) if s==1 else min(l[b],l[b-1],l[b-2])
                st2=c[b]-s*2.*atr[b];m1=(b+1)*bm;mend=min((b+7)*bm,nm);em2=-1;raw2=0.
                for m in range(m1,mend):
                    if (s==1 and P[m,2]<=st2) or (s==-1 and P[m,1]>=st2):
                        if not ((s==1 and P[m,1]>=lvl) or (s==-1 and P[m,2]<=lvl)):break
                    if s==1 and P[m,1]>=lvl:raw2=max(P[m,0],lvl);em2=m;break
                    if s==-1 and P[m,2]<=lvl:raw2=min(P[m,0],lvl);em2=m;break
                if em2>=0:
                    e2=raw2*(1+s*slip);d2=s*(e2-st2)
                    if d2/e2>=minstop:
                        q2=min(risk*1e4/(d2+e2*(2*fee+2*slip)),cap*1e4/e2)
                        root+=1
                        k=sim(P,fcum,bm,s,em2,raw2,e2,st2,d2,q2,target_r,hold,0,0.,0.,0.,side,kind,lev,stp,val,fee,slip,risk,cap,minstop,out,k,root,info)
                        free=int(info[0])+1
        root+=1
    return out[:k]

def run3(d,add_mode=0,add_r=1.,add_frac=0.,sig_min=0.,reent=0,target_r=2.,hold=30):
    g=d['sig'];n=len(g['side'])
    return engine3(d['P'],d['fc'],240,np.asarray(g['side'],np.int8),g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],d['h'][:n],d['l'][:n],d['c'][:n],
                   float(target_r),int(hold),int(add_mode),float(add_r),float(add_frac),float(sig_min),int(reent),PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP,250)

VARIANTS={'A0_be_only':dict(add_mode=1,add_r=1.,add_frac=0.),
 'A_add1_half':dict(add_mode=1,add_r=1.,add_frac=.5),
 'B_add1_full':dict(add_mode=1,add_r=1.,add_frac=1.),
 'C_add1_half_t3':dict(add_mode=1,add_r=1.,add_frac=.5,target_r=3.),
 'D_sig_half':dict(add_mode=2,sig_min=.5,add_frac=.5),
 'E_sig_full':dict(add_mode=2,sig_min=1.,add_frac=1.),
 'F_reent':dict(reent=1),
 'G_add1h_reent':dict(add_mode=1,add_r=1.,add_frac=.5,reent=1)}

def fn(d,v):return run3(d,**v)

def assert_repro():
    for s in ('LINKUSDT','CRVUSDT',PB.OTHER20[0]):
        d=PB.coin(s);a=PB.run(d);b=run3(d)
        assert a.shape==b.shape and np.allclose(a,b),f'engine3 does not reproduce baseline on {s}'
    print('engine3 reproduces pabench.run on 3 coins',flush=True)

def diag():
    sm=PB.X.SPLIT*1440;tot=0;wins=0;losses=0;ts=0;skipped=0;n3=0;tsw=0
    for s in PB.OTHER20:
        d=PB.coin(s);t=PB.run(d);t=t[t[:,0]<sm]
        if not len(t):continue
        tot+=len(t);wins+=int((t[:,4]>1.5).sum());losses+=int((t[:,4]<-.8).sum());ts+=int(((t[:,4]>-.8)&(t[:,4]<1.5)).sum());tsw+=int(((t[:,4]>0)&(t[:,4]<1.5)).sum())
        sd=d['sig']['side']
        for e,x in zip(t[:,0],t[:,1]):
            b0=int(e)//240;b1=int(x)//240;sg=int(t[t[:,0]==e][0,2]);skipped+=int((sd[b0:b1]==sg).sum()) if b1>b0 else 0
    print(f'TRAIN OTHER20 baseline trades {tot}: R>1.5 {wins} ({wins/tot*100:.1f}%), R<-0.8 {losses} ({losses/tot*100:.1f}%), in between {ts} (of which positive timestop-like {tsw}); same-side signals during open trades {skipped}')

def main():
    assert_repro();PB.run_idea('reentry',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':
    diag() if len(sys.argv)>1 and sys.argv[1]=='diag' else main()
