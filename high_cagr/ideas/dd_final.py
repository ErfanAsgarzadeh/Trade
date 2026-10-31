"""Drawdown study, final check: ONE continuous $10,000 account from 2022-01-01 to the end of data (no reset between years),
for the current bots, E+M without control, and the chosen AI risk-control setups from stage 5 (scales as solved there).
Entry multipliers per period: 2022 momentum only (no trained entry model yet), 2023 / 2024 / 2025-26 E+M from that period's
walk-forward model. AI regime scores: strict walk-forward for 2023+, purged CV for 2022 (see dd_ai.py / dd_ai2.py)."""
import sys,json,warnings
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import dd_engine as E, dd_lab as DL, dd_lab5 as D5
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
def piecewise():
    m=np.zeros(len(DL.DEP));em=np.array([l['em'] for l in DL.DEP])
    for fn,(a,b) in DL.PER.items():
        k=(em>=a)&((em<b) if b else True);m[k]=DL.mult(fn)[k]
    return m
def run(mult,ctrl):
    a=DL.PER['2022'][0];return E.period(DL.DEP,mult,a,None,ctrl)
def main():
    S=json.loads((DL.OUT/'stage5.json').read_text());sc={r['name']:r['scale'] for r in S};t=D5.tops();ones=np.ones(len(DL.DEP));pm=piecewise()
    pick={'B: AI off50 + vol target + AI on open + brake .06-.14 (dev 13%)':('B r20/off50+vt+gopen','b2 .06-.14 fl.1',13),
          'A: AI cut30up + vol target + AI on open + brake .04-.10 (dev 13%)':('A r20/cut30up+vt+gopen','b4 .04-.10 fl.3',13)}
    rows={'current bots (no control)':run(ones,{}),'E+M, no control':run(pm,{})}
    for nm,(tn,bn,tg) in pick.items():
        s=sc[f'{tn} | brake {bn} | dev target {tg}'];rows[nm+f' [scale {s:.2f}]']=run(pm,dict(t[tn],ddopen=D5.BRAKES[bn],scale=s))
    out={};fig,ax=plt.subplots(2,1,figsize=(12,8),sharex=True);idx=pd.date_range('2022-01-01',periods=len(next(iter(rows.values()))['daily']))
    for nm,r in rows.items():
        d=r.pop('daily');out[nm]=r;s=pd.Series(d,idx);ax[0].plot(idx,d,label=nm);ax[1].plot(idx,(d/np.maximum.accumulate(d)-1)*100)
        me=s.resample('ME').last();out[nm]['monthly']={str(k.date())[:7]:round(float(v),2) for k,v in ((me/me.shift(1).fillna(1e4)-1)*100).items()}
        print(f"{nm:72s} final {r['final']:>12,.0f} CAGR {r['cagr']:6.1f}% maxDD {r['dd']:6.1f}% months+ {r['mpos']:3.0f}% worst month {r['mworst']:+5.1f}% | "+' '.join(f"{y}: {v['ret']:+6.0f}%/{v['dd']:5.1f}" for y,v in r['years'].items()),flush=True)
    ax[0].set_yscale('log');ax[0].legend(fontsize=8);ax[0].set_title('One account from 2022-01-01 ($10,000)');ax[1].axhline(-15,color='k',ls='--');ax[1].set_ylabel('drawdown %')
    fig.tight_layout();fig.savefig(DL.OUT/'final_equity.png',dpi=110);(DL.OUT/'final.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
