"""Entry-trigger study for the deployed winner (FIVE/standard/4h/Donchian10 trail/4B, P4).

Only the root entry trigger changes. Data, costs, sizing, REJECT<1.2%, ATR2 stop,
trail, pyramid and profit floor are identical to high_cagr.ablation_fixes 4B.
Every variant keeps the original condition (close beyond prior 10-bar Donchian and
closed 4h price outside Kumo) and adds one causal filter computed on closed bars.

Protocol (fixed before running): variants are ranked on Train (2021-10..2024-12)
Calmar only; 2025-2026 is reported as validation. A family is ROBUST only if every
parameter in its predeclared neighbourhood beats the baseline Train Calmar.
"""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs, ablation_fixes as af
from high_cagr.kernel_fixes import simulate
OUT=ROOT/'high_cagr/output';POLICY=af.FIX4['4B'];RISKS=[.0075,.01]

def wilder(x,n):return x.ewm(alpha=1/n,adjust=False).mean()

def adx(f,n=14):
    up=f.high.diff();down=-f.low.diff()
    plus=np.where((up>down)&(up>0),up,0.);minus=np.where((down>up)&(down>0),down,0.)
    tr=pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1)
    atr=wilder(tr,n);pdi=100*wilder(pd.Series(plus,index=f.index),n)/atr;mdi=100*wilder(pd.Series(minus,index=f.index),n)/atr
    return wilder(100*(pdi-mdi).abs()/(pdi+mdi),n)

def features(f):
    """Closed-bar columns; every value at row r uses rows <= r only."""
    f=f.copy();rng=(f.high-f.low).replace(0,np.nan)
    f['base_long']=f.close>f.donchian_high_10;f['base_short']=f.close<f.donchian_low_10
    f['clv']=(f.close-f.low)/rng;f['body']=(f.close-f.open)/rng
    f['vol_ratio']=f.volume/f.volume.rolling(20).mean().shift(1)
    width=(f.high.rolling(20).max()-f.low.rolling(20).min())/f.close
    f['squeeze_pct']=width.shift(1).rolling(120).rank(pct=True)
    f['ext_atr']=(f.close-f.kijun)/f.atr;f['adx']=adx(f)
    return f

def side_for(variant,param,e,h):
    """+1/-1/0 per entry bar; 'A+B' combines filters (param applies to the parametrised one)."""
    if '+' in variant:
        parts=[side_for(v,param,e,h) for v in variant.split('+')]
        return np.where(np.all([x==1 for x in parts],axis=0),1,0)-np.where(np.all([x==-1 for x in parts],axis=0),1,0)
    return _side(variant,param,e,h)

def _side(variant,param,e,h):
    """+1/-1/0 per entry bar. e=entry-tf rows, h=4h rows, both already sampled at boundaries."""
    kumo_long=h.close.to_numpy()>h.kumo_top.to_numpy();kumo_short=h.close.to_numpy()<h.kumo_bottom.to_numpy()
    L=e.base_long.to_numpy(bool)&kumo_long;S=e.base_short.to_numpy(bool)&kumo_short
    c=e.close.to_numpy();atr=e.atr.to_numpy()
    if variant=='FRESH':
        bl=e.base_long_prev.to_numpy(bool);bs=e.base_short_prev.to_numpy(bool);L&=~bl;S&=~bs
    elif variant=='ATRBUF':L&=c>e.donchian_high_10.to_numpy()+param*atr;S&=c<e.donchian_low_10.to_numpy()-param*atr
    elif variant=='CLOSELOC':L&=e.clv.to_numpy()>=param;S&=e.clv.to_numpy()<=1-param
    elif variant=='BODY':L&=e.body.to_numpy()>=param;S&=e.body.to_numpy()<=-param
    elif variant=='VOLUME':v=e.vol_ratio.to_numpy()>=param;L&=v;S&=v
    elif variant=='SQUEEZE':q=e.squeeze_pct.to_numpy()<=param;L&=q;S&=q
    elif variant=='EXTENSION':x=e.ext_atr.to_numpy();L&=x<=param;S&=x>=-param
    elif variant=='ADX':a=e.adx.to_numpy()>=param;L&=a;S&=a
    elif variant=='TK':L&=(e.tenkan>e.kijun).to_numpy()&(c>e.kijun.to_numpy());S&=(e.tenkan<e.kijun).to_numpy()&(c<e.kijun.to_numpy())
    elif variant=='KUMO_FUTURE':L&=(h.senkou_a_future>h.senkou_b_future).to_numpy();S&=(h.senkou_a_future<h.senkou_b_future).to_numpy()
    elif variant=='EMA':L&=(e.ema20>e.ema50).to_numpy();S&=(e.ema20<e.ema50).to_numpy()
    elif variant!='BASE':raise ValueError(variant)
    return L.astype(np.int64)-S.astype(np.int64)

