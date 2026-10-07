"""Idea diversification: more simultaneous positions, less risk each (A: 8 slots @0.6%, B: 10 slots @0.5%)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

VARIANTS = {'A': {'slots': 8, 'risk': 0.006}, 'B': {'slots': 10, 'risk': 0.005}}


def build_fn(ctx, variant):
    return {'slots': variant['slots'], 'risk': variant['risk'], 'subset_slots': 5}


if __name__ == '__main__':
    from high_cagr import imp_harness as h
    h.run_idea('diversification', VARIANTS, build_fn,
               notes='A: 8 slots risk 0.6%; B: 10 slots risk 0.5%; subset runs use 5 slots (baseline subsets used 4 slots at 0.75%, so subset comparison mixes slot count and risk).')
