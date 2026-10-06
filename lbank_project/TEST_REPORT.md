# Test report

Executed on 2026-10-05, Linux, Python 3.12.14. No private exchange requests or real orders were made.

## Results

| Check | Result |
| --- | --- |
| Python suite: `python -m pytest tests -q --tb=short` | 109 passed; combined engine + backtest suite: 120 passed, 4.70 seconds |
| JavaScript DOM logic: `node tests/test_ui.cjs` | Passed |
| Python compilation | Passed |
| Two running subprocesses: engine + Uvicorn, shared SQLite/config | Passed, included in the Python suite |
| Parallel close from separate OS processes | Passed; one history record, no double close |
| Python 3.11 binary dependency resolution for requirements.txt | Passed with pip dry-run |
| Docker Compose structure | Parsed and checked in the Python suite |
| Docker image build / container startup | Not executed: Docker unavailable |
| Browser screenshot / visual layout validation | Not executed: browser unavailable |
| Public LBank network availability / CSV producer integration | Not verified against the live exchange |
| Live futures trading | Unsupported and blocked by implementation |

The suite emitted one third-party Starlette deprecation warning about its httpx test-client adapter. No test failed.

## Tested dependencies

| Package | Version |
| --- | --- |
| ccxt | 4.5.85 |
| pandas | 2.2.3 |
| numpy | 2.2.6 |
| fastapi | 0.142.2 |
| uvicorn | 0.54.0 |
| pydantic | 2.13.5 |
| pytest | 9.1.1 |
| httpx | 0.28.1 |

## Coverage of behavior

- SMA-seeded Wilder RSI/ATR checked against independent numerical loops, including flat and one-sided price series.
- Ichimoku rolling values, current/future displacement and Chikou trend gates.
- Open-candle exclusion: large changes to the discarded current candle do not alter indicator results.
- Invalid, duplicate, non-finite and gapped candles rejected; stale history prevents entries and requests retries.
- Long/short signal anatomy, H2/L2 attempts and Barb Wire filtering.
- Fee-adjusted quantity, contract-size conversion, margin cap, gap re-sizing and updated TP1.
- Pending trigger activation, expiry, invalidation and cancellation when automatic entry is disabled.
- Both sides through INITIAL, TP1 partial close, breakeven stop and TRAILING_KIJUN; small positions close completely at TP1.
- Kijun stop ratcheting and closed-candle exits; existing stops still function when config cannot be reloaded.
- Candidate ranking, three-slot allocation, immediate-entry mode, persistent candle deduplication and the rolling daily loss breaker.
- Atomic config replacement under concurrent reads/writes, WAL mode and transaction rollback.
- Duplicate close attempts from threads and separate processes do not duplicate realized PnL.
- Panic closes active paper positions, cancels pending entries and stops new entries; feed failures preserve the unclosed position and report errors.
- Existing rows marked live are never paper-closed or silently deleted.
- API PIN checks, pending PnL zero, missing prices represented as unknown, configuration validation, ETag conflicts and no-store responses.
- DEMO never calls exchange network methods; CSV futures candles never call the pinned CCXT spot OHLCV method.
- UI connect, position rendering, percentage-to-ratio conversion, JSON/quick-control synchronization, conditional save, panic and unknown PnL.

## Exchange limitation verification

The installed `ccxt.lbank` implementation was inspected locally. Its capability flags are:

```text
swap: None
createReduceOnlyOrder: False
setLeverage: False
setMarginMode: False
fetchPositions: False
```

`create_order` uses spot private endpoints; `fetch_ohlcv` uses `spotPublicGetKline`. `fetch_ticker` routes swap markets to public contract tickers. The application therefore supports synthetic DEMO and futures CSV paper trading with public futures tickers, and rejects live execution.

References:

- https://github.com/ccxt/ccxt/blob/master/python/ccxt/lbank.py
- https://github.com/ccxt/ccxt/wiki/ccxt-vs-lbank-api
- https://www.lbank.com/docs/contract.html

## Structural optimization regressions

Twenty new tests cover both long and short sides: minimum-stop reject/widen; risk/margin cap; quarter-R and candle-confirmed partial stop; no partial close at the pure-runner 2R milestone; hard 4R exit; fresh closed 4h trail timing; Wilder ADX seed and flat/up/down cases; slope and ADX gates; deployed BTC-only SINGLE configuration. The five-year minute kernel was replayed against the frozen baseline and winner; its baseline trade count, net PnL and DD matched exactly. See optimization/TEST_RESULTS.md in the optimization bundle for cost and intrabar controls.

Subprocess integration also passed with the deployed winning config, in addition to the frozen baseline config.

## Four-family benchmark validation

Nineteen additional tests cover clean RSI pullback ranges, strict momentum RSI and fresh Kumo cross, prior-bar Donchian extremes without including the current bar, mechanical H2/L2 second attempts, full hard-target exits, close-through exits that ignore intrabar line wicks, pending regime invalidation before fill, directional opposite-channel trail, and actual market-gap micro-stop rejection. An OHLC/RSI counterexample verifies that wick contact with Kijun and RSI>=50 can coexist.

The benchmark and runtime share strategy_archetypes.py. All 112 definitions were checked in 1,120 actual windows for feature, regime and entry parity. The minute cost kernel reproduced the original 241-trade baseline net, fees, funding and DD exactly. The selected 288-trade result was replayed with reversed intraminute High/Low order and doubled missing funding cost. See archetypes/TEST_RESULTS.md in the full benchmark bundle.
