"""POST-HOC neighbourhood of winner_trail.py (chosen after seeing its results): trigger R x channel."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, htf_confirm as hc, winner_trail as wt
COLS={'3bar':4,'4bar':6,'15bar':14,'20bar':12}
if __name__=='__main__':
    ctx=bench.load();b=json.loads((bench.OUT/'htf_confirm.json').read_text())['baseline_2A5A']['results'];out={}
    for ch,col in COLS.items():
        for r in (3.,4.,5.,6.,8.):
            v=dict(r=r,col=col);res=bench.evaluate(wt.build(ctx,v));vd=hc.verdict(res,b);f=res['full|2']
            out[f'{ch}@{r:g}R']=dict(variant=v,results=res,verdict=vd)
            print(f"{ch:5s} after {r:g}R: CAGR {f['cagr']:5.1f} DD {f['dd']:4.1f} Calmar {f['calmar']:.2f} | train {res['train|2']['calmar']:.2f} oos {res['oos|2']['calmar']:.2f} @5 {res['full|5']['calmar']:.2f} PASS={vd['passed']}",flush=True)
    (bench.OUT/'winner_trail_sensitivity.json').write_text(json.dumps(out,indent=1,default=float))
