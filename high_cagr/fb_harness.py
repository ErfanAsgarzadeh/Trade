"""Frozen test bench for the false-breakout study (see output/fb/predeclared_fb.json). DO NOT EDIT from an agent.

A method is a pure function  mask_fn(frames, ix, side, variant) -> {symbol: bool array over signal bars}
  frames[sym] : DataFrame of CLOSED 4h bars (open high low close volume atr kijun kumo_top/bottom donchian_* ...)
  ix[sym]     : int array, ix[sym][b] = row of frames[sym] that signal bar b is computed from (last closed bar)
  side[sym]   : int array over signal bars, +1/-1 breakout signal of the current strategy, 0 none (already BTC-gated)
True = entry allowed at that bar. The mask can only REMOVE signals (it also blocks pyramid adds at that bar).
Use only rows <= ix[sym][b] for bar b; check_causal() verifies this by truncating the history.
"""
from pathlib import Path
import sys,json,functools
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
from high_cagr.btc_regime_experiment import V2,btc_inside_kumo
from high_cagr.stage2_experiment import OLD,NEW,frame,folder
SYMBOLS=OLD+NEW;OUT=ROOT/'high_cagr/output/fb';CACHE=ROOT/'high_cagr/prepared_stage2'
def _minute(d):return int((pd.Timestamp(d,tz='UTC').timestamp()*1000-rs.START)//60000)
PERIODS={'H1':(_minute('2021-10-05'),_minute('2024-01-01')),'H2':(_minute('2024-01-01'),_minute('2026-01-01')),'Y2026':(_minute('2026-01-01'),_minute('2026-10-05')),'full':(_minute('2021-10-05'),_minute('2026-10-05'))}
POLICY={**ab.FIX4['4B'],**V2};RISK=.0075

def _stacked(kind,name='ALL15',symbols=None):
    p=CACHE/f'{name}_{kind}.npy'
    if not p.exists():
        arr=np.stack([np.load(folder(s)/f'{kind}.npy',mmap_mode='r') for s in (symbols or SYMBOLS)]);tmp=CACHE/f'{name}_{kind}.{np.random.randint(1e9)}.tmp.npy';np.save(tmp,arr);tmp.replace(p)
    return np.load(p,mmap_mode='r')

@functools.lru_cache(1)
def load():
    frames={s:frame(s) for s in SYMBOLS};fkey={(s,'4h','standard'):f for s,f in frames.items()}
    case=dict(symbols=SYMBOLS,entry_timeframe='4h',preset='standard',lookback=10,trail='DONCHIAN10',risk=RISK,max_open_positions=6)
    ss,bb,step=rs.inputs(case,fkey);bb=np.concatenate([bb,ab.channel_columns(case,fkey)],axis=2)
    inside=btc_inside_kumo(fkey,ss.shape[1]);g=ss.copy()
    for k,s in enumerate(SYMBOLS):
        if s!='BTCUSDT':g[k,inside,0]=0
    boundaries=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000
    ix={s:(np.searchsorted(frames[s].timestamp.to_numpy(np.int64)+step*60000,boundaries,side='right')-1)[:g.shape[1]] for s in SYMBOLS}
    side={s:g[k,:,0].astype(int) for k,s in enumerate(SYMBOLS)}
    return dict(frames=frames,ix=ix,side=side,sig=g,bb=bb,step=step,prices=_stacked('prices'),funding=_stacked('funding'))

def _apply(ctx,mask,symbols):
    k=[SYMBOLS.index(s) for s in symbols];g=ctx['sig'][k].copy()
    if mask is not None:
        for j,s in enumerate(symbols):
            m=np.asarray(mask[s],bool);assert m.shape==(g.shape[1],),(s,m.shape);g[j,~m,0]=0
    return g,k

def _run(ctx,mask,symbols,slots,bps,period):
    g,k=_apply(ctx,mask,symbols);name='ALL15' if len(k)==len(SYMBOLS) else ('OLD5' if symbols==OLD else 'NEW10');pr=_stacked('prices',name,symbols);fu=_stacked('funding',name,symbols)
    b,e=PERIODS[period];a,t,curve=simulate(pr,fu,g,np.ascontiguousarray(ctx['bb'][k]),rs.START,b,e,RISK,slots,ctx['step'],True,slip=bps/1e4,**POLICY)
    r=rs.summarize(a,t,curve,b,e,symbols);return dict(cagr=r['cagr_pct'],net=r['net_profit'],dd=r['max_dd_pct'],pf=r['profit_factor'],calmar=r['cagr_pct']/r['max_dd_pct'],roots=r['root_entries'],win=r['win_rate_pct']),t

def _positions(t,symbols):
    roots=t[t[:,18]==0];out=[]
    for r in roots:
        legs=t[t[:,17]==r[17]];out.append((symbols[int(r[0])],int(r[1]),float(legs[:,12].sum()),float(legs[:,9].sum()),float(r[19])))
    return pd.DataFrame(out,columns=['sym','ts','net','gross','mfe'])

def evaluate(mask=None):
    ctx=load();res={'ALL15':{}}
    for bps in (2,5):
        for per in PERIODS:
            row,t=_run(ctx,mask,SYMBOLS,6,bps,per);res['ALL15'][f'{per}|{bps}']=row
            if per=='full' and bps==2:
                p=_positions(t,SYMBOLS);fb=p[(p.net<0)&(p.mfe<.3)]
                res['false_breakouts']=dict(n=int(len(fb)),loss=float(fb.net.sum()));res['_positions']=p
    for name,syms in (('OLD5',OLD),('NEW10',NEW)):res[name]=_run(ctx,mask,syms,4,2,'full')[0]
    return res

@functools.lru_cache(1)
def baseline():
    p=OUT/'baseline.json'
    if p.exists():return json.loads(p.read_text())
    r=evaluate(None);pos=r.pop('_positions');top=pos.sort_values('net',ascending=False).head(25)
    r['top25']=[[s,int(t_),float(n)] for s,t_,n in zip(top.sym,top.ts,top.net)];OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r,indent=1));return r

