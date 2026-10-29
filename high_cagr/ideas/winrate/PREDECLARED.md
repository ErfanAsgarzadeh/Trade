# Win-rate study — pre-declared (written before any variant result was seen)

Baseline: the three bots as shipped on 2026-10-11 on one $10,000 paper account, 2021-10-05..2026-10-04
(`five_year_report.replay()`, Ghoghnous = C_exhaustion_soft x1.5). Reproduced exactly (2,875 trades, P&L diff 0).
Periods as in every earlier study: TRAIN 2021-10-05..2024-12-31 (choose), VALIDATION 2025-01-01..2026-10-04 (judge).

Objective: a higher share of winning trades WITHOUT giving the money back elsewhere. A candidate is adopted only if:

* W1 trade win rate (all legs, three bots) >= baseline + 3.0 pp in TRAIN and in VALIDATION
* W2 account Calmar >= 0.95 x baseline in TRAIN and in VALIDATION
* W3 full-period max drawdown <= baseline + 2.0 pp
* W4 full-period CAGR >= baseline - 10 pp
* W5 causal (only data available at the decision minute)

Families:

1. Exit management (`exits.py`), per bot and for all bots, fixed grid:
   lock after arm: arm in {0.5, 0.75, 1.0, 1.5, 2.0} R, lock in {0.0, 0.1, 0.3, 0.5} R (lock < arm);
   partial: 50% at {1.0, 1.5, 2.0} R, with and without lock(1.0 -> 0.1 R).
   The variant is chosen on TRAIN (best train Calmar among those that pass W1-train), then judged on VALIDATION.
2. AI gate (`ml_gate.py`): walk-forward XGBoost, label = winner, drop fraction chosen on the previous year only.
   Only the walk-forward years 2023-2026 are filtered; it is judged on those years
   (window 2023-01-01..2026-10-04 vs the baseline on the same window) with W1-W4 applied to TRAIN-part 2023-2024 and
   VALIDATION 2025-2026.
3. Combination of the best of 1 and 2 (only if each passes alone).

Robustness reported for anything that passes: fee/slip x2, the 30-coin cross-check is not available for the gate.
