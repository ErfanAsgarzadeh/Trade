"""Out-of-sample check of the two near-miss rules from pa_rules.py on 30 coins the bot never traded.
Written and committed BEFORE running; one run, no tuning.

Coins: NEW10 + H10 + H2 (xuni / holdout_test lists), sorted, in 6 groups of 5 -> 6 independent bot portfolios exactly as
xuni.bot_daily (2A+5A, Donchian10+Kumo 4h, 4 slots, floor 1R/+0.1R) at 1.0% risk; group daily returns averaged.
Rules (definitions unchanged from pa_rules.flags_at):
  R1 room2:half  -> 0.5x risk when the nearest pivot against the trade is < 2 ATR beyond the close
  R2 badsb:1.5x  -> 1.5x risk when the signal bar fails the Al Brooks quality test
Gates, each rule separately (all must hold to recommend adding it to the bot):
  G1 trade level (baseline trades): mean net R of YES vs NO has the same sign as on the bot's 5 coins
     (R1: YES worse, R2: YES better) with n_yes >= 50
  G2 combined 30-coin Calmar (full period) with the rule >= baseline Calmar + 0.05
  G3 at least 4 of the 6 groups have a higher full-period Calmar with the rule
  G4 the rule beats a flat risk multiplier equal to its realised mean multiplier on combined Calmar
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
from high_cagr.ideas import xuni as X, holdout_test as H, pa_rules as PR, bench
COINS=sorted(X.NEW+H.H10+H.H2);GROUPS=[COINS[i:i+5] for i in range(0,30,5)];OUT=bench.OUT/'pa_rules_oos';RISK=.01

def setup(symbols):
    F={s:X.frame(s) for s in symbols};case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=RISK,max_open_positions=4)
    fk={(s,'4h','standard'):F[s] for s in symbols};ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;ix={}
    for j,s in enumerate(symbols):
        f=F[s];ix[s]=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]]
        ar=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()[ix[s]];low=~(ar>=1.)&(ss[j,:,0]!=0);ss[j,low,0]=0;ss[j,low,3]=-np.inf
    ss=np.concatenate([ss,np.ones(ss.shape[:2]+(1,))],axis=2)
    prices=np.stack([np.load(X.PREP/s/'prices.npy') for s in symbols]);funding=np.stack([np.load(X.PREP/s/'funding.npy') for s in symbols])
    flags={};Xp={s:PR.prep(F[s]) for s in symbols}
    for j,s in enumerate(symbols):
        for b in np.where(ss[j,:,0]!=0)[0]:
            fl=PR.flags_at(Xp[s],int(ix[s][b]),int(ss[j,b,0]))
            if fl:flags[(j,int(b))]=fl
    return dict(ss=ss,bb=bb,step=step,prices=prices,funding=funding,flags=flags,symbols=symbols)

def run(g,mult):
    ss=g['ss'].copy()
    for (j,b),fl in g['flags'].items():ss[j,b,4]=mult(fl)
    a,t,curve=simulate(g['prices'],g['funding'],np.ascontiguousarray(ss),np.ascontiguousarray(g['bb']),rs.START,0,(rs.END-rs.START)//60000,RISK,4,g['step'],True,slip=2e-4,floor_on=True,floor_trigger=1.,floor_lock=.1,risk_col=4)
    return X.daily_from_curve(curve,len(g['prices'][0])//1440),t

def roots(g,t):
    out=[]
    for r_ in t[t[:,18]==0]:
        j=int(r_[0]);b=int((r_[1]-rs.START)//(g['step']*60000))
        while b>0 and g['ss'][j,b,0]==0:b-=1
        legs=t[t[:,17]==r_[17]];out.append(dict(R=legs[:,12].sum()/max(r_[15],1e-9),**g['flags'].get((j,b),{})))
    return pd.DataFrame(out)

RULES={'R1_room2_half':('room2',.5,-1),'R2_badsb_1.5x':('badsb',1.5,+1)}
def main():
    G=[setup(gr) for gr in GROUPS];base=[run(g,lambda fl:1.) for g in G];res=dict(notes=__doc__,groups=GROUPS,rules={})
    comb=lambda rs_:np.mean([r for r in rs_],axis=0);bst=X.stats(comb([b[0] for b in base]));res['baseline']=bst
    print('baseline 30 coins (6 groups):',{k:[round(v,2) for v in x] for k,x in bst.items()},flush=True)
    L=pd.concat([roots(g,b[1]) for g,b in zip(G,base)]).fillna(False)
    for name,(k,m,sign) in RULES.items():
        y=L[L[k]==True];n=L[L[k]!=True];d=y.R.mean()-n.R.mean()
        sims=[run(g,lambda fl,k=k,m=m:m if fl.get(k) else 1.) for g in G];st=X.stats(comb([s[0] for s in sims]))
        share=np.mean([fl.get(k,False) for g in G for fl in g['flags'].values()]);mm=1+(m-1)*share
        ctrl=X.stats(comb([run(g,lambda fl,mm=mm:mm)[0] for g in G]))
        better=sum(X.stats(s[0])['full'][0]>X.stats(b[0])['full'][0] for s,b in zip(sims,base))
        Gt=dict(G1=bool(len(y)>=50 and np.sign(d)==sign),G2=st['full'][0]>=bst['full'][0]+.05,G3=better>=4,G4=st['full'][0]>ctrl['full'][0])
        res['rules'][name]=dict(n_yes=len(y),yes_R=float(y.R.mean()),no_R=float(n.R.mean()),stats=st,control=ctrl,groups_better=better,gates=Gt,passed=all(Gt.values()))
        print(f"{name}: trades YES {len(y)} R {y.R.mean():+.3f} vs NO {n.R.mean():+.3f} | 30-coin Calmar {st['full'][0]:.2f} CAGR {st['full'][1]:.1f}% DD {st['full'][2]:.1f}% (baseline {bst['full'][0]:.2f} / {bst['full'][1]:.1f}% / {bst['full'][2]:.1f}%) | flat x{mm:.2f} control {ctrl['full'][0]:.2f} | groups better {better}/6 | {Gt} PASS={all(Gt.values())}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
