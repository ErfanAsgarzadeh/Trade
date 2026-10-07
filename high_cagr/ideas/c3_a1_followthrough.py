"""Agent 1 - C3 entry quality vs NO_FOLLOW_THROUGH losers (price never reached +0.5R; 456 trades, 55% of loss R).

Variants declared BEFORE any run (fixed round parameters, no tuning afterwards):

A  'dip30'  - pullback-depth floor. Keep a PULL long only if min(RSI14) over the 12 bars up to the signal bar is >= 30
   (short: max(RSI14) <= 70). Mechanism: a pullback inside a healthy trend is a shallow momentum reset (RSI 30-40);
   an RSI excursion into oversold (<30) against the EMA50/200 trend means sellers took control for a while - it is a
   regime break / distribution phase, not a dip, and the re-cross of 40 is often just a dead-cat bounce that never
   follows through. Same 12-bar window the diagnosis used.

B  'dip30_slope' - A plus "trend still alive": EMA50 must be moving in the trade direction, e50[t] > e50[t-20]
   (short: <). Mechanism: very old EMA50/200 crosses (>400 bars) are weak because the trend has often stalled while
   EMA50 is still above EMA200 by inertia; a flat/rolling EMA50 identifies a stalled trend directly instead of using
   an age cutoff (age is a proxy, slope is the cause; slope also does not penalise long, still-running trends).

C  'confirm3' - confirmation trigger instead of a filter. After a PULL signal on bar t (weekday, trend still valid),
   enter only when a later close within the next 3 bars exceeds the signal bar's high (short: closes below its low);
   enter at the open after the confirming bar (engine semantics: signal at k -> entry at k+1, stop 2 ATR[k]).
   Mechanism: NO_FOLLOW_THROUGH trades by definition never move in our favour; demanding the market show
   continuation past the trigger bar removes the ones that stall immediately, at the cost of a slightly worse entry.
   Weekend mask applied to the confirming bar (the entry decision bar).

ROUND 2 (declared after seeing round 1: A train 1.59/valid 0.88, B worse everywhere, C train 1.88/valid 1.57/OTHER20 0.31,
fails G2+G4 mainly by cutting ~32% of trades). One extra variant, no other changes:
D  'confirm3_close' - as C but the confirmation level is the signal bar's CLOSE instead of its high/low (any further
   progress within 3 bars). Mechanism: same "show continuation" idea, but the bar-high requirement pays away part of
   the move and drops slow-starting winners; the close threshold only rejects trades that go nowhere.

All features use only data <= decision bar (EMA/RSI recursions and trailing windows).
"""
from pathlib import Path
import sys
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from high_cagr.ideas import c3bench as B, mtf_search as M


def _filters(d, variant):
    le, se, _, _ = d['sig']['PULL']
    le = le.copy(); se = se.copy(); r = pd.Series(d['r14'])
    if variant.get('dip'):
        lo = r.rolling(12, min_periods=1).min().to_numpy(); hi = r.rolling(12, min_periods=1).max().to_numpy()
        le &= lo >= variant['dip']; se &= hi <= 100 - variant['dip']
    if variant.get('slope'):
        e50 = d['e50']; k = variant['slope']; prev = np.concatenate([np.full(k, np.nan), e50[:-k]])
        le &= e50 > prev; se &= e50 < prev
    return le, se


def _confirm(d, le, se, w, lvl='hl'):
    h, l, c, e50, e200, wk = d['h'], d['l'], d['c'], d['e50'], d['e200'], d['wk']; n = d['n']
    cl = np.zeros(n, bool); cs = np.zeros(n, bool)
    for t in np.where(le & wk)[0]:
        for k in range(t + 1, min(t + 1 + w, n)):
            if e50[k] <= e200[k]: break
            if c[k] > (c[t] if lvl == 'close' else h[t]): cl[k] = True; break
    for t in np.where(se & wk)[0]:
        for k in range(t + 1, min(t + 1 + w, n)):
            if e50[k] >= e200[k]: break
            if c[k] < (c[t] if lvl == 'close' else l[t]): cs[k] = True; break
    return cl, cs


def trades_fn(d, variant):
    le, se = _filters(d, variant)
    if variant.get('confirm'): le, se = _confirm(d, le, se, variant['confirm'], variant.get('level', 'hl'))
    z = np.zeros(d['n'], bool)
    return M.engine(d['o'], d['h'], d['l'], d['c'], d['atr'], le, se, z, z, d['wk'], d['wk'], 6, .0006, .0002, d['fb'], 300)


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'round2':
    B.run('a1_followthrough_r2', {'D': dict(confirm=3, level='close')}, trades_fn,
          notes='Agent1 round 2: confirmation close beyond signal-bar close within 3 bars.')
elif __name__ == '__main__':
    B.run('a1_followthrough', {'A': dict(dip=30), 'B': dict(dip=30, slope=20), 'C': dict(confirm=3)}, trades_fn,
          notes='Agent1: NO_FOLLOW_THROUGH entry quality. A RSI dip floor 30; B +EMA50 20-bar slope; C close beyond signal-bar extreme within 3 bars.')
