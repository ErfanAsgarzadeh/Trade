# Quant Ichimoku M15/H4 — independent experiment

Standalone version of the user's QuantIchimokuBacktester. Does **not** alter Shahin, Mojsavar, Ghoghnous, LBank services, configs, database, or live/paper positions. No orders are sent.

Signals: closed 4h Kumo + Tenkan/Kijun slope + ADX>22, closed M15 RSI 3-candle pullback to Kijun, rejection candle above/below M15 Kumo and Tenkan, UTC signal session 08–21. ATR0.5 + last-5-bars swing stop; minimum stop 0.4%; TP1 50% at 1.5R; remaining exits at BE/closed-bar Kijun. Default risk 1.5%, independent initial balance $1,000 for each asset.

**Corrections vs submitted prototype:** complete H4 bar must close before regime becomes available; indicators never read future bars; orders triggered on completed M15 candles execute at next M15 open; candle intrabar stop has priority over TP1; stop gaps fill at the open; TP1 BE takes effect starting following bar; equity curve includes unrealized PnL; fees accrue on every fill; slippage modelled as 2 bps each fill; initial quantity capped at 80% equity margin with 5x leverage; risk size includes stop and estimated fees/slippage. Entries are not immediately replayed on the signal bar.

Historical dataset: existing **Binance USD-M futures** official minute archives in `btc_backtest/cache/` and `portfolio/cache/` (not LBank candles). Existing `restore_data.py` reconstructs these files, verifying checksums. Recompute M15 from 1m (no synthetic fillers); main period `2021-10-05` inclusive to `2026-10-05` exclusive, with warmup since August 2021. Any missing archive/minute aborts run. 5 symbols are evaluated **independently**, not as a shared portfolio.

```bash
python restore_data.py
pip install -r lbank_project/requirements.txt
python -m quant_ichimoku.run --source repo --symbols BTCUSDT ETHUSDT SOLUSDT XRPUSDT ADAUSDT
# Or provide real UTC M15 data (at least 1200 bars):
python -m quant_ichimoku.run --source csv --csv /path/BTCUSDT_15m.csv --symbols BTCUSDT
python -m pytest quant_ichimoku/test_backtester.py -q
```

Outputs under `quant_ichimoku/output/`: `report.json`, per-symbol trades and mark-to-market equity CSV. `report.json` includes absolute interval, number of trades (round trips, not partial fills), net mark-to-market return, CAGR, MaxDD, win rate, profit factor, and monthly returns.

**Limitations:** Funding, historical contract-size/tick-size, liquidation/margin-call tiers, varying spread, live order routing and price-impact are not modeled. The configured commission is **6 bps per fill**, i.e. **12 bps round-trip** for a full position before TP splits; slippage is **2 bps per fill**. End-of-test positions are *marked* but not forcibly liquidated (therefore final close fees are excluded if open). Trailing exit uses next-open market execution; protective fills are simulated from 15m OHLC with conservative stop-first priority where path is ambiguous. Results are exploratory and are not evidence of live profitability or equivalent to LBank execution.