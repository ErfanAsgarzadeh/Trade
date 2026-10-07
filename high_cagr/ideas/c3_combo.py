"""Bot (2A+5A, 5 coins, 0.75%/trade, 4 slots) + C3 sleeve on its 10 chosen coins at several per-trade risks.
Coins = top-10 by C3 TRAIN profit among the 30 tested coins (identical to the top-10 by full period); in validation
those 10 averaged +8.4% vs +1.9% for the other 20 (c3_per_coin.csv). Daily mark-to-market returns are added."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import holdout_test as H, xuni as X, orb_intraday as oi
COINS=['AAVEUSDT','UNIUSDT','AVAXUSDT','KSMUSDT','EGLDUSDT','DOTUSDT','DOGEUSDT','ONEUSDT','TRXUSDT','SUSHIUSDT']
if __name__=='__main__':
    days=len(np.load(X.PREP/COINS[0]/'prices.npy',mmap_mode='r'))//1440;c3=sum(H.per_coin(s,days)['C3'][0] for s in COINS);bot=oi.bot_daily(days)
    out={'coins':COINS,'bot':X.stats(bot),'corr':float(np.corrcoef(bot,c3)[0,1]),'rows':{}}
    print(f"correlation bot vs C3 sleeve: {out['corr']:.2f}")
    for r in (0,.0025,.00375,.005):
        comb=bot+c3*(r/.005);st=X.stats(comb);alone=X.stats(c3*(r/.005)) if r else None;out['rows'][str(r)]=dict(comb=st,alone=alone,curve=list(np.cumprod(1+comb)[::7]*1e4))
        print(f"C3 risk {r*100:.3f}%/trade: combined CAGR {st['full'][1]:5.1f}% DD {st['full'][2]:4.1f}% Calmar {st['full'][0]:.2f} | train {st['train'][0]:.2f} valid {st['oos'][0]:.2f}"+(f" | C3 alone CAGR {alone['full'][1]:.1f}% DD {alone['full'][2]:.1f}%" if r else '  (bot alone)'))
    (X.OUT/'c3_combo.json').write_text(json.dumps(out,indent=1,default=float))
