"""Conditional ablation of the three loss-driver fixes against the committed winner baseline.
Same 5-symbol 1m data, costs, slippage, funding proxy and REJECT<1.2% as high_cagr.run_suite."""
from pathlib import Path
import sys,json,itertools,concurrent.futures
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.kernel_fixes import simulate
OUT=ROOT/'high_cagr/output'
BASE_ID='HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R{risk}__P4'
FIX1={'0':{},'1A':dict(same_side_cap=3,max_new_per_bar=2),'1B':dict(same_side_cap=2,max_new_per_bar=2)}
FIX2={'0':{},'2A':dict(stale_bars=4,stale_mfe=.40,stale_cols=4),'2B':dict(stale_bars=6,stale_mfe=.40,stale_cols=6)}
FIX4={'0':{},'4A':dict(floor_on=True),'4B':dict(floor_on=True,pyr_risk_mult=.35,pyr_safe=True)}
RISKS=[.0075,.01]

def channel_columns(case,frames):
    """3- and 4-bar closed-bar channel extremes, sampled exactly like the 10-bar line."""
    step=240;boundaries=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;cols=[]
    for symbol in case['symbols']:
        f=frames[symbol,'4h',case['preset']];ix=np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,boundaries,side='right')-1
        cols.append(np.column_stack([f.low.rolling(n).min().to_numpy()[ix] if side==0 else f.high.rolling(n).max().to_numpy()[ix] for n in (3,4) for side in (0,1)]))
    return np.stack(cols)

def build(risk,frames):
    case=[c for c in rs.grid() if c['id']==BASE_ID.format(risk=f'{risk:g}')][0]
    ss,bb,step=rs.inputs(case,frames);assert step==240
    return case,ss,np.concatenate([bb,channel_columns(case,frames)],axis=2),step

def run(case,ss,bb,step,prices,funding,policy,period):
    begin,end=rs.PERIODS[period]
    a,t,curve=simulate(prices,funding,ss,bb,rs.START,begin,end,case['risk'],case['max_open_positions'],step,True,**policy)
    row=rs.summarize(a,t,curve,begin,end,case['symbols'])
    row['calmar']=row['cagr_pct']/row['max_dd_pct'] if row['max_dd_pct']>0 else None
    row.update(cap_rejects=int(a[13]),stale_tightened_bar_events=int(a[14]),pyramid_safe_rejects=int(a[15]),floor_events=int(a[16]))
    return row,t,a

def positions(t):
    """Group unit rows into root positions: key (symbol, root entry ts) -> net pnl."""
    out={}
    for r in t:
        k=(int(r[0]),int(t[int(r[17]),1]));out[k]=out.get(k,0.)+r[12]
    return out

def validate(name,t,policy,risk,stats):
    """Ledger-level invariants proving each enabled rule binds as specified (asserts, never just reports)."""
    roots=t[t[:,18]==0];adds=t[t[:,18]==1];notes=dict(roots=len(roots),adds=len(adds))
    assert stats[6]<=4 and stats[7]<=.6+1e-8,(name,'slot/margin cap',stats[6],stats[7])
    if policy.get('max_new_per_bar'):
        _,counts=np.unique(roots[:,1],return_counts=True);assert counts.max()<=policy['max_new_per_bar'],name;notes['max_roots_per_bar']=int(counts.max())
    if policy.get('same_side_cap'):
        worst=0
        for ts in np.unique(roots[:,1]):
            live=roots[(roots[:,1]<=ts)&(roots[:,2]>ts)]
            for side in (1,-1):worst=max(worst,int((live[:,3]==side).sum()))
        assert worst<=policy['same_side_cap'],(name,worst);notes['max_same_side_open']=worst
    if policy.get('stale_bars'):notes['stale_tightened_roots']=int((roots[:,20]>0).sum())
    mult=policy.get('pyr_risk_mult',.5)
    if len(adds):
        ratio=adds[:,15]/adds[:,14]/risk;assert ratio.max()<=mult+1e-9,(name,'add risk',ratio.max());notes['max_add_risk_fraction']=float(ratio.max())
    if policy.get('floor_on'):
        hit=roots[(roots[:,19]>=2.)&(roots[:,13]==3)];sign=hit[:,3]
        raw_exit=hit[:,8]/(1-sign*.0002);floor=hit[:,4]+sign*.25*hit[:,7]
        assert (sign*(raw_exit-floor)>=-1e-6*hit[:,4]).all(),(name,'floor breached');notes['stopped_after_2R']=int(len(hit))
        notes['stopped_after_2R_net_loss']=int((hit[:,12]<0).sum());notes['reached_2R']=int((roots[:,19]>=2.).sum())
    if policy.get('pyr_safe') and len(adds):
        base=t[adds[:,17].astype(int)];sign=adds[:,3];x=adds[:,6]*(1-sign*.0002)
        combined=sum(sign*u[:,5]*(x-u[:,4])-.0006*u[:,5]*(u[:,4]+x) for u in (base,adds))
        assert (combined>=-1e-6).all(),(name,'unsafe add');notes['min_combined_stop_net_usd']=float(combined.min())
    return notes

