# ATR trailing ablation — 2026-10-07

Frozen Git baseline: 56fc480bd191c592e9e205bb927e8eab67823b3c.
Only tested change: Donchian stop-trail buffer 0.25 ATR, long subtract / short add.
Raw closed-channel breakdown retained. No ATR entry gate or 4B additions.
Decision: REJECT buffer 0.25; production default remains 0.0.

Results: Full CAGR 32.235064 -> 24.701389; DD 34.563348 -> 38.335956.
Data: 2021-10-05 <= UTC < 2026-10-05, five symbols, 2,629,440 minutes each.
Split 2025-01-01; independent $10,000 reset per split.
Fees .0012 round trip, adverse .0002 each fill; recorded funding plus Oct1-4 proxy.
Baseline numeric parity verified across all three periods. 168 tests + DOM smoke test pass.

Code in work/ is the updated production package; copy its changed files to
lbank_project/ in the original Git checkout. Keep original infrastructure files.
The patch applies against the frozen commit. Existing open positions retain
frozen trail_atr values; changes apply to newly sized positions.

Reproduction from a full original checkout:
1. Place atr_update/ at repository root using this archive. Install numpy pandas
   numba matplotlib and lbank_project/requirements.txt in a virtual environment.
2. python atr_update/source/high_cagr/restore_local.py
   (uses verified pinned source archive; BTC minute/funding cache must be present
   in btc_backtest/cache as in the original checkout).
3. python atr_update/source/high_cagr/prepare_local.py
4. OPENBLAS_NUM_THREADS=1 python atr_update/research/run.py
5. OPENBLAS_NUM_THREADS=1 python atr_update/research/report.py
6. python atr_update/research/final_package.py

Do not compare these baseline numbers with a different ATR-entry + 4B research
baseline. CSV equity is hourly; headline maximum DD includes intraminute phases.
The ledger slippage column is explanatory and already included in fill prices.
Reports use net PF and per-unit wins/losses; base plus add is one root position.

No minute caches are bundled. They can be retrieved from the pinned original
repository using restore_local.py; restored archives and price arrays are hashed.
Backtests assume adverse-first minute OHLC path, not actual live exchange ticks.
