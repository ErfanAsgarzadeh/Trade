# Seven-method five-year walk-forward study

**Scope:** seven configurations of the original Shahin, Mojsavar and Ghoghnous signal ledger, with an expanding, exit-purged annual research walk-forward and strictly fold-fitted RobustScaler/Imputer. The AI layer never generates or modifies a base signal.

Core files: ai_research/seven_benchmark.py (seven models and account screen); ai_research/walkforward_features.py (causal stationary OHLCV, Bollinger, RSI, Ichimoku, wick/volume and completed HTF features); ai_research/strict_execution.py (true next-minute fills, SL-first TP/SL, fee 0.0005 each side, slip 0.0002 each side, explicit perp funding).

Available historical ledger: high_cagr/output/ideas/winrate/legs.pkl covering 2021-10-05 to 2026-10-04, with current Shahin late-entry signal check and Ghoghnous C_exhaustion_soft x1.5. However this ledger was created before current Mojsavar +1R to +0.1R profit lock and 50%-at-2R partial exits. The source net PnL also includes a higher original taker fee **0.0006 each side**, with 0.0002 slippage each side. Exact 0.0005 fee repricing is **impossible** without individual source fill-price/funding paths. Thus original costs are preserved (no duplicate fees), making the study conservatively priced but NOT equivalent to requested exact costs.

The 14-row benchmark contains **7 methods without F and 7 with an explicitly named F-style proxy**, NOT actual Claude F. The proxy uses realized-only account drawdown brake and volatility target at entry. The real F also adds market regime AI, per-bot streak controls and cuts positions already open. Source open-price paths and 35-coin data are missing, so a true matching 7×F on/off backtest and mark-to-market portfolio DD is **blocked**. Never present the table as verified actual F comparisons or real potential returns.

The cached signal feature set does NOT contain all required OHLCV fields. The complete feature builder is ready for raw per-symbol 1m/4h input, but for cached screening we include only genuine known historical entry columns. Models label historical signals by realized net R>0 (not true intrabar triple-barrier TP/SL; those labels require price paths), with maximum root exit time and 20×4h-bar embargo.

Outputs from GitHub Actions (.github/workflows/ai-seven-5y.yml):
- ai_research/output/seven_methods/benchmark_screen.md
- ai_research/output/seven_methods/benchmark_screen.csv
- ai_research/output/seven_methods/seven_equity_drawdown_screen.png (all curves)
- ai_research/output/seven_methods/equity_screen.csv
- ai_research/output/seven_methods/folds.json and audit.json

Validation: pytest ai_research/test_seven_benchmark.py ai_research/test_strict_execution.py, including anti-future perturbation of indicators and HMM forward filtering, label overlap purge, native SL-first collision, next-bar entry, mandatory funding and both-sided costs.

**Safety:** no modification of production main/PAPER/LIVE/F or existing entry/exit engine. No activation of an AI model based on this experimental output. For a full faithful 35-coin test, retrieve minute trade paths, source native signal/stop/TP streams and F output snapshots, replay the real trading book with mark-to-market then compare no F and F at matched risk and forward paper.
