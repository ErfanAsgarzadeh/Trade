"""CHOP study method: time_stop. Exit at a 4h close if after N bars the position's MFE never reached 1R."""
import sys
from pathlib import Path
VARIANTS={'A':{'time_stop_bars':12,'time_stop_mfe':1.0},'B':{'time_stop_bars':18,'time_stop_mfe':1.0}}
def build_fn(ctx,variant):
    return {'kwargs':dict(variant)}
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from high_cagr import chop_harness as h
    h.run_idea('time_stop',VARIANTS,build_fn,notes='A: 12 bars (48h), B: 18 bars (72h); exit at 4h close if MFE<1R')
