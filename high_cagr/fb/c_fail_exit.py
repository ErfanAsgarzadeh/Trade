"""CHOP study method: fail_exit. Exit at a 4h close when the breakout has failed (closed bar back inside the level stored at entry)."""
import sys
from pathlib import Path
VARIANTS={'A':{'fail_exit_mode':1},'B':{'fail_exit_mode':2}}
def build_fn(ctx,variant):
    return {'kwargs':dict(variant)}
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from high_cagr import chop_harness as h
    h.run_idea('fail_exit',VARIANTS,build_fn,notes='A: close back inside breakout level max(Donchian10,Kumo top) at entry; B: close back inside Kumo edge at entry')
