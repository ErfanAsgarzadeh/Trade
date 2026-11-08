# Shahin review 2 — pre-declared (written before any result of this study was seen)

Goal (owner): more profit AND lower drawdown for Shahin. Baseline = Shahin as shipped after the win-rate study:
2A+5A (Donchian10 + Kumo breakout, 4h, ATR2 stop, Donchian10 trail, pyramid, floor 1R -> +0.1R, ATR-regime filter),
1 % risk, 4 slots, five coins, late-entry gate (60 bars, 0.1521). Engine: high_cagr.kernel_fixes (the verified research engine).
Periods: TRAIN < 2025-01-01 <= VALID. Three views per variant:
* ALONE   Shahin on its five coins, own account
* ACCOUNT Shahin's legs in the shared three-bot account (Mojsavar with profit lock, Ghoghnous soft), five_year_report sizing
* OTHER30 Shahin alone on the 30 coins it never traded (generalisation; same variant, thresholds frozen from the five coins)

Variants (one change at a time vs the baseline):
* late entry: lookback {30, 60, 120} x threshold = TRAIN quantile {0.7, 0.8, 0.9} of the side-signed move on signal bars;
  current gate as "skip" vs "half size"; and no gate (for reference)
* entry / sizing: same-side cap {2, 3}; max one new entry per bar; slots {3, 5, 6}; shorts x0.5; no pyramid;
  pyramid risk x0.3 / x0.75; ATR-regime filter off; pilot entry (half size, rest at +0.5R)
* exits: profit floor {0.75R -> 0.1R, 1R -> 0.3R, 1.5R -> 0.3R, 2R -> 0.5R}; partial {1/3 at 2R, 1/2 at 3R};
  time stop (exit after 3 / 6 bars if MFE < 0.5R); tighter trail (4-bar channel) after {2R, 3R};
  stale guard (6 bars, MFE < 0.4R); failed-breakout exit (close back inside the breakout level / the Kumo edge)

A variant PASSES only if ALL hold:
* S1 ALONE Calmar >= 1.05 x baseline in TRAIN and in VALID
* S2 ACCOUNT Calmar >= baseline in TRAIN and in VALID, and ACCOUNT full max DD <= baseline + 1 pp
* S3 OTHER30 full-period Calmar >= baseline OTHER30 full-period Calmar
Passing variants are then combined greedily (in order of ALONE validation Calmar) and each addition must keep S1-S3.
