"""Frozen bench for the five failure-report ideas. DO NOT EDIT from an idea agent.

Baseline = the failure report's winner HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4
(5 symbols, 4 slots, risk 0.75%, pyramid on), engine high_cagr.kernel_fixes (bit-identical to
high_cagr.kernel with defaults). Periods = run_suite full / train (<2025) / oos (2025-2026), each from $10k.

A candidate is build_fn(ctx, variant) -> dict with any of
  'sig'    : (n_sym, n_bars, 4 or 5) signals; start from base_sig(). cols 0 side(+1/-1/0), 1 price, 2 stop, 3 rank score,
             optional col 4 = root risk multiplier (e.g. 0.5 = half risk). Setting side=0 removes the signal (and the pyramid
             add at that bar).
  'bb'     : (n_sym, n_bars, 12) trail bars; start from base_bb(). 0 low line, 1 atr, 2 close, 3 high line,
             4/5 3-bar low/high, 6/7 4-bar low/high, 8/9 breakout level long/short, 10/11 Kumo edge long/short.
  'kwargs' : extra keyword switches of kernel_fixes.simulate (time_stop_bars, time_stop_mfe, partial_frac, partial_r,
             floor_on, floor_trigger, floor_lock, tight_after_r, tight_cols, ...).
ctx: frames[sym] = DataFrame of CLOSED 4h bars (see prepared columns), ix[sym][b] = frame row signal bar b is computed
from (last closed bar), symbols, step=240. Entry filters must only use rows <= ix[sym][b]; check_causal() verifies it.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as ab
from high_cagr.kernel_fixes import simulate
OUT=ROOT/'high_cagr/output/ideas';WINNER='HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4'
SYMBOLS=rs.SYMBOLS;RISK=.0075;SLOTS=4;PERIODS=rs.PERIODS
GATES=('G1 train and oos net > 0; G2 full Calmar >= baseline+0.05 at 2bps AND >= baseline at 5bps; '
       'G3 full maxDD <= baseline; G4 Calmar not worse than baseline in train AND in oos. Pass = all four.')

@functools.lru_cache(1)
def load():
    case=next(c for c in rs.grid() if c['id']==WINNER);frames=rs.load_frames();ss,bb,step=rs.inputs(case,frames)
    bb=np.concatenate([bb,ab.channel_columns(case,frames)],axis=2);f4={s:frames[s,'4h','standard'] for s in SYMBOLS}
    boundaries=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;ix={};extra=[]
    for s in SYMBOLS:
        f=f4[s];ix[s]=(np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,boundaries,side='right')-1)[:ss.shape[1]]
        g=lambda c:f[c].to_numpy()[ix[s]]
        extra.append(np.column_stack([np.maximum(g('donchian_high_10'),g('kumo_top')),np.minimum(g('donchian_low_10'),g('kumo_bottom')),g('kumo_top'),g('kumo_bottom')]))
    bb=np.concatenate([bb,np.stack(extra)],axis=2)
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy',mmap_mode='r') for s in SYMBOLS])
    funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy',mmap_mode='r') for s in SYMBOLS])
    return dict(case=case,frames=f4,ix=ix,symbols=SYMBOLS,step=step,sig=ss,bb=bb,prices=prices,funding=funding)

def base_sig():return load()['sig'].copy()
def base_bb():return load()['bb'].copy()

def _sim(c,period,bps):
    ctx=load();sig=np.ascontiguousarray(c.get('sig',ctx['sig']),dtype=np.float64);bb=np.ascontiguousarray(c.get('bb',ctx['bb']),dtype=np.float64)
    kw=dict(c.get('kwargs',{}))
    if sig.shape[2]>=5:kw['risk_col']=4
    b,e=PERIODS[period]
    return simulate(ctx['prices'],ctx['funding'],sig,bb,rs.START,b,e,RISK,SLOTS,ctx['step'],True,slip=bps/1e4,**kw),b,e

def positions(t):
    """Root-level positions (root + its add): symbol, side, entry/exit ms, net, mfe_r (root), exit reason of root."""
    rows=[]
    for r in t[t[:,18]==0]:
        legs=t[t[:,17]==r[17]];rows.append((SYMBOLS[int(r[0])],int(r[3]),int(r[1]),int(r[2]),float(legs[:,12].sum()),float(r[19]),int(r[13]),float(r[15])))
    return pd.DataFrame(rows,columns=['symbol','side','entry_ts','exit_ts','net','mfe_r','reason','risk_usd'])

def evaluate(c,keep=False):
    res={};extra={}
    for period in PERIODS:
        for bps in ((2,5) if period=='full' else (2,)):
            (a,t,curve),b,e=_sim(c,period,bps);r=rs.summarize(a,t,curve,b,e,SYMBOLS)
            res[f'{period}|{bps}']=dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],
                                       roots=r['root_entries'],adds=r['pyramid_adds'],win=r['win_rate_pct'],fees=r['fees'],chop_exits=int(a[20]),partials=int(a[21]),floor_events=int(a[16]))
            if period=='full' and bps==2:
                p=positions(t);loss=p[p.net<0]
                res['full|2']['losses']=int(len(loss));res['full|2']['loss_sum']=float(loss.net.sum())
                res['full|2']['no_follow_through']=dict(n=int((loss.mfe_r<.5).sum()),loss=float(loss[loss.mfe_r<.5].net.sum()))
                res['full|2']['giveback_ge1r']=dict(n=int((loss.mfe_r>=1).sum()),loss=float(loss[loss.mfe_r>=1].net.sum()))
                cv=curve[np.isfinite(curve).all(axis=1)];daily=cv[::24]
                extra=dict(curve=[[int(x),float(y)] for x,y in daily[:,:2]]+[[int(cv[-1,0]),float(cv[-1,1])]],positions=p)
    if keep:res['_extra']=extra
    return res

@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate({},keep=True);ex=r.pop('_extra');m=json.loads((ROOT/'high_cagr/output/matrix.json').read_text())['winner']
    for period in PERIODS:  # the bench must reproduce the report's audited winner exactly
        assert abs(r[f'{period}|2']['net']-m[period]['net_profit'])<1e-6 and r[f'{period}|2']['roots']==m[period]['root_entries'],period
    top=ex['positions'].sort_values('net',ascending=False).head(25)
    r['top25']=[[s,int(t_),float(n)] for s,t_,n in zip(top.symbol,top.entry_ts,top.net)];r['curve']=ex['curve']
    OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r,indent=1));return r

def verdict(r):
    b=baseline();ck={}
    ck['G1_train_oos_positive']=r['train|2']['net']>0 and r['oos|2']['net']>0
    ck['G2_calmar_up']=r['full|2']['calmar']>=b['full|2']['calmar']+.05 and r['full|5']['calmar']>=b['full|5']['calmar']
    ck['G3_dd_not_worse']=r['full|2']['dd']<=b['full|2']['dd']
    ck['G4_calmar_both_slices']=r['train|2']['calmar']>=b['train|2']['calmar'] and r['oos|2']['calmar']>=b['oos|2']['calmar']
    return dict(checks=ck,passed=all(ck.values()))

def top25_retention(p):
    b=baseline();keys={(s,t_):n for s,t_,n in zip(p.symbol,p.entry_ts,p.net)};base=sum(n for *_,n in b['top25'])
    return dict(kept=int(sum((s,t_) in keys for s,t_,_ in b['top25'])),pnl_ratio=float(sum(keys.get((s,t_),0.) for s,t_,_ in b['top25'])/base))

def check_causal(build_fn,variant,cutoffs=(.35,.6,.85)):
    """Rebuild the candidate on frames truncated at several bars; sig/bb at bars <= cut must not change."""
    ctx=load();full=build_fn(ctx,variant);nb=ctx['sig'].shape[1]
    for q in cutoffs:
        cut=int(nb*q);fr={};ixt={}
        for s in SYMBOLS:
            row=int(ctx['ix'][s][cut]);fr[s]=ctx['frames'][s].iloc[:row+1].copy();ixt[s]=np.minimum(ctx['ix'][s],row)
        part=build_fn({**ctx,'frames':fr,'ix':ixt},variant)
        for key in ('sig','bb'):
            if key in full:
                a=np.nan_to_num(np.asarray(full[key])[:,:cut+1],nan=-9e99);b_=np.nan_to_num(np.asarray(part[key])[:,:cut+1],nan=-9e99)
                if not np.array_equal(a,b_):return dict(causal=False,key=key,cut=q)
    return dict(causal=True)

def run_idea(name,variants,build_fn,notes=''):
    """Evaluate every declared variant, gate it, write output/ideas/<name>.json (with daily equity curves)."""
    b=baseline();ctx=load();out=dict(idea=name,notes=notes,gates=GATES,baseline={k:v for k,v in b.items() if k not in ('top25','curve')},variants={})
    for v,var in variants.items():
        c=build_fn(ctx,var);cz=check_causal(build_fn,var);r=evaluate(c,keep=True);ex=r.pop('_extra');vd=verdict(r)
        kept=None
        if 'sig' in c:kept=float((np.asarray(c['sig'])[:,:,0]!=0).sum()/(ctx['sig'][:,:,0]!=0).sum()*100)
        out['variants'][v]=dict(variant=var,causal=cz,signals_kept_pct=kept,results=r,top25=top25_retention(ex['positions']),verdict=vd,passed=bool(vd['passed'] and cz['causal']),curve=ex['curve'])
        f=r['full|2']
        print(f"{name}/{v}: CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} PF {f['pf']:.3f} | train {r['train|2']['calmar']:.2f} oos {r['oos|2']['calmar']:.2f} | @5bps {r['full|5']['calmar']:.3f} | causal={cz['causal']} PASS={out['variants'][v]['passed']}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{name}.json').write_text(json.dumps(out,indent=1,default=float));return out

if __name__=='__main__':
    b=baseline();print({k:{m:round(v[m],3) for m in ('cagr','net','dd','pf','calmar','roots')} for k,v in b.items() if '|' in k})
