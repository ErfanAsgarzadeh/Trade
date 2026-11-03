"""PREDECLARED_1H.md: 1h Shahin variants vs the shipped 4h Shahin, three views."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.shahin2 import lab as LB, lab1h as L1
V={'1h N10':dict(N=10),'1h N20':dict(N=20),'1h N40':dict(N=40),'1h N40, 1h ATR regime':dict(N=40,atr='1h'),
   '1h N40, trail 4h':dict(N=40,trail4h=True),'1h N40, stop 4h':dict(N=40,stop4h=True),'1h N40, trail 4h + stop 4h':dict(N=40,trail4h=True,stop4h=True)}
def show(n,a,c,o):print(f"{n:28s} ALONE CAGR {a['full'][1]:5.1f} DD {a['full'][2]:4.1f} Cal tr {a['train'][0]:.2f} va {a['valid'][0]:.2f} WR {a['win']:.1f} legs {a['legs']} | ACCOUNT CAGR {c['full'][1]:5.1f} DD {c['full'][2]:4.1f} Cal tr {c['train'][0]:.2f} va {c['valid'][0]:.2f} | OTHER30 Cal {o['full'][0]:.2f} CAGR {o['full'][1]:.1f} DD {o['full'][2]:.1f}",flush=True)
def main():
    res={};legs,a=LB.run(LB.MAIN5,{});_,o=LB.run(LB.OTHER30,{});LB.ctx.cache_clear();c=LB.account(legs);res['4h baseline (shipped)']=dict(alone=a,account=c,other30=o);show('4h baseline (shipped)',a,c,o);b=res['4h baseline (shipped)']
    for n,v in V.items():
        legs,a=L1.run(LB.MAIN5,v);_,o=L1.run(LB.OTHER30,v);L1.ctx.cache_clear();c=LB.account(legs)
        ok=a['train'][0]>=b['alone']['train'][0] and a['valid'][0]>=b['alone']['valid'][0] and c['train'][0]>=b['account']['train'][0] and c['valid'][0]>=b['account']['valid'][0] and c['full'][2]<=b['account']['full'][2]+1 and o['full'][0]>=b['other30']['full'][0]
        res[n]=dict(variant=v,alone=a,account=c,other30=o,passed=bool(ok));show(n,a,c,o)
    print('PASSED:',[n for n,r in res.items() if r.get('passed')]);(LB.OUT/'tf_1h.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
