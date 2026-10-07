"""C3 failure and missed-trend diagnostics on its 10 coins (4h PULL / TRAILW / NOWKND). Diagnosis only.

Per trade: R = initial stop distance (2 ATR); MFE/MAE in R from bar highs/lows between entry and exit; exit kind
(initial stop, trailing stop in loss, trailing stop in profit). Loss categories as in the bot's failure report:
COST_FLIP (price result > 0, net < 0), NO_FOLLOW_THROUGH (MFE < 0.5R), FAST_REVERSAL (<= 2 bars and MFE < 1R),
GIVEBACK (MFE >= 1R), SLOW_FAILURE (rest). Winners: capture = exit R / MFE.
Missed trends: zigzag 25% on daily closes, swings >= 30% and >= 7 days; each 4h bar inside a trend is WITH /
AGAINST / FLAT:no_signal / FLAT:weekend_blocked / FLAT:trend_filter (EMA50 vs EMA200 against the swing).
Writes high_cagr/output/ideas/c3_diag.json, c3_trades.csv and C3_DIAGNOSIS.md.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import ltf_search as L, mtf_search as M, xuni as X, trend_audit as TA
COINS=['AAVEUSDT','UNIUSDT','AVAXUSDT','KSMUSDT','EGLDUSDT','DOTUSDT','DOGEUSDT','ONEUSDT','TRXUSDT','SUSHIUSDT'];SPLIT=X.SPLIT

def coin_data(s):
    p=np.load(X.PREP/s/'prices.npy');f=np.load(X.PREP/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fc=np.concatenate([[0.],np.cumsum(f)])
    o,h,l,c=L.bars(p,240);sig,atr,adx=L.signals(o,h,l,c);n=len(c);wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    return dict(o=o,h=h,l=l,c=c,atr=atr,adx=adx,sig=sig,wk=wk,fb=fc[np.minimum(np.arange(n)*240,len(fc)-1)],n=n)

def main():
    rows=[];days=None;audit=[]
    for s in COINS:
        d=coin_data(s);o,h,l,c,atr=d['o'],d['h'],d['l'],d['c'],d['atr'];le,se,_,_=d['sig']['PULL']
        T=M.engine(o,h,l,c,atr,le,se,np.zeros(d['n'],bool),np.zeros(d['n'],bool),d['wk'],d['wk'],6,.0006,.0002,d['fb'],300)
        e50=L.ema(c,50);e200=L.ema(c,200);r14=L.rsi(c,14)
        for t in T:
            e,x,side,frac,pR,q,ent,xp,cost=int(t[0]),int(t[1]),int(t[2]),t[3],t[4],t[5],t[6],t[7],t[8];sb=e-1;R=2*atr[sb]
            hi=h[e:x+1].max();lo=l[e:x+1].min();mfe=(hi-o[e] if side>0 else o[e]-lo)/R;mae=(o[e]-lo if side>0 else hi-o[e])/R
            init_stop=ent-side*2*atr[sb];xr=side*(xp/(1-side*.0002)-o[e])/R
            kind='INITIAL_STOP' if abs(xp/(1-side*.0002)-init_stop)/init_stop<1e-9 or side*(xp/(1-side*.0002)-init_stop)<=0 else ('TRAIL_LOSS' if frac<0 else 'TRAIL_PROFIT')
            win=frac>0;cat='WIN' if win else ('COST_FLIP' if pR>0 else 'NO_FOLLOW_THROUGH' if mfe<.5 else 'FAST_REVERSAL' if (x-e)<=2 and mfe<1 else 'GIVEBACK_GE1R' if mfe>=1 else 'SLOW_FAILURE')
            # entry context at the signal bar
            k=sb;dip=r14[max(0,k-12):k].min() if side>0 else 100-r14[max(0,k-12):k].max()   # side-adjusted pullback depth
            cross_age=0
            while k-cross_age-1>0 and np.sign(e50[k-cross_age-1]-e200[k-cross_age-1])==side:cross_age+=1
            rows.append(dict(coin=s[:-4],side='LONG' if side>0 else 'SHORT',entry_bar=e,exit_bar=x,bars=x-e,entry_day=int(e*240//1440),net_frac=frac,net_R=frac/.005,price_R=pR,mfe_R=mfe,mae_R=mae,exit_kind=kind,category=cat,
                capture=xr/mfe if mfe>0 and win else np.nan,adx=d['adx'][sb],atr_rel=atr[sb]/np.median(atr[max(0,sb-60):sb]),ema_gap_atr=side*(e50[sb]-e200[sb])/atr[sb],
                dist_ema50_atr=side*(c[sb]-e50[sb])/atr[sb],rsi_dip=dip,cross_age_bars=cross_age,train=int(e*240//1440)<SPLIT))
        # missed trends (daily zigzag)
        dc=c[5::6];days=len(dc);piv=TA.zigzag(dc)
        state=np.zeros(d['n']);
        for t in T:state[int(t[0]):int(t[1])+1]=t[2]
        for i in range(len(piv)-1):
            i0,i1=piv[i],piv[i+1];mv=dc[i1]/dc[i0]-1
            if abs(mv)<.30 or i1-i0<7:continue
            sd=1 if mv>0 else -1;b0,b1=(i0+1)*6,(i1+1)*6;lr=np.diff(np.log(c[b0:b1+1]))*sd;st=state[b0:b1]
            raw=(le if sd>0 else se)[b0:b1];trend_ok=(e50>e200)[b0:b1] if sd>0 else (e50<e200)[b0:b1]
            lab=np.where(st==sd,'WITH',np.where(st==-sd,'AGAINST',np.where(~trend_ok,'FLAT:trend_filter_against',np.where(raw&~d['wk'][b0:b1],'FLAT:weekend_blocked','FLAT:no_signal'))))
            tot=np.log(dc[i1]/dc[i0])*sd;audit.append(dict(coin=s[:-4],side='UP' if sd>0 else 'DOWN',move=mv*100,days=i1-i0,**{k:float(lr[lab==k].sum()/tot*100) for k in ('WITH','AGAINST','FLAT:trend_filter_against','FLAT:weekend_blocked','FLAT:no_signal')}))
    P=pd.DataFrame(rows);A=pd.DataFrame(audit);P.to_csv(X.OUT/'c3_trades.csv',index=False);A.to_csv(X.OUT/'c3_trend_audit.csv',index=False)
    los=P[P.net_frac<0];tl=P[P.train]
    cat=los.groupby('category').agg(n=('net_R','size'),sum_R=('net_R','sum'),median_bars=('bars','median')).assign(share_loss_R=lambda g:g.sum_R/los.net_R.sum()*100)
    ex=P.groupby('exit_kind').agg(n=('net_R','size'),sum_R=('net_R','sum'),win=('net_frac',lambda v:(v>0).mean()*100))
    w=P[P.net_frac>0]
    caps=pd.cut(w.mfe_R,[0,2,4,8,100]);cap=w.groupby(caps,observed=True).agg(n=('net_R','size'),mean_mfe=('mfe_R','mean'),mean_exit_R=('price_R','mean'),capture=('capture','median'))
    lw=A.assign(lm=np.log1p(A.move.abs()/100*np.sign(A.move)).abs());keys=['WITH','AGAINST','FLAT:trend_filter_against','FLAT:weekend_blocked','FLAT:no_signal']
    share=(lw[keys].mul(lw.lm,axis=0).sum()/lw.lm.sum())
    def coh(col,bins):
        z=tl.dropna(subset=[col]);g=z.groupby(pd.cut(z[col],bins),observed=True).agg(n=('net_R','size'),mean_R=('net_R','mean'),win=('net_frac',lambda v:(v>0).mean()*100));return g
    cohorts={c_:coh(c_,b) for c_,b in (('adx',[0,15,20,25,35,100]),('atr_rel',[0,.8,1,1.2,1.5,10]),('ema_gap_atr',[-1,1,2,4,8,100]),('dist_ema50_atr',[-20,-1,0,1,2,20]),('rsi_dip',[0,25,30,35,40,100]),('cross_age_bars',[-1,30,90,180,400,5000]))}
    side=P.groupby(['side','train']).agg(n=('net_R','size'),sum_R=('net_R','sum'),win=('net_frac',lambda v:(v>0).mean()*100))
    top=P.sort_values('net_R',ascending=False);top_share=top.net_R.head(len(P)//10).sum()/P.net_R.sum()*100
    md=['# C3 diagnosis (10 coins, full period, 4h PULL / TRAILW / NOWKND)',f"trades {len(P)}, win rate {(P.net_frac>0).mean()*100:.1f}%, mean net {P.net_R.mean():+.3f}R, top 10% of trades = {top_share:.0f}% of net R",
        '\n## Losing trades by category\n'+cat.round(2).to_string(),'\n## Exit kind\n'+ex.round(2).to_string(),'\n## Winners: how much of the peak is kept\n'+cap.round(2).to_string(),
        '\n## Big trends (>=30%, >=7 days): share of the move\n'+share.round(1).to_string(),'\n## Long vs short (train=True/False)\n'+side.round(2).to_string()]
    for k,v in cohorts.items():md.append(f'\n## TRAIN cohort: {k}\n'+v.round(3).to_string())
    (X.OUT/'C3_DIAGNOSIS.md').write_text('\n'.join(md));print('\n'.join(md))
if __name__=='__main__':main()
