"""Round-2 bench: goal = capture MORE of big trends. Baseline = C3 + D (agent 1: enter only when a close within 3 bars
goes beyond the signal bar's close). DO NOT EDIT from an agent. Same API as c3bench: trades_fn(d, variant) -> trades.

GATES (pre-declared, all must hold; numbers are this bench's baseline = C3+D):
  R1 MAIN10 train CAGR >= baseline + 5 pp  AND  MAIN10 train Calmar >= 0.95 x baseline
  R2 MAIN10 validation CAGR >= baseline     AND  MAIN10 validation Calmar >= 0.90 x baseline
  R3 OTHER20 full-period CAGR >= baseline  (generalisation to the 20 coins never chosen for C3)
  R4 portfolio (bot + C3 x0.3) full CAGR >= baseline + 2 pp AND portfolio full max DD <= baseline + 2 pp
  R5 causal
Also reported: share of big-trend moves (>=30%, >=7 days) captured on MAIN10 (trend_capture()).
"""
from pathlib import Path
import sys,json,functools
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import c3bench as B, c3_a1_followthrough as A1, mtf_search as M, trend_audit as TA
D=dict(confirm=3,level='close')
def d_trades(d,variant=None):return A1.trades_fn(d,D)
def confirm_signals(d):
    """C3+D entry arrays (le, se) for agents who build on D: confirmation bars, weekday-masked by the engine."""
    le,se=A1._filters(d,{});return A1._confirm(d,le,se,3,'close')
B.baseline_trades=d_trades;B.OUT=B.X.OUT/'c3d';B.baseline.cache_clear()

def trend_capture(fn,variant=None):
    """Move-weighted share of big-trend log-moves held WITH the trend on MAIN10 (hindsight diagnostic)."""
    num=den=0.
    for s in B.MAIN10:
        d=B.coin(s);T=fn(d,variant);c=d['c'];state=np.zeros(d['n'])
        for t in T:state[int(t[0]):int(t[1])+1]=t[2]
        dc=c[5::6];piv=TA.zigzag(dc)
        for i in range(len(piv)-1):
            i0,i1=piv[i],piv[i+1];mv=dc[i1]/dc[i0]-1
            if abs(mv)<.30 or i1-i0<7:continue
            sd=1 if mv>0 else -1;b0,b1=(i0+1)*6,(i1+1)*6;lr=np.diff(np.log(c[b0:b1+1]))*sd;tot=abs(np.log(1+mv))
            num+=lr[state[b0:b1]==sd].sum();den+=tot
    return float(num/den*100)

def verdict(r):
    b=B.baseline();m,bm=r['main'],b['main']
    ck={'R1_train':m['train'][1]>=bm['train'][1]+5 and m['train'][0]>=.95*bm['train'][0],
        'R2_valid':m['oos'][1]>=bm['oos'][1] and m['oos'][0]>=.90*bm['oos'][0],
        'R3_other20':r['other']['full'][1]>=b['other']['full'][1],
        'R4_portfolio':r['port']['full'][1]>=b['port']['full'][1]+2 and r['port']['full'][2]<=b['port']['full'][2]+2}
    return dict(checks=ck,passed=all(ck.values()))
B.verdict=verdict

def run(name,variants,fn,notes=''):
    out=B.run(name,variants,fn,notes)
    for v in variants:
        cap=trend_capture(fn,variants[v]);out['variants'][v]['trend_capture']=cap
        mm=out['variants'][v]['main'];print(f"{name}/{v}: MAIN10 CAGR train {mm['train'][1]:.1f}% valid {mm['oos'][1]:.1f}% | big-trend capture {cap:.1f}% (baseline {BASE_CAPTURE():.1f}%)",flush=True)
    (B.OUT/f'{name}.json').write_text(json.dumps(out,indent=1,default=float));return out

@functools.lru_cache(1)
def BASE_CAPTURE():return trend_capture(d_trades)

if __name__=='__main__':
    b=B.baseline();print('C3+D baseline',{k:{p:[round(x,2) for x in v] for p,v in b[k].items()} for k in ('main','other','port')},'| capture',round(BASE_CAPTURE(),1))
