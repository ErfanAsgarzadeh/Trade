"""Idea partial_tp (CHOP study): take 50% off at +partial_r R, rest keeps trailing. Implemented in kernel via kwargs."""
import sys
from pathlib import Path

VARIANTS = {'A': {'partial_frac': 0.5, 'partial_r': 1.0}, 'B': {'partial_frac': 0.5, 'partial_r': 1.5}}


def build_fn(ctx, variant):
    return {'kwargs': dict(variant)}


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from high_cagr import chop_harness as h
    h.run_idea('partial_tp', VARIANTS, build_fn, notes='kernel partial_frac=0.5 at partial_r R; A 1.0R, B 1.5R; remainder keeps trailing.')
