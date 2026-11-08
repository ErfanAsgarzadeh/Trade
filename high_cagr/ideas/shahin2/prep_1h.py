"""1h features (standard Ichimoku preset) for the 30 coins Shahin never traded, built exactly like high_cagr/prepare.py builds
them for the five Shahin coins (same aggregation, indicators, Donchian 15/40 columns), from the verified 1m archives of
high_cagr/stage2_data.py. Written to high_cagr/prepared_stage2/<SYM>/1h_standard.npz."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import stage2_data as S
from high_cagr.ideas.shahin2 import lab as LB
def build(sym):
    dst=S.PREP/sym/'1h_standard.npz'
    if dst.exists():return 'cached'
    frames=[]
    for rel in [r for r in S.files(sym) if '-1m-' in r]:
        d=S.read_zip(S.CACHE/rel,header=None,usecols=range(6),names=['timestamp','open','high','low','close','volume'],low_memory=False)
        d=d[pd.to_numeric(d.timestamp,errors='coerce').notna()].astype(float)
        if d.timestamp.max()>1e14:d.timestamp/=1000
        frames.append(d)
    d=pd.concat(frames,ignore_index=True).drop_duplicates('timestamp').sort_values('timestamp');d=d[d.timestamp<S.bt.END].reset_index(drop=True)
    raw=S.bt.aggregate(d,'1h');c=json.loads((ROOT/'optimization/baseline/config.json').read_text());c['ichimoku_params'].update(zip(['tenkan','kijun','senkou_b','displacement'],(9,26,52,26)))
    f=S.shared.add_features(S.bt.prepare_indicators(raw,c))
    for n in (15,40):f[f'donchian_high_{n}']=f.high.rolling(n).max().shift(1);f[f'donchian_low_{n}']=f.low.rolling(n).min().shift(1)
    np.savez_compressed(dst,data=f.to_numpy(),columns=json.dumps(list(f.columns)));return len(f)
if __name__=='__main__':
    for s in LB.OTHER30:print(s,build(s),flush=True)
