# Offline XGBoost vs 1D-CNN trade filter

Research-only comparison for frozen Shahin configuration HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4.
No live or paper trading configuration is changed by this branch.

Run tests: python -m pytest high_cagr/test_ml_trade_filter.py -q
Install optional dependencies: python -m pip install -r high_cagr/ml_requirements.txt
Restore inputs if absent: python high_cagr/restore_inputs.py; python high_cagr/prepare.py
Run experiment: python -m high_cagr.ml_trade_filter
Results: high_cagr/output/ml_trade_filter_results.json

Method: 48 fully closed 4h bars; XGBoost summaries and CNN sequences use the same causal source data.
Trade labels use net realized R in the previously committed baseline position ledger.
14-day exit-time embargo; validation years 2023/2024/2025; evaluation years 2024/2025/2026.
Thresholds selected solely on prior validation-year full minute replay, never the test year.
Test-year portfolio equity resets to $10,000; outputs cannot be summed as a five-year CAGR.

Limitations: historically accepted baseline trades alone have labeled outcomes; selection bias.
The baseline strategy and symbol universe were previously selected on overlapping data.
Historical market data comes primarily from Binance and does not validate LBank execution.
Model scores are not probability-calibrated. No production activation or proven performance uplift.