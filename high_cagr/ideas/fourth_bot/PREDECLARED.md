# Fourth-bot candidates — pre-declared (written before any result of this study was seen)

Same data, coin groups and periods as `high_cagr/ideas/chabok/PREDECLARED.md`: 49 TTT coins (Binance USDT-M 1m),
A = 25 coins for selection, B = 24 untouched coins (alternate by latest liquidity), TRAIN < 2025-01-01 <= VALID,
no trade before listing + 60 days. Costs: perp fee 0.06 % per side, 2 bps slippage per fill, historical funding.

## 1. Mean reversion (`mean_reversion.py`)
Entry on a CLOSED bar, fill at the next open:
* BB20/2.0, BB20/2.5: long when close < SMA20 - k x std20, short when close > SMA20 + k x std20
* RSI2-10, RSI2-5: long when RSI(2) < 10 (5), short when RSI(2) > 90 (95)
Filter: none | with-trend (only longs while the 4x-timeframe EMA50 > EMA200 and close > EMA50, shorts mirrored) |
range (ADX14 < 20). Exit: stop = entry -/+ stop_atr x ATR14 (min 0.6 %), take profit when the bar closes back
beyond SMA20 (mode "sma20") or SMA5 (mode "sma5"), time stop after max_bars bars. One position per coin.
Grid per timeframe (15m, 1h, 4h, 1d): 4 entries x 3 filters x stop_atr {1.5, 2.5, 4} x max_bars {12, 24, 48} x 2 exits = 216 (first written as 432: arithmetic slip, the grid itself is unchanged).
Selection and gates exactly as Chabok (highest A-TRAIN daily-R Sharpe with >= 300 A-TRAIN trades; C1 PF >= 1.10 and R > 0
on A-VALID, B-TRAIN, B-VALID; C2 doubled costs PF >= 1.0 on B-TRAIN and B-VALID; C3 no calendar year below -10 R).

## 2. Funding carry (`funding_carry.py`), delta-neutral
Short the perpetual and buy the same notional on Binance SPOT (1h spot closes downloaded from data.binance.vision)
when the mean of the last K funding prints known at the hour is > theta_in; close both when it falls below theta_out.
Hourly decisions, funding credited at each print while open. Costs per round trip: perp 2 x (0.06 % + 2 bps), spot
2 x (0.10 % + 2 bps). P&L = funding + perp leg + spot leg (basis included). Capital: up to 10 positions, each
notional = capital / 10 / 1.2 (spot fully paid + perp margin at 5x). Daily return on capital, no compounding.
Grid: K {1, 3, 9} x theta_in {0.01 %, 0.02 %, 0.03 %, 0.05 %} x theta_out {0, theta_in / 2} = 24.
Selection: highest A-TRAIN Sharpe. PASS if annualised return > 3 % and Sharpe > 1 on A-VALID, B-TRAIN and B-VALID,
with costs doubled still annualised > 0 on B-TRAIN and B-VALID, and max drawdown on A+B < 10 %.

## 3. Account value (only for a candidate that passes)
Added to the shared three-bot account; must not lower the account's validation Calmar.
