# Wave research on the repository's Binance USD-M data

This package screens 52 named candidates and runs every rule it can specify as a causal, reproducible signal. A **proxy** is a mechanical interpretation for research, with no claim to reproduce an author's full method. Five candidates with no validated rule in this package are reported as **Not Tested**. Executed candidates may also have too few trades to rank. See the generated reports for the exact status and counts.

## Run

```bash
python -m pip install -r wave_research/requirements.txt
python restore_data.py
python -m unittest discover -s wave_research/tests -v
python -m wave_research.main --workers 2 --output wave_research/results
```

`--config` selects a YAML file. `--checkpoint` selects the baseline cache directory. An atomic per-symbol checkpoint is keyed to the config, source and input manifests, so repeating the command resumes a matching baseline. `--baseline-only` runs only that phase, including on shorter date windows or alternate subsets. The full run currently uses the bot ledger's fixed date window. The HTML and Excel reports are generated locally. Large CSVs are gzip-compressed.

## Coverage and protocol

- Binance USD-M futures minute OHLCV and funding from the repository, verified against its manifests. BTC, ETH, BNB, SOL, XRP and ADA were available in compatible minute archives. XAUUSD, EURUSD, GBPUSD, USDJPY, NAS100 and US30 were unavailable in those archives. The five-year run uses the common bot-ledger period, 2021-10-05 to 2026-10-04 UTC inclusive. 2018 through July 2021 is absent, and the August through early October 2021 archives are outside this run.
- All seven requested bar sizes derive from the same contiguous minutes. Missing candles fail verification rather than being filled. Funding uses the available archived rates and treats minutes with no event as zero. Historical bid/ask spreads, maintenance margin/liquidation, historical lot/tick rules, asset universe changes and selection of assets before the period could not be verified. The six-asset universe is conditional on what the repository archives and does not correct survivorship bias.
- Calendar days split 60% training, 20% validation and 20% final. Each rule is ranked on training by Sharpe less 0.015 × maximum drawdown in percentage points, with a minimum sample and positive expectancy. The eight strongest eligible rules get a one-factor grid and a seeded random interaction search. Up to three variants per optimized rule advance from training, and validation picks one. Finalists are the three highest validation scores from distinct signal families: S01/S31 share a signal, while S02/S04 partition S30's breakout events. The full pair matrix still includes related rules. Final-period observations do not choose variants or finalists. The archive was already used in repository research, so the final slice is a temporal holdout for this pipeline and is not independently fresh market data.
- The baseline uses E13 market after confirmed signal, SL06 (2 ATR), TP03 (2R), maximum 18 bars. It evaluates long, short and combined direction, and fixed-dollar vs compound sizing at 0.25%, 0.5%, 1% and 2% for the combined direction. The search adds E01 (a three-bar 61.8% resting retracement limit of the signal candle), E02 engulfing, E03 pin bar, E09 MACD cross, E11 previous-bar sweep, E12 (0.3 ATR continuation), SL03–SL08, and a signal-bar structural stop with 0.1 ATR buffer (SL09 proxy). Confirmation models wait at most three closed bars and enter on the following open. The search tests TP01–TP07, TP14 ATR trailing and TP17 price break-even at 1R, 1.5R and 2R with a 3R cap. Break-even moves the stop to entry price with friction still charged. Filters include EMA20/50/100/200 direction, RSI centerline, MACD histogram, relative volume, high/low ATR, and three fixed UTC session approximations. E04–E08, E10, SL01–SL02, TP08–TP13, TP15–TP16, news, ADX, Fibonacci confluence and weekday/hour tuning were not executed.
- Stop and target are tested along the minute path. Stop takes precedence in an ambiguous minute, gap fills use its opening price where appropriate, and the high/low beyond an ambiguous exit are excluded from MAE/MFE. Market fills include slippage, taker fees and directional funding. A standalone account holds at most one leg per tested configuration and marks open positions at the end of each day. Period trade metrics assign realized legs by close date; equity returns mark at the boundaries with open trades carried through. The margin calculation uses isolated 5× leverage, an 80% cap, $20 minimum notional and fractional quantity.
- Shared-account replay tests every pair of training-eligible wave rules and every eligible single rule by itself and against each of the seven nonempty bot subsets. The three finalists are also combined and replayed against the same subsets. The archived three-bot baseline uses Shahin, Mojsavar and Ghoghnous `C_exhaustion_soft × 1.5` from the previous research commit. Orders in the same minute use deterministic bot-first order and enter before exit events. Each wave rule uses its selected instrument/timeframe and base risk; position legs on overlapping symbols remain independent. Bot fills and outcomes remain frozen. Shared sizing/margin/curves use realized balances because matching minute marks for the entire bot universe are absent. Its drawdown excludes floating losses and is comparable only to the corresponding shared-account baseline.
- Stability artifacts include four fee/slippage multipliers (1×, 1.5×, 2×, 3×), a relative trend/range proxy based on a training-fixed price-change threshold, sensitivity of validation to searched parameters, two expanding walk-forward folds within development (60→70% and 70→80%), and 10,000 circular 14-day block bootstrap paths per finalist. Bootstrap uncertainty is conditional on realized holdout returns and does not correct for screening thousands of correlated configurations. Screening counts and rejection reasons are published. Optuna/Bayesian tuning, fresh external market validation and formal multiple-testing inference were not executed.

