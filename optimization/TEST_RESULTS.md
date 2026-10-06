# Validation — 2026-10-05

- Python 3.12.14; 101 tests passed in 4.95s (90 engine/dashboard tests and 11 original backtest tests).
- JavaScript DOM test passed: connect, render, ETag save, config editor synchronization, panic and missing-price handling.
- Baseline replay: 241 trades; net −1040.49783519037; DD 15.45229220919%; matched the frozen original results to 1e-7.
- Winner replay: 8 trades; net 125.207072314588; fees 9.926602820599308; funding +10.877013205984213.
- Reversed intraminute High/Low ordering gave identical trade counts and net PnL for baseline and winner. DD may differ slightly; exact numbers in verification.json.
- ADX: 24 actual 199-bar windows agreed between optimization features and runtime indicators to 1e-10. Known flat/up/down cases and initialization index checked.
- All winning ledger PnL reconciled gross − fees + funding to 1e-8; fill fees equal ledger fees.
- New structural tests cover both sides for micro-stop reject/widen, quantity/risk limits, delayed partial SL, pure runner 2R milestone without partial fills, hard 4R exit, candle-confirmed BE, strict Tenkan slope and ADX threshold, and waiting for a fresh closed 4h candle.
- Existing tests cover old config compatibility, SQLite/WAL persistence, process-level serialization, restart, gap sizing, duplicate-close prevention, security, bad data and subprocess engine/dashboard integration.
- One third-party Starlette/httpx deprecation warning; no failed tests.
- No live order, Docker build or browser screenshot was performed. Generated comparison chart was visually inspected; HTML structure, complete matrix rows, embedded image and filtering script were checked independently.

These checks establish implementation consistency, not statistical robustness of the selected eight-trade configuration.

Subprocess integration also passed with the deployed winning config, in addition to the frozen baseline config.