def verdict(r):
    b=baseline();checks={}
    for bps in (2,5):
        x,y=r['ALL15'],b['ALL15']
        checks[f'positive_H1_H2_2026|{bps}']=all(x[f'{p}|{bps}']['net']>0 for p in ('H1','H2','Y2026'))
        checks[f'calmar_up_0.05|{bps}']=x[f'full|{bps}']['calmar']>=y[f'full|{bps}']['calmar']+.05
        checks[f'dd_not_worse|{bps}']=x[f'full|{bps}']['dd']<=y[f'full|{bps}']['dd']
        checks[f'calmar_both_halves|{bps}']=all(x[f'{p}|{bps}']['calmar']>=y[f'{p}|{bps}']['calmar'] for p in ('H1','H2'))
    checks['false_breakout_loss_cut_15pct']=r['false_breakouts']['loss']>=.85*b['false_breakouts']['loss']
    checks['both_subsets_calmar_not_worse']=r['OLD5']['calmar']>=b['OLD5']['calmar'] and r['NEW10']['calmar']>=b['NEW10']['calmar']
    return dict(checks=checks,passed=all(checks.values()))

def top25_retention(r):
    b=baseline();pos=r['_positions'];keys={(s,t_):n for s,t_,n in zip(pos.sym,pos.ts,pos.net)};base=sum(n for _,_,n in b['top25'])
    return dict(kept=int(sum((s,t_) in keys for s,t_,_ in b['top25'])),pnl_ratio=float(sum(keys.get((s,t_),0.) for s,t_,_ in b['top25'])/base))

def check_causal(mask_fn,variant,cutoffs=(0.35,0.6,0.85)):
    """Recompute the mask on histories truncated at several points; bars before each cut must not change."""
    ctx=load();full=mask_fn(ctx['frames'],ctx['ix'],ctx['side'],variant);nb=ctx['sig'].shape[1]
    for q in cutoffs:
        cut=int(nb*q);fr={};ixt={};sd={}
        for s in SYMBOLS:
            row=int(ctx['ix'][s][cut]);fr[s]=ctx['frames'][s].iloc[:row+1].copy();ixt[s]=np.minimum(ctx['ix'][s],row);sd[s]=ctx['side'][s].copy();sd[s][cut+1:]=0
        part=mask_fn(fr,ixt,sd,variant)
        for s in SYMBOLS:
            a,b_=np.asarray(full[s],bool)[:cut+1],np.asarray(part[s],bool)[:cut+1]
            if not np.array_equal(a,b_):return dict(causal=False,symbol=s,cut=q,first_diff_bar=int(np.argmax(a!=b_)))
    return dict(causal=True)

def run_method(method,variants,mask_fn,notes=''):
    """Evaluate every declared variant, gate it, and write output/fb/<method>.json. Returns the dict."""
    out=dict(method=method,notes=notes,baseline={k:baseline()[k] for k in ('ALL15','false_breakouts','OLD5','NEW10')},variants={})
    ctx=load()
    for name,variant in variants.items():
        cz=check_causal(mask_fn,variant);m=mask_fn(ctx['frames'],ctx['ix'],ctx['side'],variant)
        kept=sum(int(((ctx['side'][s]!=0)&np.asarray(m[s],bool)).sum()) for s in SYMBOLS);total=sum(int((ctx['side'][s]!=0).sum()) for s in SYMBOLS)
        r=evaluate(m);ret=top25_retention(r);r.pop('_positions');v=verdict(r)
        out['variants'][name]=dict(variant=variant,causal=cz,signal_bars_kept_pct=kept/total*100,results=r,top25=ret,verdict=v,passed=bool(v['passed'] and cz['causal']))
        f=r['ALL15']['full|2'];print(f"{method}/{name}: causal={cz['causal']} kept={kept/total*100:.1f}% | CAGR {f['cagr']:.2f} DD {f['dd']:.2f} Calmar {f['calmar']:.3f} | FB {r['false_breakouts']['n']} ${r['false_breakouts']['loss']:.0f} | top25 {ret['pnl_ratio']:.2f} | PASS={out['variants'][name]['passed']}",flush=True)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'{method}.json').write_text(json.dumps(out,indent=1,default=float));return out
