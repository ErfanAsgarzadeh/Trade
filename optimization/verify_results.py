"""Replay baseline/winner and check indicator parity and intrabar sensitivity."""
import json
import numpy as np
import pandas as pd
import run_suite as suite
import lbank_bot as runtime
from kernel import simulate

def main():
    prices,funding,h,q=suite.build_features()
    matrix=json.loads((suite.ROOT/'output/matrix.json').read_text())
    rows={r['id']:r for r in matrix['matrix']}
    for i in np.linspace(198,len(q)-1,24,dtype=int):
        value=runtime.adx_wilder(q.iloc[i-198:i+1]).iloc[-1]
        assert abs(value-q.iloc[i].adx)<1e-10
    eb={'MTF':suite.bars_for_engine(h,60),'SINGLE':suite.bars_for_engine(q,240)}
    checks={}
    for label,case in [('baseline',rows['MTF__baseline__none__none']),('winner',matrix['profit_winner'])]:
        momentum=next(m for m in suite.MOMENTUM if m[0]==case['momentum'])
        si,sv=suite.signals_for(case['mode'],momentum[1],momentum[2],h,q)
        for reverse in [False,True]:
            a,t,f,c=simulate(prices,suite.bt.START,0,len(prices),si,sv,eb[case['mode']],eb['SINGLE'],funding,np.array(case['params']),60 if case['mode']=='MTF' else 240,path_reverse=reverse)
            summary=suite.summarize(a,t,f)
            if not reverse:
                for key in ['trades','net_profit','fees','funding_pnl','max_dd_pct']:
                    assert abs(summary[key]-case['full'][key])<1e-7,(label,key)
            assert np.allclose(t[:,7]-t[:,8]+t[:,9],t[:,10],atol=1e-8)
            assert abs(f[:,5].sum()-t[:,8].sum())<1e-8
            checks[label+('_reversed' if reverse else '')]=summary
            print(label,reverse,summary['net_profit'],flush=True)
    checks['adx_window_parity_samples']=24
    (suite.ROOT/'output/verification.json').write_text(json.dumps(checks,indent=2))

if __name__=='__main__':main()