## Rules

Wave rules use alternating **close** pivots, with separate occurrence and confirmation indexes. The ATR ZigZag emits a pivot only when an observed reversal closes. The engine also supports price-dependent percentage thresholds and confirmed symmetric fractals. Each row is symmetric long/short unless the pattern is explicitly bullish or bearish. Numbering matches the requested catalog. For harmonic ratios, nominal targets and bands are expanded by the relative tolerance from the config. All checked sides are written in `strategies/rules.py`.

| ID | Rule used |
|---:|---|
| 01 | Confirm pullback into 38.2–78.6% of prior swing and above its origin, then enter on the next open. |
| 02 | Cross the last confirmed opposite pivot with no two-level trend-continuation classification. |
| 03 | Higher reaction low, with the fourth pivot above wave 1's high and below the wave 3 high. |
| 04 | Break a confirmed pivot while both highs and lows continue in the same direction. |
| 05 | Reverse after a six-pivot impulse, no 1/4 overlap, wave 3 not shortest. |
| 06 | Enter continuation of the corrective leg after B, with B failing to retake A's origin. |
| 07 | Reverse after local A–B–C geometry with B below A's origin and C beyond A. |
| 08 | B retraces 38.2–78.6% of A and C projects 61.8–161.8% of A beyond A's end. |
| 09 | Near-complete B retracement, with C extending near or moderately beyond A. |
| 10 | B extends past A's start and C extends beyond A's end, using the expanded ratios in code. |
| 11 | B extends past A's start and C falls short of A's end. |
| 12 | Five-pivot contracting local range. |
| 13 | Five-pivot broadening local range. |
| 14–17 | Not Tested. Double/triple Zigzag and Three lack validated lower-degree subwave segmentation. |
| 18 | Overlapping converging five swings with decreasing directional lengths. |
| 19 | Overlapping diverging five swings with increasing directional lengths. |
| 20 | Six-pivot impulse whose last leg fails to reach the third leg's terminal extreme. |
| 21 | MACD-type momentum cross with bias from the latest closed four-bar EMA group. |
| 22 | 38.2–78.6% pullback with duration 61.8–161.8% of the preceding swing. |
| 23 | AO cross of zero. |
| 24 | Confirmed improving AO extrema on one side of zero without an intervening zero cross. |
| 25 | AO saucer using two same-direction changes followed by the reversal, on the relevant side of zero. |
| 26 | Confirmed fractal level crossed with the three displaced Alligator averages aligned. |
| 27 | Not Tested. NEoWave requires a separately validated interpretive implementation. |
| 28 | Five alternating pivots and fifth pivot at or beyond the projection through the first and third. |
| 29 | Confirmed successive higher highs/lows or lower highs/lows. |
| 30 | Close crosses a confirmed ZigZag breakout level. |
| 31 | Confirmed continuation pullback in the rule 01 band, with no Elliott-specific context. Rules 01/31 currently share the same signal and should not be treated as independent evidence. |
| 32 | Reversal in a declining (mirrored rising) swing sequence on declining directional volume per bar. |
| 33–34 | Spring/Upthrust proxies. Sweep a prior 24-bar extreme and close back inside the range. |
| 35–36 | LPS/LPSY proxies. EMA34 test and reclaim/failure in the direction of the prior close. |
| 37 | Turns in the slope of a trailing 10/40 moving-average cycle proxy. |
| 38 | First two consecutive higher-high/higher-low bars or their bearish mirror. |
| 39–40 | N/V shape proxies from a local continuation structure in shallow/deep pullback bands. |
| 41 | Causal eight-bar Haar detail, computed from current and earlier four-bar blocks. |
| 42 | AB=CD length equality, BC retracement and CD extension constraints. |
| 43–48 | Gartley, Bat, Butterfly, Crab, Deep Crab and Alternate Bat, checking geometry and AB/XA, BC/AB, CD/BC and AD/XA. |
| 49 | Shark proxy using its 0–X–A–B–C ratio bands. |
| 50 | Five-O proxy checking precondition extensions, 50% BC retracement and reciprocal AB=CD. |
| 51 | Three Drives proxy checking both intervening retracements and both next-drive extensions. |
| 52 | Cypher checks AB/XA, XC/XA and CD/XC with directional geometry. |

The remaining wave-engine work includes validated recursive multi-degree alternative counts, a distinct CHoCH rule, and cross-market feeds for traditional instruments.
