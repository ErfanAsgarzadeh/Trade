"""Round-2 final check (meeting: 6/6 votes "adopt RESCALED S3_gap only if this passes, never raw S3"). Written and
committed BEFORE running; single run, no tuning afterwards.

S3R = agent-4 S3_gap tiers (EMA50-EMA200 gap in ATR on the trade side: <=2 / 2-4 / >4) scaled by 1/m_train, where
m_train = realised mean risk multiplier of raw S3 on MAIN10 TRAIN trades (entry before 2025-01-01) -> mean ~1.0x.
PASS needs ALL (risk-neutral gates; CAGR gates R1/R4 reported for information only):
  F1 MAIN10 validation Calmar >= C3+D baseline (no 0.9x tolerance)
  F2 MAIN10 train Calmar >= 1.10 x baseline
  F3 OTHER20 full Calmar STRICTLY > baseline
  F4 portfolio (bot + C3 x0.3) full Calmar >= baseline AND max DD <= baseline + 1 pp
  F5 MAIN10 per-calendar-year Calmar (2022..2026): beats baseline in >= 3 of 5 years, AND 2025 and 2026 each >= baseline
  F6 OTHER20 per-calendar-year Calmar: beats baseline in >= 3 of 5 years
  F7 MAIN10 validation mean price-R per gap band strictly falls band1 > band2 > band3
  F8 causal
Also reported: raw S3, flat-1.16x control (C3+D with every trade at raw S3's mean multiplier), realised mean multiplier
of S3R on MAIN10 and OTHER20 (train/valid), trade count per band.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.ideas import c3bench_d as BD, c3r2_a4_sizing as S, ltf_search as L
B=BD.B
SPLIT_BAR=lambda d:(rs.SPLIT-rs.START)//(240*60000)

def raw_mult(d):
    le,se=BD.confirm_signals(d);ml,ms=S.mults(d,'S3_gap');return le,se,ml,ms

def run_with(d,scale=1.,flat=None):
    le,se,ml,ms=raw_mult(d)
    if flat is not None:ml=ms=np.full(d['n'],float(flat))
    return S.engine_s(d['o'],d['h'],d['l'],d['c'],d['atr'],le,se,d['wk'],d['wk'],(ml*scale).astype(float),(ms*scale).astype(float),.0006,.0002,d['fb'],300)

def m_train():
    m=[]
    for s in B.MAIN10:
        d=B.coin(s);T=run_with(d);m+=list(T[T[:,0]<SPLIT_BAR(d),9])
    return float(np.mean(m))

def yearly(r):
    dates=pd.to_datetime(rs.START,unit='ms')+pd.to_timedelta(np.arange(len(r)),unit='D');out={}
    for y in range(2022,2027):
        k=(dates.year==y);out[y]=float(L.calmar(r[k])[0])
    return out

def band_R(variant_fn):
    rows=[]
    for s in B.MAIN10:
        d=B.coin(s);le,se,ml,ms=raw_mult(d);T=variant_fn(d)
        for t in T:
            if t[0]<SPLIT_BAR(d):continue
            sb=int(t[0])-1;m=(ml if t[2]>0 else ms)[sb];rows.append((m,t[4]))
    a=np.array(rows);return {f'{b}x':dict(n=int((a[:,0]==b).sum()),mean_R=float(a[a[:,0]==b,1].mean())) for b in (1.5,1.,.5)}

def main():
    mt=m_train();print('m_train (raw S3 mean multiplier, MAIN10 train trades):',round(mt,4),flush=True)
    fns={'S3R':lambda d,v=None:run_with(d,1/mt)[:,:9],'S3_raw':lambda d,v=None:run_with(d)[:,:9],'FLAT_116':lambda d,v=None:run_with(d,flat=1.16)[:,:9]}
    b=B.baseline();out=dict(notes=__doc__,m_train=mt,baseline=b,variants={})
    by_base={u:yearly(B.series(BD.d_trades,None,c)[0]) for u,c in (('main',B.MAIN10),('other',B.OTHER20))}
    for name,fn in fns.items():
        r=B.evaluate(fn);cz=B.check_causal(fn,None);rd=BD.verdict(r)
        yr={u:yearly(B.series(fn,None,c)[0]) for u,c in (('main',B.MAIN10),('other',B.OTHER20))}
        wins={u:sum(yr[u][y]>by_base[u][y] for y in yr[u]) for u in yr}
        mm=[];
        for u,c in (('MAIN10',B.MAIN10),('OTHER20',B.OTHER20)):
            T=np.concatenate([run_with(B.coin(s),1/mt if name=='S3R' else 1.,1.16 if name=='FLAT_116' else None) for s in c]);mm.append((u,float(T[:,9].mean())))
        bands=band_R(lambda d:run_with(d,1/mt)) if name=='S3R' else None
        m,o,p=r['main'],r['other'],r['port'];bm,bo,bp=b['main'],b['other'],b['port']
        F=dict(F1_valid=m['oos'][0]>=bm['oos'][0],F2_train=m['train'][0]>=1.10*bm['train'][0],F3_other=o['full'][0]>bo['full'][0],
               F4_port=p['full'][0]>=bp['full'][0] and p['full'][2]<=bp['full'][2]+1,
               F5_years_main=wins['main']>=3 and yr['main'][2025]>=by_base['main'][2025] and yr['main'][2026]>=by_base['main'][2026],
               F6_years_other=wins['other']>=3,F7_bands=(bands['1.5x']['mean_R']>bands['1.0x']['mean_R']>bands['0.5x']['mean_R']) if bands else None,F8_causal=cz['causal'])
        ok=all(v for v in F.values() if v is not None)
        out['variants'][name]=dict(eval=r,gates=F,passed=ok,R_gates_info=rd,yearly=yr,year_wins=wins,mean_mult=mm,bands=bands)
        print(f"{name}: MAIN10 Calmar train {m['train'][0]:.2f} valid {m['oos'][0]:.2f} CAGR {m['full'][1]:.1f}% DD {m['full'][2]:.1f}% | OTHER20 Calmar {o['full'][0]:.3f} CAGR {o['full'][1]:.1f}% | PORT CAGR {p['full'][1]:.1f}% DD {p['full'][2]:.1f}% Calmar {p['full'][0]:.2f} | years won main {wins['main']}/5 other {wins['other']}/5 | mult {mm} | PASS={ok} fails={[k for k,v in F.items() if v is False]}",flush=True)
        if bands:print('  validation bands:',bands,flush=True)
    out['baseline_yearly']=by_base;print('baseline yearly Calmar',{u:{y:round(v,2) for y,v in by_base[u].items()} for u in by_base})
    for n_ in fns:print(n_,{u:{y:round(v,2) for y,v in out['variants'][n_]['yearly'][u].items()} for u in ('main','other')})
    (B.OUT/'r2_final.json').write_text(json.dumps(out,indent=1,default=float))
if __name__=='__main__':main()
