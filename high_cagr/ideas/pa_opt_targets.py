"""pa_opt_targets - Targets and partial exits for the PA sleeve (4h KEYREV, stop entry, 2R target, 30-bar time stop).

HYPOTHESIS: 2R fixed target may not be the optimal exit. KEYREV entries after a reversal might run further in good trends
(then a larger target / partial + runner captures more) or may mean-revert quickly (then a nearer target 1.5R is better).
MECHANISM: Expectancy = P(hit target)*target - P(stop)*1R - costs. Changing the target trades hit rate for payoff size;
a partial at 1R banks part of the move (higher win rate, smoother), the runner keeps convexity. Costs/slippage are fixed per
trade, so a larger target amortises them better only if the hit rate does not fall proportionally.
No signal filters are used; the only change is the exit, so causality is by construction (engine uses bars <= current).

VARIANTS (fixed before any result is seen; all other args = baseline defaults, hold=30 unless stated):
  T15        target_r=1.5
  T25        target_r=2.5
  T3         target_r=3.0
  NOTGT      target_r=0 (no target), hold=30 (time stop only)
  NOTGT60    target_r=0, hold=60
  P50_T3     partial_frac=0.5 at partial_r=1.0, target_r=3.0
  P50_T3_BE  partial_frac=0.5 at 1R, target_r=3.0, be_r=1.0 (stop to breakeven after MFE 1R)
  P33_TRAIL  partial_frac=1/3 at 1R, target_r=0, trail_after_r=1.5, trail_atr=3.0, hold=60
GATES: P1-P5 from pabench.
"""
from high_cagr.ideas import pabench as PB

VARIANTS={
 'T15':dict(target_r=1.5),
 'T25':dict(target_r=2.5),
 'T3':dict(target_r=3.0),
 'NOTGT':dict(target_r=0,hold=30),
 'NOTGT60':dict(target_r=0,hold=60),
 'P50_T3':dict(partial_frac=.5,partial_r=1.0,target_r=3.0),
 'P50_T3_BE':dict(partial_frac=.5,partial_r=1.0,target_r=3.0,be_r=1.0),
 'P33_TRAIL':dict(partial_frac=1/3,partial_r=1.0,target_r=0,trail_after_r=1.5,trail_atr=3.0,hold=60),
}
def fn(d,v):return PB.run(d,**v)
def main():PB.run_idea('targets',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
