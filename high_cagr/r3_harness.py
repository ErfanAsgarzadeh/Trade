"""Frozen bench for ROUND 3 (false breakouts + choppy market), see output/r3/predeclared_r3.json. DO NOT EDIT from an agent.

Baseline = the DEPLOYED bot: 4B + V2 stop-width + BTC Kumo gate B, DONCHIAN10 4h, R=0.75%, initial stop 2.0 ATR, 4 slots,
run separately on three universes: OLD5 (tuned on), NEW10 and HOLD10 (untouched by tuning).

A candidate is  build_fn(U, variant) -> dict with any of
  'sig'      : (ns, nbars, 4) [side, entry price, initial stop, rank score]   start from U['sig'].copy()
  'bb'       : (ns, nbars, 12) trail/bar columns: 0 low line, 1 atr, 2 close, 3 high line, 4/5 3-bar low/high,
               6/7 4-bar low/high, 8/9 breakout level long/short, 10/11 Kumo edge long/short   start from U['bb'].copy()
  'kwargs'   : extra keyword args for the simulate function (override baseline policy keys)
  'simulate' : OPTIONAL replacement for high_cagr.kernel_fixes.simulate (same signature + your new kwargs, all
               default OFF). The bench checks it reproduces the baseline bit-for-bit when called with the baseline kwargs.
U (one universe): name, symbols, frames{sym: DataFrame of CLOSED 4h bars incl. BTCUSDT}, ix{sym: signal bar -> frame row},
side{sym: +1/-1/0 already BTC-gated}, sig, bb, step(=240), inside (bool per signal bar: BTC close inside its Kumo).
For signal bar b use only frame rows <= ix[sym][b] and bb/sig rows <= b. check_causal() enforces this by truncation.
"""
from pathlib import Path
import sys,json,functools
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs, fb_harness as fh
from high_cagr.kernel_fixes import simulate as base_simulate
from high_cagr.btc_regime_experiment import btc_inside_kumo
from high_cagr.stage2_experiment import OLD,NEW,frame
HOLD=[c['symbol'] for c in json.loads((ROOT/'high_cagr/output/stage3_selection.json').read_text())['chosen']]
UNIVERSES={'OLD5':OLD,'NEW10':NEW,'HOLD10':HOLD}
POLICY={**ab.FIX4['4B'],'vol_max_pct':.056,'vol_mid_pct':.045,'vol_mid_mult':.5};RISK=.0075;SLOTS=4
OUT=ROOT/'high_cagr/output/r3';PER=('full','H1','H2','Y2026')

@functools.lru_cache(3)
def universe(name):
    symbols=UNIVERSES[name];frames={s:frame(s) for s in set(symbols)|{'BTCUSDT'}};fk={(s,'4h','standard'):f for s,f in frames.items()}
    case=dict(symbols=symbols,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=RISK,max_open_positions=SLOTS)
    ss,bb,step=rs.inputs(case,fk);bb=np.concatenate([bb,ab.channel_columns(case,fk)],axis=2)
    bnd=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    ix={s:(np.searchsorted(frames[s].timestamp.to_numpy(np.int64)+step*60000,bnd,side='right')-1)[:ss.shape[1]] for s in frames}
    inside=btc_inside_kumo(fk,ss.shape[1])
    for k,s in enumerate(symbols):
        if s!='BTCUSDT':ss[k,inside,0]=0
    extra=[]
    for s in symbols:
        f=frames[s];g=lambda c:f[c].to_numpy()[ix[s]]
        extra.append(np.column_stack([np.maximum(g('donchian_high_10'),g('kumo_top')),np.minimum(g('donchian_low_10'),g('kumo_bottom')),g('kumo_top'),g('kumo_bottom')]))
    bb=np.concatenate([bb,np.stack(extra)],axis=2)
    for a in (ss,bb):a.setflags(write=False)
    return dict(name=name,symbols=symbols,frames=frames,ix=ix,side={s:ss[k,:,0].astype(int) for k,s in enumerate(symbols)},sig=ss,bb=bb,step=step,inside=inside,
                prices=fh._stacked('prices',name,symbols),funding=fh._stacked('funding',name,symbols))

