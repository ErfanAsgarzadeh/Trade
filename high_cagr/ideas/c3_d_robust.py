"""Robustness of the meeting's choice (agent 1 variant D) vs C3 baseline: per coin, per year, and on the bot's 5 coins
(never used by any C3 agent). Diagnosis only - D is already fixed."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B, c3_a1_followthrough as A1, mtf_search as M, ltf_search as L, xuni as X
from high_cagr import run_suite as rs
D=dict(confirm=3,level='close')
def five(s):
    p=np.load(ROOT/'high_cagr/prepared'/s/'prices.npy');f=np.load(ROOT/'high_cagr/prepared'/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fc=np.concatenate([[0.],np.cumsum(f)])
    o,h,l,c=L.bars(p,240);sig,atr,adx=L.signals(o,h,l,c);n=len(c);wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    return dict(name=s,o=o,h=h,l=l,c=c,atr=atr,adx=adx,sig=sig,wk=wk,fb=fc[np.minimum(np.arange(n)*240,len(fc)-1)],n=n,e50=L.ema(c,50),e200=L.ema(c,200),r14=L.rsi(c,14))
days=B.days();rows=[];yr={}
for uni,coins,get in (('MAIN10',B.MAIN10,B.coin),('OTHER20',B.OTHER20,B.coin),('BOT5',['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT'],five)):
    tot={'base':np.zeros(days),'D':np.zeros(days)}
    for s in coins:
        d=get(s);rb=M.m2m(B.baseline_trades(d),d['c'],240,days);rd=M.m2m(A1.trades_fn(d,D),d['c'],240,days);tot['base']+=rb;tot['D']+=rd
        rows.append(dict(uni=uni,coin=s[:-4],base=rb.sum()*100,D=rd.sum()*100,base_cal=X.stats(rb)['full'][0],D_cal=X.stats(rd)['full'][0]))
    for k,r in tot.items():
        st=X.stats(r*10/len(coins));s_=pd.Series(r*10/len(coins),index=pd.date_range('2021-10-05',periods=days,freq='D'))
        yr[(uni,k)]=((1+s_).groupby(s_.index.year).prod()-1)*100
        print(f"{uni:7s} {k:4s}: CAGR {st['full'][1]:5.1f}% DD {st['full'][2]:4.1f}% Calmar {st['full'][0]:.2f} | train {st['train'][0]:.2f} valid {st['oos'][0]:.2f}")
R=pd.DataFrame(rows);R['better']=R.D_cal>R.base_cal
print('\ncoins where D has the higher Calmar:',R.groupby('uni').better.agg(['sum','size']).to_dict('index'))
print(R.round(2).to_string(index=False))
Y=pd.DataFrame(yr).round(1);print('\nyearly return % (10-coin scaled):');print(Y.to_string())
R.to_csv(X.OUT/'c3/d_robust_coins.csv',index=False);Y.to_csv(X.OUT/'c3/d_robust_years.csv')
