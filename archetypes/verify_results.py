"""Independent baseline replay, indicator/signal parity and winner sensitivity."""
import json,sys,importlib.util
import numpy as np
import pandas as pd
import run_suite as suite
from kernel import simulate
import lbank_bot as runtime

def main():
    prices,funding,frames=suite.load_features();report=json.loads((suite.ROOT/'output/matrix.json').read_text())
    path=suite.ROOT.parent/'optimization/run_suite.py'
    spec=importlib.util.spec_from_file_location('old_suite',path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    _,_,h,q=old.build_features();si,sv=old.signals_for('MTF',False,0,h,q)
    sv=np.column_stack([sv,np.ones(len(sv))]);eb=old.bars_for_engine(h,60);hb=old.bars_for_engine(q,240)
    eb=np.column_stack([eb,eb[:,0]]);hb=np.column_stack([hb,hb[:,0]])
    cfg=np.array([1.5,.5,0,.2,60,0,0,0,0,0])
    a,t,f,curve=simulate(prices,suite.START,0,len(prices),si,sv,eb,hb,funding,cfg,60)
    baseline=suite.summarize(a,t,f)
    original=json.loads((suite.ROOT.parent/'optimization/output/matrix.json').read_text())
    previous=next(x for x in original['matrix'] if x['id']=='MTF__baseline__none__none')['full']
    for key in ['trades','net_profit','fees','funding_pnl','max_dd_pct']:assert abs(baseline[key]-previous[key])<1e-7,(key,baseline[key],previous[key])
    checks=dict(baseline=baseline,parity_windows=0,parity_cases=0)
    # All 112 definitions checked on regularly spaced windows plus actual signals.
    for case in suite.grid():
        c=runtime.validate_config(suite.config_for(case));low=frames[case['mode'],case['setting']];high=frames['SINGLE',case['setting']]
        minutes=60 if case['mode']=='MTF' else 240
        si,sv,valid=suite.signals(case,c,frames)
        longs,shorts=__import__('strategy_archetypes').entry_masks(low,c)
        indices=list(np.linspace(900 if minutes==60 else 230,len(low)-2,6,dtype=int))
        times=low.timestamp.to_numpy(dtype=np.int64)+minutes*60000
        if len(si):indices+=np.searchsorted(times,suite.START+si[np.linspace(0,len(si)-1,min(4,len(si)),dtype=int)]*60000).tolist()
        for i in indices:
            now=int(low.iloc[i].timestamp/1000+minutes*60+3)
            sample=low.iloc[i-198:i+2][['timestamp','open','high','low','close','volume']].to_numpy().tolist()
            frame=runtime.indicators(sample,c,'1h' if minutes==60 else '4h',now)
            hi=np.searchsorted(high.timestamp.to_numpy(dtype=np.int64)+14400000,now*1000,side='right')-1
            hsample=high.iloc[hi-198:hi+2][['timestamp','open','high','low','close','volume']].to_numpy().tolist()
            ht=runtime.indicators(hsample,c,'4h',now)
            for col in ['tenkan','kijun','kumo_top','kumo_bottom','rsi','atr','ema20','ema50','donchian_high_20','opposite_low_10','opposite_high_10']:
                assert np.isclose(frame.iloc[-1][col],low.iloc[i][col],atol=1e-8), (case['id'],col,i)
            expected=__import__('strategy_archetypes').regime_masks(high,c)
            side='long' if expected[0].iloc[hi] else 'short' if expected[1].iloc[hi] else None
            assert runtime.regime(ht,c)==side
            for direction in ['long','short']:
                source=ht if case['family']=='DONCHIAN' else frame
                expected_masks=__import__('strategy_archetypes').entry_masks(high if case['family']=='DONCHIAN' else low,c)
                ix=hi if case['family']=='DONCHIAN' else i
                assert runtime.entry_signal(frame,direction,c,ht)==bool(expected_masks[0 if direction=='long' else 1].iloc[ix])
            checks['parity_windows']+=1
        checks['parity_cases']+=1
    winner=report['winner']
    if winner:
        c=suite.config_for(winner);si,sv,valid=suite.signals(winner,c,frames);minutes=60 if winner['mode']=='MTF' else 240
        eb=suite.bars(frames[winner['mode'],winner['setting']],minutes,winner['trail']);hb=suite.bars(frames['SINGLE',winner['setting']],240,winner['trail'])
        for reverse in [False,True]:
            a,t,f,curve=simulate(prices,suite.START,0,len(prices),si,sv,eb,hb,funding,suite.engine_cfg(c),minutes,path_reverse=reverse,validity=valid)
            summary=suite.summarize(a,t,f)
            if not reverse:
                for k in ['trades','net_profit','fees','funding_pnl','max_dd_pct']:assert abs(summary[k]-winner['full'][k])<1e-7
            checks['winner_reversed' if reverse else 'winner']=summary
        # Stress the single missing-archive funding event by doubling its cost.
        # A proxy multiplier is passed explicitly to the same kernel below.
        a,t,f,curve=simulate(prices,suite.START,0,len(prices),si,sv,eb,hb,funding,suite.engine_cfg(c),minutes,validity=valid,funding_proxy=.0002)
        checks['winner_double_missing_funding_cost']=suite.summarize(a,t,f)
    (suite.ROOT/'output/verification.json').write_text(json.dumps(checks,indent=2))
    print('VERIFIED',checks,flush=True)

if __name__=='__main__':main()
