"""Idea short_risk: scale risk of new short root entries via kernel kwarg short_risk_mult."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

VARIANTS = {'A': {'short_risk_mult': 0.5}, 'B': {'short_risk_mult': 0.75}}


def build_fn(ctx, variant):
    return {'kwargs': dict(variant)}


if __name__ == '__main__':
    from high_cagr import imp_harness as h
    h.run_idea('short_risk', VARIANTS, build_fn, notes='short_risk_mult 0.5 (A) / 0.75 (B) on new short root entries.')
