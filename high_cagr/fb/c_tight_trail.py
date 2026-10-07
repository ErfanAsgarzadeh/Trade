"""CHOP study method: tight_trail. Once MFE >= N R, trail on a shorter channel (4-bar / 3-bar opposite extreme)."""
import sys
from pathlib import Path
VARIANTS={'A':{'tight_after_r':1.0,'tight_cols':6},'B':{'tight_after_r':1.5,'tight_cols':4}}
def build_fn(ctx,variant):
    return {'kwargs':dict(variant)}
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from high_cagr import chop_harness as h
    h.run_idea('tight_trail',VARIANTS,build_fn,notes='A: after 1R trail on 4-bar extreme (cols 6/7), B: after 1.5R trail on 3-bar extreme (cols 4/5)')