def build_signals(case,frames,variant,param):
    """Same sampling, stop and ranking as run_suite.inputs; only the side mask differs."""
    step=240;boundaries=rs.START+np.arange((rs.END-rs.START)//(step*60000)+1)*step*60000;ss=[]
    for symbol in case['symbols']:
        f=features(frames[symbol,'4h',case['preset']])
        if 'FRESH' in variant:
            # A fresh breakout: no base breakout on any of the previous `param` closed bars.
            f['base_long_prev']=f.base_long.astype(float).rolling(int(param)).max().shift(1).fillna(0)>0
            f['base_short_prev']=f.base_short.astype(float).rolling(int(param)).max().shift(1).fillna(0)>0
        ix=np.searchsorted(f.timestamp.to_numpy(np.int64)+step*60000,boundaries,side='right')-1;e=f.iloc[ix]
        side=side_for(variant,param,e,e);price=e.close.to_numpy();high=e.donchian_high_10.to_numpy();low=e.donchian_low_10.to_numpy()
        top=e.kumo_top.to_numpy();bottom=e.kumo_bottom.to_numpy();stop=price-side*2*e.atr.to_numpy()
        score=np.where(side==1,(price-np.maximum(high,top))/price,(np.minimum(low,bottom)-price)/price);score=np.where(side!=0,score,-np.inf)
        ss.append(np.column_stack([side,price,stop,score]))
    return np.stack(ss)

VARIANTS=[('BASE',0)]+[('FRESH',k) for k in (1,2,3)]+[('ATRBUF',k) for k in (.1,.25,.5)]+[('CLOSELOC',q) for q in (.5,.6,.7)]+\
 [('BODY',q) for q in (.3,.5)]+[('VOLUME',m) for m in (1.,1.25,1.5)]+[('SQUEEZE',q) for q in (.3,.5,.7)]+\
 [('EXTENSION',x) for x in (2.,2.5,3.)]+[('ADX',t) for t in (15,20,25)]+[('TK',0),('KUMO_FUTURE',0),('EMA',0)]

# Stage 2, added AFTER stage 1 was seen: neighbourhood of the two stage-1 leaders and their
# combination. Reported separately; this is robustness checking, not untouched validation.
STAGE2=[('ATRBUF',k) for k in (.3,.4,.6,.75,1.)]+[('KUMO_FUTURE+ATRBUF',k) for k in (.25,.4,.5,.6,.75)]+\
 [('KUMO_FUTURE+VOLUME',m) for m in (1.,1.25)]

def name(v,p):return v if v in ('BASE','TK','KUMO_FUTURE','EMA') else f'{v}_{p:g}'

def yearly(curve):
    c=curve[np.isfinite(curve[:,1])];s=pd.Series(c[:,1],index=pd.to_datetime(c[:,0],unit='ms'))
    y=s.groupby(s.index.year).last();prev=y.shift(1).fillna(10000.)
    return {str(k):float(v) for k,v in ((y/prev-1)*100).items()}

def daily_returns(curve):
    c=curve[np.isfinite(curve[:,1])];s=pd.Series(c[:,1],index=pd.to_datetime(c[:,0],unit='ms')).resample('1D').last().dropna()
    return s.pct_change().dropna().to_numpy()

def bootstrap(base,var,n=3000,block=20,seed=7):
    """Paired stationary-block bootstrap on daily returns: P(variant beats baseline)."""
    rng=np.random.default_rng(seed);m=min(len(base),len(var));base,var=base[:m],var[:m];stats=np.zeros((n,2))
    for k in range(n):
        idx=[];
        while len(idx)<m:
            s=rng.integers(0,m);idx.extend(range(s,min(m,s+block)))
        idx=np.array(idx[:m]);out=[]
        for r in (base[idx],var[idx]):
            eq=np.cumprod(1+r);dd=(1-eq/np.maximum.accumulate(eq)).max();cagr=eq[-1]**(365/m)-1;out.append((cagr,cagr/dd if dd>0 else np.inf))
        stats[k]=[out[1][0]-out[0][0],out[1][1]-out[0][1]]
    return dict(p_cagr_better=float((stats[:,0]>0).mean()),p_calmar_better=float((stats[:,1]>0).mean()))

def main():
    prices=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'prices.npy') for s in rs.SYMBOLS]);funding=np.stack([np.load(ROOT/'high_cagr/prepared'/s/'funding.npy') for s in rs.SYMBOLS]);frames=rs.load_frames()
    rows={};curves={}
    for risk in RISKS:
        case,_,bb,step=af.build(risk,frames)
        for stage,(v,p) in [(1,x) for x in VARIANTS]+[(2,x) for x in STAGE2]:
            ss=build_signals(case,frames,v,p);key=name(v,p);rows.setdefault(key,dict(variant=v,param=p,stage=stage))
            for period,(begin,end) in rs.PERIODS.items():
                a,t,curve=simulate(prices,funding,ss,bb,rs.START,begin,end,risk,case['max_open_positions'],step,True,**POLICY)
                r=rs.summarize(a,t,curve,begin,end,case['symbols']);r['calmar']=r['cagr_pct']/r['max_dd_pct']
                roots=t[t[:,18]==0];r['avg_root_r']=float(np.mean(roots[:,12]/roots[:,15])) if len(roots) else 0.
                rows[key].setdefault(str(risk),{})[period]={k:r[k] for k in ('cagr_pct','max_dd_pct','calmar','profit_factor','net_profit','root_entries','win_rate_pct','fees','avg_root_r')}
                if period=='full':
                    rows[key][str(risk)]['yearly_pct']=yearly(curve)
                    if risk==.0075:curves[key]=daily_returns(curve)
            f=rows[key][str(risk)]
            print(f'{key:24s} R{risk:g} '+' '.join(f"{q}: CAGR {f[q]['cagr_pct']:6.2f} DD {f[q]['max_dd_pct']:5.2f} Cal {f[q]['calmar']:.2f} PF {f[q]['profit_factor']:.3f} n {f[q]['root_entries']}" for q in rs.PERIODS),flush=True)
    base=rows['BASE']['0.0075']['train']['calmar']
    families={}
    for key,r in rows.items():
        if r['stage']==1:families.setdefault(r['variant'],[]).append(r['0.0075']['train']['calmar']>base)
    for key,r in rows.items():
        r['robust_family']=r['variant']!='BASE' and all(families.get(r['variant'],[False]))
        if key!='BASE':r['bootstrap_full_r0075']=bootstrap(curves['BASE'],curves[key])
    # Leave-one-symbol-out on Full at the deployed risk for the baseline and leaders.
    case,_,bb,step=af.build(.0075,frames);begin,end=rs.PERIODS['full']
    for key in ('BASE','ATRBUF_0.5','KUMO_FUTURE','KUMO_FUTURE+VOLUME_1.25'):
        ss=build_signals(case,frames,rows[key]['variant'],rows[key]['param']);rows[key]['leave_one_out_full_r0075']={}
        for drop in range(len(rs.SYMBOLS)):
            keep=[i for i in range(len(rs.SYMBOLS)) if i!=drop]
            a,t,curve=simulate(prices[keep],funding[keep],ss[keep],bb[keep],rs.START,begin,end,.0075,case['max_open_positions'],step,True,**POLICY)
            r=rs.summarize(a,t,curve,begin,end,[rs.SYMBOLS[i] for i in keep]);rows[key]['leave_one_out_full_r0075']['-'+rs.SYMBOLS[drop]]=dict(cagr_pct=r['cagr_pct'],max_dd_pct=r['max_dd_pct'])
    ranked=sorted((k for k in rows if k!='BASE' and rows[k]['stage']==1),key=lambda k:-rows[k]['0.0075']['train']['calmar'])
    result=dict(policy=POLICY,risks=RISKS,protocol=__doc__,ranked_by_train_calmar=ranked,rows=rows)
    (OUT/'trigger_study.json').write_text(json.dumps(result,indent=1,default=float));print('WROTE trigger_study.json')
if __name__=='__main__':main()
