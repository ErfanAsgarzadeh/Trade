"""Idea 5_giveback (pre-declared in predeclared.json): protect trades that reach +1R and then end as losses.
A: after root MFE >= 1R move stop to entry +0.1R (breakeven + costs)
B: close 1/3 of every leg at +1.5R, rest keeps trailing
C: after MFE >= 2R trail on the 4-bar channel (bars cols 6/7) instead of Donchian10
Only kernel switches; signals and trail bars are untouched (causal by construction)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import bench

VARIANTS={'A':dict(floor_on=True,floor_trigger=1.0,floor_lock=0.1),
          'B':dict(partial_frac=1/3,partial_r=1.5),
          'C':dict(tight_after_r=2.0,tight_cols=6)}

def build(ctx,variant):
    return {'kwargs':dict(variant)}

if __name__=='__main__':
    bench.run_idea('idea5_giveback',VARIANTS,build,
                   notes='Exit-management only (kernel_fixes kwargs); A floor 1R->+0.1R, B partial 1/3 @1.5R, C 4-bar channel trail after 2R.')
