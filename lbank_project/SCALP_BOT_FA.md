# Chabok (چابک): experimental fourth PAPER bot

Status: **research prototype; OFF by default; no live futures execution.**
No five-year low-timeframe backtest or real forward test has been performed.

## Strategy

Chabok operates alongside Shahin, Mojsavar and Ghoghnous in an independent SQLite
database and is included in their shared paper equity and margin calculations.

- 15m entry: a fully closed candle must break the prior 20-bar Donchian high/low,
  with EMA20 direction and RSI14 of 55–75 for longs or 25–45 for shorts.
- 1h trend: fully closed EMA50/EMA200 trend confirmation and price on the right side
  of EMA50. No incomplete current bar is used.
- Minimum ATR14/close on 15m: 0.15%.
- Entry only if the live sampled price is within half an ATR of signal close.
- Initial stop: 2 ATR or 0.6% of entry, whichever is wider; ratcheting trail:
  2.5 ATR below best close (above best close for shorts).
- Time exit: after 48 subsequent 15m bars, about 12 hours. No take profit.
- Budget: base 0.15% shared equity risk, with estimated fee/slippage allowance,
  at most 25% equity notional per position, at most two positions, paper 5x max.
- Stop new entries after Chabok's daily realized loss reaches 0.5% of shared equity.
- All existing margin limits and shared locking are preserved; watchdog checks
  stop prices even while entry scanner cannot read valid bars.

## Data and limitations

The existing 4h candle producer cannot feed this new strategy. The independent
scalp_candles.py samples the LBank public *futures* quote every 10 seconds and
writes separate 15m and 1h CSV files. It does not touch existing 4h files.

These bars are NOT native futures OHLCV. Very short wicks can be missed; volume
is unavailable (written as zero); gaps are retained and reject scanning.
Recorded Paper stops are simulated, not exchange-native protective orders.
Paper P&L does not fully model actual spread, slippage, gaps or funding.
Actual profitability or safety is unproven. Do not use with real funds.

A new collector needs at least 350 1h bars (about 15 days) plus 300 15m bars
(about 3.2 days), each with the extra forming bar, before scan readiness.
No fake history is backfilled.

## Safe preparation only

1. Review the draft PR and run all tests before deploying. Do not overwrite
   existing runtime configs, databases, logs or current server processes.
2. With this branch checked out inside lbank_project, if the new runtime config
   does not exist: cp scalp_config.json runtime/scalp_config.json
3. Leave PAPER_DATA_MODE=csv-lbank, SCALP_IN_BOT=0 and the config's enabled=false.
4. Run ONLY the collector:
   docker compose --profile scalp up -d --build lbank-scalp-candles
5. Check runtime/ohlcv/BTC_USDT_USDT_15m.csv and corresponding BTC 1h and ETH
   files. Check for consecutive timestamps, data age and market availability.
6. Run python -m pytest tests/test_scalp_sleeve.py -q and the full suite.
7. Only after walk-forward backtests and extended Paper forward tests, enable
   the 15m engine in an approved, controlled rollout using SCALP_IN_BOT=1 and
   enabled=true. Do not enable it based on this source code alone.

The collector and engine remain opt-in; enabling one does not enable the other.

## New authenticated dashboard endpoints

GET /api/scalp/status
GET /api/scalp/config
PUT /api/scalp/config (ETag/If-Match supported)
POST /api/scalp/close with symbol in JSON
POST /api/bots/toggle with bot=scalp and enabled boolean

The fourth sleeve is also included in the emergency close-all endpoint, and
its paper positions are included in the dashboard position and margin views.

When the entry thread is off, positions remain in shared-account accounting,
but automatic watchdog supervision for Chabok is also off. Do not leave open
positions unmanaged; use the thread or manually close them.

## Required backtest before active Paper trading

Replay true 1m/15m futures history from 2021 to 2026, with decisions after
15m/1h close and intrabar exits at observed minute resolution. Include funding,
0.12% round-trip taker fees, slippage/depth/spread sensitivities and minimum
contract sizing. Evaluate standalone and jointly with all existing sleeves.
Keep a genuinely untouched out-of-sample period; report full CAGR, DD, trade
count, profit factor, fee drag, margin, overlap and negative years.
