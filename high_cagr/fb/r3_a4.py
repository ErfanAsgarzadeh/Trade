"""A4 adaptive risk (trade-outcome based sizing / cooldown), custom kernel r3k_a4.
Declared before running:
 streak2: per-symbol, after 2 consecutive losing root trades on the symbol next root entry at 0.5x risk; win resets.
 streak1: after 1 losing root on the symbol, next root at 0.5x (aggressive neighbour of streak2).
 book8:   portfolio: if last 8 closed root trades (whole book) had <=2 wins (25%), new roots at 0.5x risk.
 cool6:   no same-side re-entry on a symbol within 6 bars (24h) after a losing root close on it.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.fb.r3k_a4 import simulate
VARIANTS={'streak2':{'streak_n':2,'streak_mult':.5},'streak1':{'streak_n':1,'streak_mult':.5},
          'book8':{'wr_k':8,'wr_max_wins':2,'wr_mult':.5},'cool6':{'cool_bars':6}}
def build_fn(U,variant):
    return {'simulate':simulate,'kwargs':dict(variant)}
if __name__=='__main__':
    from high_cagr import r3_harness as h
    h.run_method('r3_a4_adaptive','chop',VARIANTS,build_fn,notes='trade-outcome based adaptive risk, custom kernel r3k_a4')
