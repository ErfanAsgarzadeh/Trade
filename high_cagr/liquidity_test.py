"""Point-in-time liquidity rule test (see output/liq/predeclared_liquidity.json).
Rank = trailing 30d quote volume on CLOSED 4h bars at each signal bar; the mask only removes entries/adds."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import verify_atr_expansion as v, run_suite as rs, fb_harness as fh, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
OUT=ROOT/'high_cagr/output/liq';OUT.mkdir(parents=True,exist_ok=True)
U20=v.NEW+v.HOLD;ALL25=v.OLD+U20;PER=('full','H1','H2','Y2026')

def qvol(U,bars):
    out=[]
    for s in U['symbols']:
        f=U['frames'][s];q=(f.volume*f.close).rolling(bars,min_periods=bars).sum().to_numpy();i=U['ix'][s]
        x=np.where(i>=0,q[np.clip(i,0,None)],np.nan);out.append(x)
    return np.stack(out)
def ranks(q):
    r=np.full(q.shape,np.inf);ok=np.isfinite(q)
    for b in range(q.shape[1]):
        c=np.where(ok[:,b])[0]
        if len(c):r[c[np.argsort(-q[c,b])],b]=np.arange(1,len(c)+1)
    return r
def run(U,mask=None,slots=4,periods=PER,keep=None):
    g=U['ss'].copy()
    if mask is not None:g[~mask,0]=0
    for k,s in enumerate(U['symbols']):
        if s!='BTCUSDT':g[k,U['inside'],0]=0
    pr,fu,bb,syms=U['prices'],U['funding'],U['bb'],U['symbols']
    if keep is not None:g=g[keep];pr=pr[keep];fu=fu[keep];bb=np.ascontiguousarray(bb[keep]);syms=[syms[k] for k in keep]
    out={}
    for per in periods:
        b,e=fh.PERIODS[per];a,t,c=simulate(pr,fu,g,bb,rs.START,b,e,.0075,slots,U['step'],True,slip=2/1e4,**ab.FIX4['4B'],**v.V2)
        r=rs.summarize(a,t,c,b,e,syms);out[per]=dict(cagr=r['cagr_pct'],dd=r['max_dd_pct'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'])
    return out

def main():
    res={}
    # ---------- T1 ----------
    U=v.universe(U20,'U20');rk={w:ranks(qvol(U,w)) for w in (180,540)}
    for w,r in rk.items():
        tag='' if w==180 else '_90d'
        res['T1'+tag]={'ALL20':run(U),'TOP10':run(U,r<=10),'BOT10':run(U,(r>10)&np.isfinite(r))}
    rng=np.random.default_rng(20261007);null=[]
    for _ in range(200):
        keep=np.sort(rng.choice(20,10,replace=False));m=np.zeros(U['ss'].shape[:2],bool);m[keep]=True
        null.append(run(U,m,periods=('full',))['full']['calmar'])
    null=np.array(null);t1=res['T1'];top,bot,all_=(t1[k]['full']['calmar'] for k in ('TOP10','BOT10','ALL20'))
    subs=sum(t1['TOP10'][p]['calmar']>t1['BOT10'][p]['calmar'] for p in ('H1','H2','Y2026'))
    pct=float((null<top).mean()*100)
    res['T1_null']=dict(p10=float(np.percentile(null,10)),p50=float(np.median(null)),p90=float(np.percentile(null,90)),top10_percentile=pct)
    res['T1_checks']=dict(top_gt_bot=bool(top>bot),top_gt_all=bool(top>all_),subperiods_won=int(subs),top_ge_p90=bool(pct>=90))
    res['T1_pass']=bool(top>bot and top>all_ and subs>=2 and pct>=90)
    # top-10 membership share per symbol (descriptive)
    r=rk[180];res['T1_top10_share']={s:float(np.mean(r[k][np.isfinite(r[k])]<=10)) for k,s in enumerate(U20)}
    # ---------- T2 / T3 ----------
    A=v.universe(ALL25,'ALL25');ra=ranks(qvol(A,180));per_sym={}
    for k,s in enumerate(ALL25):
        x=run(A,slots=1,periods=('full',),keep=[k])['full'];fin=np.isfinite(ra[k]);x['avg_rank25']=float(ra[k][fin].mean());per_sym[s]=x
    res['T2_per_symbol']=per_sym
    def spear(syms):
        c=pd.Series([per_sym[s]['calmar'] for s in syms]).rank().to_numpy();q=pd.Series([per_sym[s]['avg_rank25'] for s in syms]).rank().to_numpy()
        rho=np.corrcoef(c,q)[0,1];pr=np.random.default_rng(1);perm=np.array([np.corrcoef(c,pr.permutation(q))[0,1] for _ in range(10000)])
        return dict(rho=float(rho),p_one_sided=float((perm<=rho).mean()))
    res['T2_U20']=spear(U20);res['T2_ALL25']=spear(ALL25);res['T2_pass']=bool(res['T2_U20']['rho']<0 and res['T2_U20']['p_one_sided']<.05)
    res['T3']={'ALL25':run(A),**{f'TOP{n}':run(A,ra<=n) for n in (5,8,10)}}
    (OUT/'liquidity_results.json').write_text(json.dumps(res,indent=1));return res

if __name__=='__main__':
    r=main();print(json.dumps({k:r[k] for k in r if k not in ('T2_per_symbol','T1_top10_share')},indent=1))
    for s,x in sorted(r['T2_per_symbol'].items(),key=lambda kv:kv[1]['avg_rank25']):print(f"{s:14s} rank {x['avg_rank25']:5.1f}  calmar {x['calmar']:6.2f}  cagr {x['cagr']:6.1f}  dd {x['dd']:5.1f}")
