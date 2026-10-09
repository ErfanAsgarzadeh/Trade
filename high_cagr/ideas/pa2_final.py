"""pa2_final - final step of the second Ghoghnous meeting. Written and committed BEFORE running; one run, no tuning.

Meeting result (high_cagr/output/ideas/pa_opt2/): 3 of 64 builder variants passed Q1-Q6 and survived their auditors, all
from 'confluence' (skip_le2, tilt, lin); auditors: real but modest, two of the four factors (BAR size, BTC 6-bar move)
flipped sign in validation, the two that held are F1 VOL (volrank < 0.354: low volatility regime) and F2 EXH (EMA50 6-bar
slope against/not with the trade, < 0.146 ATR) - also the anatomy diagnostician's top two hypotheses (H1, H3).
'exits' V5 oppKR (exit at the close of a bar printing an opposite C1 signal) passed every gate except Q1 (train unchanged).
Variants (factor definitions and cut-offs exactly as in pa2_confluence.py; exit as pa2_exits.engine_x):
  F1 gate2        trade only when F1 AND F2 (normal risk)                      - only the two robust factors
  F2 gate2_opp    F1 gate2 + oppKR exit
  F3 vol_opp      F1 only (volrank < 0.354) + oppKR exit
  F4 skip_le2_opp confluence skip_le2 (4-factor score >= 3) + oppKR exit
  F5 tilt_opp     confluence tilt + oppKR exit
  F6 lin_opp      confluence lin + oppKR exit
Gates: pabench2 Q1-Q6 unchanged. WINNER rule (fixed now): among passing variants, the one with the FEWEST factors
(F1/F2-only variants before 4-factor ones), ties -> higher TRAIN PA Calmar. Information only (not used to choose):
neighbouring cut-offs of the winner and its stand-alone compounding CAGR/DD at 0.25/0.5/1% risk.
"""
import sys;sys.path.insert(0,'/home/user/Trade')
import numpy as np
from high_cagr.ideas import pabench2 as Q, pabench as PB, pa2_confluence as CF, pa2_exits as EX

def mult_for(d,side,spec):
    vr,sl,sz,b6=CF.feats(d,side);c=CF.CUT['q']
    with np.errstate(invalid='ignore'):
        f1=vr<c[0];f2=sl<c[1];score=f1.astype(int)+f2.astype(int)+(sz>=c[2]).astype(int)+(b6<c[3]).astype(int)
    if spec=='gate2':m=(f1&f2).astype(float)
    elif spec=='vol':m=f1.astype(float)
    else:m=np.asarray(dict(skip_le2=CF.VARIANTS['skip_le2'][1],tilt=CF.VARIANTS['tilt'][1],lin=CF.VARIANTS['lin'][1])[spec],float)[score]
    m=np.where(side==0,0.,m);return m

def run(d,spec,opp):
    side=Q.c1_side(d);n=len(side);g=d['sig'];m=mult_for(d,side,spec)
    op=side.astype(np.int8) if opp else np.zeros(0,np.int8)
    return EX.engine_x(d['P'],d['fc'],240,side,g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],m,np.full(n,30,np.int64),
                       0.,1.,0.,3.,0.,0,0.,np.zeros(0),np.zeros(0),op,PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP,250)

def fn(d,v):return run(d,*v)
VARIANTS={'F1_gate2':('gate2',False),'F2_gate2_opp':('gate2',True),'F3_vol_opp':('vol',True),
          'F4_skip_le2_opp':('skip_le2',True),'F5_tilt_opp':('tilt',True),'F6_lin_opp':('lin',True)}
NFACT={'F1_gate2':2,'F2_gate2_opp':2,'F3_vol_opp':1,'F4_skip_le2_opp':4,'F5_tilt_opp':4,'F6_lin_opp':4}

if __name__=='__main__':
    for s in ('LINKUSDT','CRVUSDT'):   # with all multipliers 1 and no opp exit the engine must equal C1
        d=PB.coin(s);side=Q.c1_side(d);n=len(side);g=d['sig']
        b=EX.engine_x(d['P'],d['fc'],240,side,g['kind'][:n],g['lev'][:n],g['stp'][:n],g['val'][:n],d['atr'][:n],np.ones(n),np.full(n,30,np.int64),0.,1.,0.,3.,0.,0,0.,np.zeros(0),np.zeros(0),np.zeros(0,np.int8),PB.FEE,PB.SLIP,PB.RISK,PB.CAP,PB.MINSTOP,250)
        assert np.array_equal(np.asarray(Q.base_fn(d)),b)
    out=Q.run_idea('final',VARIANTS,fn,notes=__doc__)
    ok=[k for k,v in out['variants'].items() if v['passed']]
    win=sorted(ok,key=lambda k:(NFACT[k],-out['variants'][k]['pa']['train'][0]))[0] if ok else None
    print('WINNER',win,flush=True)
