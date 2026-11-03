# Chabok optimisation — pre-declared (written before any result of this study was seen)

Rules kept from `lbank_project/scalp_sleeve.py` (branch feat/15m-fourth-bot-paper-20261029), parametrised:
long when the closed entry bar closes above the highest high of the previous N bars, close > EMA20 and EMA20 rising,
RSI14 in [55, 75] (optional), ATR14/close >= 0.15 %, and the last CLOSED trend bar (4 x the entry timeframe) has
EMA50 > EMA200 and close > EMA50 (optional); short mirrored (RSI [25, 45]). Entry at the next bar's open, skipped when that open
is more than 0.5 ATR from the signal close. Stop = max(stop_atr x ATR, 0.6 % of price); trail = best close - trail_atr x ATR
(ratchet, 0 = off); time stop after max_bars bars (0 = off); optional profit lock (+1R -> stop +0.1R, half closed at +2R).
Costs: 0.06 % fee per side, 2 bps slippage per fill, historical funding. One position per coin.

Grid per timeframe (15m, 30m, 1h, 2h, 4h, 1d): N {20, 40, 80} x RSI band {on, off} x trend filter {on, off}
x stop_atr {1.5, 2, 3, 4} x trail_atr {0, 2.5, 4, 6} x max_bars {0, 48, 96} x lock {off, on} = 1,152 configurations.

Data: Binance USDT-M 1m bars of the 49 TheTrueTrade coins with >= 18 months of history (PAXG excluded), 2021-10-05 ..
2026-10-04, no trade before listing + 60 days. Coins are split by latest liquidity rank, alternately, into
A (selection, 25 coins) and B (holdout, 24 coins). Periods: TRAIN < 2025-01-01, VALID >= 2025-01-01.

Selection, per timeframe: among configurations with >= 300 A-TRAIN trades, the highest A-TRAIN daily-R Sharpe.
A configuration (and so the timeframe) PASSES only if ALL hold:
* C1 profit factor (in R) >= 1.10 and total R > 0 on A-VALID, B-TRAIN and B-VALID separately
* C2 with costs doubled (one extra round trip per trade), PF >= 1.0 on B-TRAIN and B-VALID
* C3 every calendar year on A+B with total R >= -10 (no lost year worse than 10 R)
A passing configuration is then added to the shared three-bot account (TTT-recommended lists) at 0.25 % risk and
must not lower the account's validation Calmar (C4). Nothing is deployed from this study without the owner's request.
