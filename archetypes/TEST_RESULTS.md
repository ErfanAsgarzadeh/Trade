# Validation — 2026-10-05

- Python 3.12.14; 120 tests passed in 4.70 seconds: 109 engine/dashboard tests and 11 original backtest tests.
- JavaScript dashboard DOM test passed, including hiding an unused TP target for pure trailing strategies and displaying actual hard-target / BE-milestone levels.
- All 112 family definitions checked on 1,120 actual 199-closed-bar windows for indicator, regime and entry parity between vectorized benchmark features and runtime. Standard/crypto Ichimoku, SMA-seeded window EMA, Wilder RSI/ATR, Donchian levels and both directions checked.
- Extended minute cost kernel exactly reproduced the frozen baseline: 241 trades, net −1040.49783519037, fees 848.51575277272, funding −59.000553715204 and DD 15.45229220919%, tolerance 1e-7.
- Selected winner replayed: 288 trades, net 2984.1391825081064, fees 723.9235432844712, funding −169.28950119956934, DD 7.0967756723392315%.
- Reversed intraminute High/Low order produced identical winner count, PnL and DD.
- Every trade ledger reconciles gross−fees+funding; actual filled stop distances are at least 1.2%. No partial-exit rows counted as separate trades.
- Missing archive funding stress: one adverse proxy event; doubled cost reduces net to 2983.7664324331054. The unarchived portion remains an assumption.
- New tests cover low-RSI bullish and high-RSI bearish pullbacks; strict momentum RSI boundaries; fresh Kumo crosses; prior-bar Donchian breakout excluding current extrema; mechanical H2/L2; full hard targets without partial fills; closed-bar exits ignoring intrabar wicks; GTC regime invalidation before fills; direction-specific opposite-channel trailing; actual market-gap micro-stop rejection; and a numerical counterexample to the proposed Kijun/RSI impossibility.
- Subprocess engine + dashboard integration passed with both legacy and deployed winning config; shared SQLite/config, authentication, ETags and panic controls passed.
- Chart visually inspected; HTML complete matrix and all 288 trade rows, inline PNG and search/eligibility JavaScript checked. Python sources parsed.
- One Starlette/httpx deprecation warning. No failed final tests. No live order, Docker build or browser screenshot performed.

Passing these checks establishes consistency and the requested eligibility conditions; it does not make the selected, validation-informed parameters an independent out-of-sample result.