def _sim(U,c,period,bps):
    kw={**POLICY,**c.get('kwargs',{})};b,e=fh.PERIODS[period];sim=c.get('simulate',base_simulate)
    return sim(U['prices'],U['funding'],np.ascontiguousarray(c.get('sig',U['sig'])),np.ascontiguousarray(c.get('bb',U['bb'])),rs.START,b,e,RISK,SLOTS,U['step'],True,slip=bps/1e4,**kw)

def _ledger(t):
    """FALSE_BREAKOUT / CHOP cost as % of equity at entry (losing root positions with MFE < 1R; FB = MFE < 0.3R)."""
    fb=ch=0.;nf=nc=0;wins=[]
    for r in t[t[:,18]==0]:
        legs=t[t[:,17]==r[17]];net=legs[:,12].sum();pct=net/r[14]*100;wins.append(pct)
        if net<0 and legs[:,9].sum()<0 and r[19]<1:
            if r[19]<.3:fb+=pct;nf+=1
            else:ch+=pct;nc+=1
    w=np.sort(np.array(wins))[::-1];top=float(w[:max(1,len(w)//20)].sum()) if len(w) else 0.
    return dict(fb_n=nf,fb_cost=fb,chop_n=nc,chop_cost=ch,top5pct_winners=top)

def evaluate(build_fn=None,variant=None):
    res={}
    for name in UNIVERSES:
        U=universe(name);c=build_fn(U,variant) if build_fn else {};r={}
        for per in PER:
            for bps in ((2,5) if per=='full' else (2,)):
                a,t,curve=_sim(U,c,per,bps);s=rs.summarize(a,t,curve,*fh.PERIODS[per],U['symbols'])
                r[f'{per}|{bps}']=dict(cagr=s['cagr_pct'],dd=s['max_dd_pct'],calmar=s['cagr_pct']/s['max_dd_pct'],net=s['net_profit'],roots=s['root_entries'],win=s['win_rate_pct'])
                if per=='full' and bps==2:r['ledger']=_ledger(t)
        res[name]=r
    return res

@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline_r3.json'
    if p.exists():return json.loads(p.read_text())
    OUT.mkdir(parents=True,exist_ok=True);r=evaluate();p.write_text(json.dumps(r,indent=1));return r

def _mean(r,key):return float(np.mean([r[u][key]['calmar'] for u in UNIVERSES]))
def verdict(r,target):
    """target: 'fb', 'chop' or 'both' (pre-declared by the method)."""
    b=baseline();c={}
    cost=lambda x,k:sum(x[u]['ledger'][f'{k}_cost'] for u in UNIVERSES)
    keys=('fb','chop') if target=='both' else (target,)
    c['target_cost_cut_15pct']=sum(cost(r,k) for k in keys)>=.85*sum(cost(b,k) for k in keys)   # costs are negative
    c['calmar_each_universe_not_worse']=all(r[u]['full|2']['calmar']>=b[u]['full|2']['calmar']-.02 for u in UNIVERSES)
    c['mean_calmar_+0.05']=_mean(r,'full|2')>=_mean(b,'full|2')+.05
    c['mean_calmar_5bps_not_worse']=_mean(r,'full|5')>=_mean(b,'full|5')
    c['dd_each_universe_not_worse_1pt']=all(r[u]['full|2']['dd']<=b[u]['full|2']['dd']+1. for u in UNIVERSES)
    c['H1_H2_mean_not_worse']=all(_mean(r,f'{p}|2')>=_mean(b,f'{p}|2') for p in ('H1','H2'))
    c['untouched_mean_+0.03']=np.mean([r[u]['full|2']['calmar'] for u in ('NEW10','HOLD10')])>=np.mean([b[u]['full|2']['calmar'] for u in ('NEW10','HOLD10')])+.03
    return dict(checks={k:bool(v) for k,v in c.items()},passed=bool(all(c.values())))

def check_causal(build_fn,variant,cutoffs=(.35,.6,.85)):
    """Rebuild on histories truncated at several bars; outputs at bars <= cut must not change."""
    for name in UNIVERSES:
        U=universe(name);full=build_fn(U,variant);nb=U['sig'].shape[1];has=np.where((U['sig'][:,:,0]!=0).any(0))[0]
        for q in cutoffs:
            cut=int(has[np.searchsorted(has,int(nb*q))]);T=dict(U);T['frames']={};T['ix']={}   # cut ON a signal bar so a peek at bar cut+1 shows
            for s,f in U['frames'].items():
                row=int(U['ix'][s][cut]);T['frames'][s]=f.iloc[:row+1].copy();T['ix'][s]=np.minimum(U['ix'][s],row)
            sig=U['sig'].copy();sig[:,cut+1:]=0;bb=U['bb'].copy();bb[:,cut+1:]=np.nan;T['sig']=sig;T['bb']=bb
            T['side']={s:np.where(np.arange(nb)<=cut,v,0) for s,v in U['side'].items()};T['inside']=np.where(np.arange(nb)<=cut,U['inside'],False)
            part=build_fn(T,variant)
            for k in ('sig','bb'):
                if k in full or k in part:
                    a=np.asarray(full.get(k,U[k]))[:,:cut+1];b_=np.asarray(part.get(k,T[k]))[:,:cut+1]
                    if not np.array_equal(a,b_,equal_nan=True):return dict(causal=False,universe=name,array=k,cut=q)
    return dict(causal=True)

def check_parity(sim):
    """A custom simulate must reproduce the baseline exactly with the baseline kwargs."""
    for name in UNIVERSES:
        U=universe(name);b,e=fh.PERIODS['full']
        x=base_simulate(U['prices'],U['funding'],U['sig'],np.ascontiguousarray(U['bb']),rs.START,b,e,RISK,SLOTS,U['step'],True,slip=2e-4,**POLICY)
        y=sim(U['prices'],U['funding'],U['sig'],np.ascontiguousarray(U['bb']),rs.START,b,e,RISK,SLOTS,U['step'],True,slip=2e-4,**POLICY)
        for i in range(3):
            if not np.array_equal(np.asarray(x[i]),np.asarray(y[i]),equal_nan=True):return dict(parity=False,universe=name,output=i)
    return dict(parity=True)

def run_method(method,target,variants,build_fn,notes=''):
    """Max 4 variants, all declared before running. Writes output/r3/<method>.json."""
    assert len(variants)<=4,'max 4 pre-declared variants';assert target in ('fb','chop','both')
    b=baseline();out=dict(method=method,target=target,notes=notes,variants={})
    for v,var in variants.items():
        cz=check_causal(build_fn,var);c0=build_fn(universe('OLD5'),var);pz=check_parity(c0['simulate']) if 'simulate' in c0 else dict(parity=True)
        r=evaluate(build_fn,var);vd=verdict(r,target);ok=bool(vd['passed'] and cz['causal'] and pz['parity'])
        out['variants'][v]=dict(variant=var,causal=cz,parity=pz,results=r,verdict=vd,passed=ok)
        L=lambda u:r[u]['ledger'];bl=lambda u:b[u]['ledger']
        print(f"{method}/{v}: causal={cz['causal']} parity={pz['parity']} | Calmar OLD5 {r['OLD5']['full|2']['calmar']:.2f} ({b['OLD5']['full|2']['calmar']:.2f}) "
              f"NEW10 {r['NEW10']['full|2']['calmar']:.2f} ({b['NEW10']['full|2']['calmar']:.2f}) HOLD10 {r['HOLD10']['full|2']['calmar']:.2f} ({b['HOLD10']['full|2']['calmar']:.2f}) | "
              f"FB {sum(L(u)['fb_n'] for u in UNIVERSES)}/{sum(bl(u)['fb_n'] for u in UNIVERSES)} cost {sum(L(u)['fb_cost'] for u in UNIVERSES):.0f}/{sum(bl(u)['fb_cost'] for u in UNIVERSES):.0f}%eq | "
              f"CHOP {sum(L(u)['chop_n'] for u in UNIVERSES)}/{sum(bl(u)['chop_n'] for u in UNIVERSES)} cost {sum(L(u)['chop_cost'] for u in UNIVERSES):.0f}/{sum(bl(u)['chop_cost'] for u in UNIVERSES):.0f}%eq | PASS={ok}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{method}.json').write_text(json.dumps(out,indent=1,default=float));return out
