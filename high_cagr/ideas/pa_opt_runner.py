"""pa_opt_runner: runner / trailing management of good key-reversal trends (PA sleeve).

HYPOTHESIS. The fixed 2R target caps the winners of the best reversals (strong trends continue beyond 2R) and the 30-bar
time stop cuts slow trends. Replacing the cap by a chandelier trail (4h closes), possibly after a 2R partial, and/or moving
the stop to breakeven once 1R is reached, should lift average winner size and lower the loss on reversals that fail after
working, without giving back the edge.
MECHANISM. Entry is unchanged (same signals, same stops, same risk), only the exit is changed with engine parameters of
pabench.run (no own engine; a structure trail is NOT tested - not enough variant budget). Trail = best 4h close - k*ATR,
armed after best close >= trail_after_r R. be_r moves the stop to entry+costs when the intrabar MFE reaches be_r R.
No train diagnostic was run; parameters are round numbers fixed before any result.
VARIANTS (fixed, all keep entries identical):
 A be1_tp2          target 2, hold 30, be_r=1
 B hold60_tp2       target 2, hold 60
 C trail3_h60       no target, trail_after_r=1, trail_atr=3, hold 60
 D trail4_h90       no target, trail_after_r=2, trail_atr=4, hold 90
 E hybrid_p2_trail  partial 50% at 2R, runner no target, trail_after_r=1, trail_atr=3, hold 60
 F hybrid_be1       as E plus be_r=1
 G tp3_be1_h60      target 3, be_r=1, hold 60
 H trail2_h60       no target, trail_after_r=1, trail_atr=2, hold 60
"""
import sys;from pathlib import Path;sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import pabench as PB

VARIANTS={'A_be1_tp2':dict(target_r=2.,hold=30,be_r=1.),
 'B_hold60_tp2':dict(target_r=2.,hold=60),
 'C_trail3_h60':dict(target_r=0.,hold=60,trail_after_r=1.,trail_atr=3.),
 'D_trail4_h90':dict(target_r=0.,hold=90,trail_after_r=2.,trail_atr=4.),
 'E_hybrid_p2_trail':dict(target_r=0.,hold=60,partial_frac=.5,partial_r=2.,trail_after_r=1.,trail_atr=3.),
 'F_hybrid_be1':dict(target_r=0.,hold=60,partial_frac=.5,partial_r=2.,trail_after_r=1.,trail_atr=3.,be_r=1.),
 'G_tp3_be1_h60':dict(target_r=3.,hold=60,be_r=1.),
 'H_trail2_h60':dict(target_r=0.,hold=60,trail_after_r=1.,trail_atr=2.)}

def fn(d,v):return PB.run(d,**v)

def main():PB.run_idea('runner',VARIANTS,fn,notes=__doc__)
if __name__=='__main__':main()
