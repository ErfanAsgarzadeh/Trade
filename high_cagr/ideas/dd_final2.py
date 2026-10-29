"""Drawdown study, final check v2 (after the weak-year fix): one continuous $10,000 account from 2022-01-01, current bots vs
the stage-9 setups: AI v2 score mapping off30up (no new trades when the score is in the bottom 30%, x1.4 in the top 30%),
vol target, AI de-risking of open positions, per-bot streak control (last 20 closed trades < -4R -> that bot x0.5) and a
drawdown brake on new and open positions (D: 10%->16%, floor 0.2; E: 9%->14%, floor 0.1; F: 8%->14%, floor 0.2).
Scales as solved in stage 9 (dev 2022-24 worst drawdown = 14%)."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_lab as DL, dd_lab6 as D6, dd_final as F
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
def main():
    p=D6.raw();pm=F.piecewise();S={r['name']:r['scale'] for r in json.loads((DL.OUT/'stage9.json').read_text())}
    def mk(b):s=S[f'off30up | brake {b} all | botdd 20<-4R x.5 | t14'];return dict(D6.VT,g=D6.gfrom(p,'off30up'),gopen=True,ddopen=b,botdd=(20,-4.,.5),scale=s)
    rows={'current bots':F.run(np.ones(len(DL.DEP)),{}),'D (max profit)':F.run(pm,mk((.1,.16,.2))),'F (balanced)':F.run(pm,mk((.08,.14,.2))),'E (strict 15%)':F.run(pm,mk((.09,.14,.1)))}
    out={};fig,ax=plt.subplots(2,1,figsize=(12,8),sharex=True);idx=pd.date_range('2022-01-01',periods=len(rows['current bots']['daily']))
    for nm,r in rows.items():
        d=r.pop('daily');s=pd.Series(d,idx);me=s.resample('ME').last();r['monthly']={str(k.date())[:7]:round(float(v),2) for k,v in ((me/me.shift(1).fillna(1e4)-1)*100).items()};out[nm]=r
        ax[0].plot(idx,d,label=nm);ax[1].plot(idx,(d/np.maximum.accumulate(d)-1)*100)
        print(f"{nm:16s} final {r['final']:>11,.0f} CAGR {r['cagr']:6.1f}% DD {r['dd']:6.1f}% months+ {r['mpos']:3.0f}% worst {r['mworst']:+5.1f}% | "+' '.join(f"{y}:{v['ret']:+.0f}%/{v['dd']:.1f}" for y,v in r['years'].items()),flush=True)
    ax[0].set_yscale('log');ax[0].legend();ax[0].set_title('One account from 2022-01-01 ($10,000)');ax[1].axhline(-15,color='k',ls='--');ax[1].set_ylabel('drawdown %')
    fig.tight_layout();fig.savefig(DL.OUT/'final2_equity.png',dpi=110);(DL.OUT/'final2.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
