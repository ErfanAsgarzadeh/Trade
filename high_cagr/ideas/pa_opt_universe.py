"""pa_opt_universe: which coin universe suits the PA sleeve, and is choosing coins by past results trustworthy?

HYPOTHESIS. KEYREV is a generic bar pattern; any edge should be about equally (weakly) present across liquid perps, so
per-coin differences are mostly noise and a drop-coin rule decided on TRAIN will NOT persist into validation (rank
correlation of per-coin train vs valid net ~0). Larger universes just diversify (more trades, lower variance).
MECHANISM. If an edge is coin-specific (liquidity / microstructure), train-losers stay losers; if not, removing them only
shrinks the sample and lowers diversification.

PART 1 (descriptive, no parameters picked): PA alone on OTHER20, MAIN5, MAIN10, IN15, ALL35 (train/valid/full Calmar,
CAGR, DD, trades) and THREE = TWO + PA*0.3 for each universe. Per-coin net (sum of net_frac*1e4 = $ on 1e4 base) in
TRAIN vs VALID for all 35 coins, Spearman of per-coin train vs valid net (ALL35, OTHER20, IN15) and top-half-by-train vs
bottom-half valid sums. Overlap with the other bots' positions cannot be measured: their trades are not stored as ledgers
(only daily series). Practical constraint: LBank holds ONE net position per symbol, so on MAIN5/MAIN10 a PA entry on a
coin where the main/C3 bot is already long would be netted (adds to / opposes that position, e.g. a PA long against a bot
short nets out) and the stop/target of the sleeve would no longer be separately enforceable. OTHER20 avoids this by design.

TRAIN-ONLY DIAGNOSTIC (baseline trades with entry < 2025-01-01 on OTHER20, net $ on 1e4 base per coin, decided BEFORE
variants): ATOM -770, THETA -593, CRV -448, CELR -388, XTZ -366, IOTA -177, ALGO -158, BCH -92, SHIB -91 (the 9 negative);
positives: NEAR 944, IOST 591, AXS 503, LINK 383, FIL 233, ALICE 215, VET 167, LTC 143, ETC 98, CVC 60, C98 10.

VARIANTS (fixed, deployed on OTHER20 only, coin lists fixed from the TRAIN diagnostic above; evaluate() scores on OTHER20):
 A drop_neg9      drop the 9 train-negative coins
 B drop_worst5    drop ATOM THETA CRV CELR XTZ
 C drop_worst3    drop ATOM THETA CRV
 D keep_top10     keep NEAR IOST AXS LINK FIL ALICE VET LTC ETC CVC
 E rand_drop5     CONTROL: drop 5 random coins (RandomState(7).choice)
 F rand_drop9     CONTROL: drop 9 random coins (RandomState(11).choice)
Note: coin lists chosen on train make P1 (train Calmar) in-sample by construction; only P2 (valid) is informative.
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np,pandas as pd
from high_cagr.ideas import pabench as PB, xuni as X

NEG9=['ATOMUSDT','XTZUSDT','ALGOUSDT','CELRUSDT','BCHUSDT','1000SHIBUSDT','THETAUSDT','CRVUSDT','IOTAUSDT']
W5=['ATOMUSDT','THETAUSDT','CRVUSDT','CELRUSDT','XTZUSDT'];W3=['ATOMUSDT','THETAUSDT','CRVUSDT']
TOP10=['NEARUSDT','IOSTUSDT','AXSUSDT','LINKUSDT','FILUSDT','ALICEUSDT','VETUSDT','LTCUSDT','ETCUSDT','CVCUSDT']
R5=list(np.array(PB.OTHER20)[np.random.RandomState(7).choice(20,5,replace=False)])
R9=list(np.array(PB.OTHER20)[np.random.RandomState(11).choice(20,9,replace=False)])
VARIANTS={'A_drop_neg9':dict(drop=NEG9),'B_drop_worst5':dict(drop=W5),'C_drop_worst3':dict(drop=W3),
    'D_keep_top10':dict(drop=[c for c in PB.OTHER20 if c not in TOP10]),'E_rand_drop5':dict(drop=R5),'F_rand_drop9':dict(drop=R9)}

def fn(d,v):
    if d['name'] in v['drop']:return np.zeros((0,10))
    return PB.run(d)

def descriptive():
    bot,c3=PB.two();tw=bot+c3;sm=X.SPLIT*1440
    print('== UNIVERSE COMPARISON (PA alone at 0.5% sim risk; THREE = TWO + PA*0.3) ==')
    for nm,co in (('OTHER20',PB.OTHER20),('MAIN5',PB.MAIN5),('MAIN10',PB.MAIN10),('IN15',PB.IN15),('ALL35',PB.ALL35)):
        r,T=PB.series(PB.base_fn,None,co);p=X.stats(r);t=X.stats(tw+r*PB.PA_SCALE);ts=PB.tstats(T)
        print(f"{nm:8s} coins {len(co):2d} trades {ts['roots']:4d} | PA calmar train {p['train'][0]:.2f} valid {p['oos'][0]:.2f} full {p['full'][0]:.2f} CAGR {p['full'][1]:.1f}% DD {p['full'][2]:.1f}%"
              f" | THREE train {t['train'][0]:.2f} valid {t['oos'][0]:.2f} full {t['full'][0]:.2f} CAGR {t['full'][1]:.1f}% DD {t['full'][2]:.1f}%",flush=True)
    rows=[]
    for s in PB.ALL35:
        t=PB.base_fn(PB.coin(s));tr=t[t[:,0]<sm];va=t[t[:,0]>=sm]
        rows.append(dict(coin=s,grp='OTHER20' if s in PB.OTHER20 else ('MAIN5' if s in PB.MAIN5 else 'MAIN10'),n_tr=len(tr),net_tr=tr[:,3].sum()*1e4 if len(tr) else 0.,n_va=len(va),net_va=va[:,3].sum()*1e4 if len(va) else 0.))
    df=pd.DataFrame(rows);print('\n== PER-COIN (net $ on 1e4 base; trades) ==');print(df.round(1).to_string(index=False))
    print('\n== PERSISTENCE: Spearman(train net, valid net) ==')
    for nm,m in (('ALL35',df.grp.notna()),('OTHER20',df.grp=='OTHER20'),('IN15',df.grp!='OTHER20')):
        x=df[m];print(f"{nm:8s} n={len(x)} spearman={x.net_tr.corr(x.net_va,method='spearman'):.3f}  coins with train>0: {int((x.net_tr>0).sum())}, of which valid>0: {int(((x.net_tr>0)&(x.net_va>0)).sum())}; train<=0: {int((x.net_tr<=0).sum())}, of which valid>0: {int(((x.net_tr<=0)&(x.net_va>0)).sum())}")
        h=x.sort_values('net_tr',ascending=False);k=len(h)//2
        print(f"   top-half-by-train valid net sum {h.net_va.iloc[:k].sum():.0f} (train {h.net_tr.iloc[:k].sum():.0f}) | bottom-half valid net sum {h.net_va.iloc[k:].sum():.0f} (train {h.net_tr.iloc[k:].sum():.0f})",flush=True)
    print()

def main():
    descriptive();PB.run_idea('universe',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
