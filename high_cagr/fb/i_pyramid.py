"""Idea: pyramid add policy. A = no pyramid; B = add-on risk 0.5x (safety check kept)."""
import sys
from pathlib import Path
VARIANTS={'A':{'pyramid':False},'B':{'pyr_risk_mult':0.5}}
def build_fn(ctx,variant):
    return {'kwargs':dict(variant)}
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from high_cagr import imp_harness as h
    h.run_idea('pyramid',VARIANTS,build_fn,notes='A: pyramid off; B: pyr_risk_mult 0.5 with pyr_safe kept')
