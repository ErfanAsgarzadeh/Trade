"""Null control for round 3: drop whole signal EPISODES (runs of consecutive same-side signal bars) at random with
probability p, same engine and baseline as r3_harness. If random thinning lifts Calmar as much as a filter, the filter
carries no information. Writes output/r3/thinning_null.json."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import r3_harness as h, run_suite as rs, fb_harness as fh

def episodes(side):
    """Label each nonzero signal bar with an episode id (new id when side changes or after a zero bar)."""
    ep=np.full(len(side),-1);cur=-1;prev=0
    for b,x in enumerate(side):
        if x!=0:
            if x!=prev:cur+=1
            ep[b]=cur
        prev=x
    return ep,cur+1

def thin(U,p,rng):
    s=U['sig'].copy()
    for k,sym in enumerate(U['symbols']):
        ep,n=episodes(s[k,:,0]);drop=rng.random(n)<p;m=(ep>=0)&drop[np.clip(ep,0,None)];s[k,m,0]=0
    return s

def calmar(U,sig,period='full'):
    a,t,c=h._sim(U,{'sig':sig},period,2);r=rs.summarize(a,t,c,*fh.PERIODS[period],U['symbols']);return r['cagr_pct']/r['max_dd_pct'],r['root_entries']

def main(ps=(.1,.2,.3),seeds=30):
    out={}
    for p in ps:
        rows=[]
        for sd in range(seeds):
            rng=np.random.default_rng(1000+sd);row={}
            for name in h.UNIVERSES:
                U=h.universe(name);row[name]=calmar(U,thin(U,p,rng))
            rows.append(row)
        cal={u:np.array([r[u][0] for r in rows]) for u in h.UNIVERSES};mean=np.mean([cal[u] for u in h.UNIVERSES],axis=0)
        out[str(p)]=dict({u:dict(p10=float(np.percentile(cal[u],10)),p50=float(np.median(cal[u])),p90=float(np.percentile(cal[u],90)),
                                  roots_mean=float(np.mean([r[u][1] for r in rows]))) for u in h.UNIVERSES},
                         mean3=dict(p10=float(np.percentile(mean,10)),p50=float(np.median(mean)),p90=float(np.percentile(mean,90))),
                         pass_rate_each_not_worse=float(np.mean([all(r[u][0]>=h.baseline()[u]['full|2']['calmar']-.02 for u in h.UNIVERSES) for r in rows])))
        print(p,json.dumps(out[str(p)]),flush=True)
    (h.OUT/'thinning_null.json').write_text(json.dumps(out,indent=1));return out

if __name__=='__main__':main()
