"""Idea profit_floor: earlier profit floor (floor_trigger / floor_lock kernel kwargs)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

VARIANTS = {'A': {'floor_trigger': 1.5, 'floor_lock': 0.25}, 'B': {'floor_trigger': 1.0, 'floor_lock': 0.0}}


def build_fn(ctx, variant):
    return {'kwargs': dict(variant)}


if __name__ == '__main__':
    from high_cagr import imp_harness as h
    h.run_idea('profit_floor', VARIANTS, build_fn, notes='A: trigger 1.5R lock +0.25R; B: trigger 1.0R lock 0R (breakeven). Baseline is trigger 2.0R lock +0.25R.')
