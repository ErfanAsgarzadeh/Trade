"""Final holdout test of the 3 candidates that had Calmar > 0.5 in all four cells (5 coins / 10 coins x train / valid).

Written and committed BEFORE the holdout data was downloaded/prepared in this session and before any of the 3,723
configs was run on these coins. Coins (repo liquidity lists, picked without performance): HOLD10 = ETC NEAR TRX CELR
BCH UNI ALICE SUSHI C98 1000SHIB, HOLD2 = THETA EGLD AAVE IOST ONE CVC CRV IOTA KSM VET -> 20 coins.
CANDIDATES (unchanged code paths from mtf_search / xuni; 4h bars; taker costs 0.06%/side + 2 bps + funding):
  C1  RSI50  exit TRAIL  (2 ATR stop, 3 ATR chandelier)   filter ADX<20
  C2  RSI50  exit TRAILW (2 ATR stop, 4.5 ATR chandelier) filter ADX<20
  C3  PULL   exit TRAILW                                   filter NOWKND
Portfolio: one position per coin, 0.5% risk per trade on the 1e4 base, daily mark-to-market returns summed over
coins and scaled by 10/20 (same total risk budget as the 10-coin test).
PASS (per candidate, on the 20 holdout coins): full-period CAGR > 0 AND Calmar >= 0.5 in train (<2025) AND in
validation (2025-01-01..2026-10-04). Reported only: HOLD10 / HOLD2 separately, per-coin net, the bot on these coins.
Three candidates are tested, so one pass out of three is weaker evidence than a single pre-registered candidate.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import ltf_search as L, mtf_search as M, xuni as X
H10=['ETCUSDT','NEARUSDT','TRXUSDT','CELRUSDT','BCHUSDT','UNIUSDT','ALICEUSDT','SUSHIUSDT','C98USDT','1000SHIBUSDT']
H2=['THETAUSDT','EGLDUSDT','AAVEUSDT','IOSTUSDT','ONEUSDT','CVCUSDT','CRVUSDT','IOTAUSDT','KSMUSDT','VETUSDT']
CANDS={'C1':('RSI50','TRAIL','ADX<20'),'C2':('RSI50','TRAILW','ADX<20'),'C3':('PULL','TRAILW','NOWKND')}
OUT=X.OUT

def per_coin(s,days):
    p=np.load(X.PREP/s/'prices.npy');f=np.load(X.PREP/s/'funding.npy').copy();m=np.arange(len(f))
    px=(m>=(1790812800000-rs.START)//60000)&(m%480==0)&~np.isfinite(f);f[px]=1e-4;f[~np.isfinite(f)]=0;fc=np.concatenate([[0.],np.cumsum(f)])
    o,h,l,c=L.bars(p,240);sig,atr,adx=L.signals(o,h,l,c);sig=M.extra_signals(o,h,l,c,atr,adx,sig);n=len(c)
    wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    filt={'ADX<20':(adx<20,)*2,'NOWKND':(wk,wk)};fb=fc[np.minimum(np.arange(n)*240,len(fc)-1)];out={}
    for k,(fam,ex,fl) in CANDS.items():
        T=M.engine(o,h,l,c,atr,*sig[fam],*filt[fl],M.EXITS[ex],.0006,.0002,fb,300);out[k]=(M.m2m(T,c,240,days),len(T))
    return out

def main():
    days=len(np.load(X.PREP/H10[0]/'prices.npy',mmap_mode='r'))//1440;coins=H10+H2;res=dict(notes=__doc__,candidates={})
    pc={s:per_coin(s,days) for s in coins}
    for k in CANDS:
        allr=sum(pc[s][k][0] for s in coins)*10/len(coins);st=X.stats(allr)
        g={name:X.stats(sum(pc[s][k][0] for s in grp)) for name,grp in (('HOLD10',H10),('HOLD2',H2))}
        ok=st['full'][1]>0 and st['train'][0]>=.5 and st['oos'][0]>=.5
        res['candidates'][k]=dict(cfg=CANDS[k],all20=st,groups=g,per_coin={s:float(pc[s][k][0].sum()*100) for s in coins},trades=int(sum(pc[s][k][1] for s in coins)),passed=bool(ok),
                                  curve=list(np.cumprod(1+allr)[::7]*1e4))
        print(f"{k} {CANDS[k]}: 20 coins CAGR {st['full'][1]:.1f}% DD {st['full'][2]:.1f}% Calmar {st['full'][0]:.2f} | train {st['train'][0]:.2f} valid {st['oos'][0]:.2f} | trades {res['candidates'][k]['trades']} | HOLD10 Calmar {g['HOLD10']['full'][0]:.2f} HOLD2 {g['HOLD2']['full'][0]:.2f} | PASS={ok}",flush=True)
        print('   coins profitable:',sum(v>0 for v in res['candidates'][k]['per_coin'].values()),'/ 20',flush=True)
    try:
        F4={s:X.frame(s) for s in coins};ok=[s for s in coins if F4[s].timestamp.iloc[0]<=rs.START-198*14400000]
        b,_=X.bot_daily(ok,F4,np.stack([np.load(X.PREP/s/'prices.npy') for s in ok]),np.stack([np.load(X.PREP/s/'funding.npy') for s in ok]),days)
        bs=X.stats(b);res['bot']=dict(coins=ok,stats=bs);print(f"bot (2A+5A, 4 slots) on {len(ok)} of these coins: CAGR {bs['full'][1]:.1f}% DD {bs['full'][2]:.1f}% Calmar {bs['full'][0]:.2f} | train {bs['train'][0]:.2f} valid {bs['oos'][0]:.2f}",flush=True)
    except Exception as e:res['bot']=str(e);print('bot not run:',e)
    (OUT/'holdout_test.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