def verdicts(rows,risk):
    base=rows['0_BASELINE'][risk]['full'];res={}
    for name,byrisk in rows.items():
        r=byrisk[risk];f,tr,oos=r['full'],r['train'],r['oos']
        cond1=tr['net_profit']>0 and oos['net_profit']>0
        calmar_win=f['calmar']>.95 and f['calmar']>base['calmar'] and f['max_dd_pct']<base['max_dd_pct'] and f['cagr_pct']>=30.
        growth_win=f['cagr_pct']>base['cagr_pct'] and f['net_profit']>base['net_profit'] and f['max_dd_pct']<=base['max_dd_pct']
        res[name]=dict(cond1_train_oos_positive=bool(cond1),calmar_route=bool(calmar_win),growth_route=bool(growth_win),
                       degrades_both=bool(f['cagr_pct']<base['cagr_pct'] and f['calmar']<base['calmar']),
                       verdict='BASELINE' if name=='0_BASELINE' else ('ACCEPTED' if cond1 and (calmar_win or growth_win) else 'REJECTED'))
    return res

def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in rs.SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in rs.SYMBOLS]);frames=rs.load_frames()
    policies={}
    for a,b,c in itertools.product(FIX1,FIX2,FIX4):
        name='0_BASELINE' if (a,b,c)==('0','0','0') else '+'.join(x for x in (a,b,c) if x!='0');policies[name]={**FIX1[a],**FIX2[b],**FIX4[c]}
    rows={n:{} for n in policies};notes={};base_positions={}
    for risk in RISKS:
        case,ss,bb,step=build(risk,frames)
        for name,policy in policies.items():
            rows[name][risk]={}
            for period in rs.PERIODS:
                row,t,stats=run(case,ss,bb,step,prices,funding,policy,period);rows[name][risk][period]=row
                if period=='full':
                    pos=positions(t)
                    if name=='0_BASELINE':base_positions[risk]=pos
                    notes.setdefault(name,{})[risk]=validate(name,t,policy,risk,stats)
                    top=sorted(base_positions[risk].items(),key=lambda kv:-kv[1])[:25]
                    rows[name][risk]['top25_baseline_winners']=dict(baseline_pnl=float(sum(v for _,v in top)),policy_pnl=float(sum(pos.get(k,0.) for k,_ in top)),still_open_same_entry=int(sum(1 for k,_ in top if k in pos)))
            print(name,risk,{p:(round(rows[name][risk][p]['cagr_pct'],2),round(rows[name][risk][p]['max_dd_pct'],2)) for p in rs.PERIODS},flush=True)
    result=dict(policies={n:{k:v for k,v in p.items()} for n,p in policies.items()},risks=RISKS,rows={n:{str(r):v for r,v in byrisk.items()} for n,byrisk in rows.items()},
                verdicts={str(r):verdicts(rows,r) for r in RISKS},validation={n:{str(r):v for r,v in x.items()} for n,x in notes.items()})
    (OUT/'ablation_fixes.json').write_text(json.dumps(result,indent=1,default=float));print('WROTE ablation_fixes.json')
if __name__=='__main__':main()
