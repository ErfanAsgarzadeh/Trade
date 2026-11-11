# Position scorer — pre-declared (written before any result of this study was seen)

Goal (owner): one model that scores every position of the three bots for its chance of success, before entry and while it is
open, and manages that position's risk. Ledger: the deployed rules (Shahin late-entry gate; Mojsavar profit lock + half at 2R with
the CORRECTED simulation; Ghoghnous soft). Earlier evidence to beat: a win/lose XGBoost entry gate had AUC 0.50 (winrate study);
on the old rules a "big winner" entry score + cross-sectional momentum sizing passed walk-forward and in-trade "protect" did not
(lbank_feasible). Inputs are limited to what the live bot has: candles, volume, funding.

Data: deployed legs + AUGMENTED legs (the same engines on the other of the 35 coins; training only). In-trade states at every 4h
close while a leg is open (from 4h after entry). Costs as everywhere.
Models (XGBoost regressors, depth 3, 300 trees, lr 0.03, subsample 0.8, min_child_weight 20):
* ENTRY  target = the leg's net R clipped to [-1.5, 8]; features = entry features of winrate/ledger.py (coin, BTC, funding, time)
         + side-adjusted 30-day momentum rank across the 35 coins + bot.
* HOLD   target = (value of holding the remaining size to its real exit - value of closing it at this 4h close) in R, clipped to
         [-3, 8]; features = unrealised R, MFE, MAE, give-back, bars held, remaining fraction + the same market block at this bar.
Scores are percentiles of out-of-fold training predictions (5 folds grouped by coin).
Walk-forward folds 2023 / 2024 / 2025-26: a training leg must have exited >= 14 days before the fold starts.
Policies (fixed now):
* E_skip20  no root entry when the entry percentile < 0.20      * E_size  risk x (0.5 + percentile)      * E_both  both
* M_only    risk x (0.5 + momentum rank) - one-feature benchmark, no model
* T_cut     close when hold percentile < 0.10 and unrealised R <= 0      * T_exit10  close when hold percentile < 0.10
* T_half20  close half (once) when hold percentile < 0.20
* combined  the best passing entry policy + the best passing in-trade policy (by the sum of fold Calmars)
Judged on the deployed legs of each fold, replayed on a fresh $10,000 shared account (dd_engine.period).
PASS = Calmar >= baseline AND max DD <= baseline + 2 pp in EVERY fold. Skill is also reported: AUC of the entry score for
winners, Spearman of each score with its target, per fold and bot.
