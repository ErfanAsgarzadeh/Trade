# The five-year Avina backtest shown on the home page

Full calendar period: 1 January 2021 to the end of 31 December 2025 UTC; 1,826 days.
Scenario: all three Avina bots on one shared account with $10,000 starting capital, no deposits or withdrawals and
profits reinvested. The scenario includes no gold purchases or 50% profit withdrawals and should not be compared
like-for-like with reports of that scenario.

Simulated result: $964,451.77 at the end of the period; a total return of about 9,544.52% and a compound annual
growth rate (CAGR) of about 149.4%; a maximum drawdown, measured on minute-close prices, of about 30.70%. Open profit
and loss and costs are included in the valuation. The hero chart shows end-of-day value on a log scale. Drawdown uses
the worst minute observation of each day rather than an estimate from the daily curve. Intra-minute, tick and full
mark-price effects are not included.

Prices come from Binance USDⓈ-M futures data; this is not a historical LBank run or a live account result. One USDT is
assumed to equal one dollar. Symbol listing dates and indicator warm-up periods are respected for each bot. A 0.06%
fee per side, 2 basis points of adverse slippage per fill and recorded funding from the research output are included.
The model uses 5x leverage and an 80% cap on total margin. Order-book depth, market impact, historical exchange
precision limits and full mark-price liquidation are not rebuilt.

License costs and taxes are not modeled.

The current research settings were tested on past data; this is not an independent forward test or an audited live
record and carries the risk of choosing settings from history. Past performance does not guarantee future profit or
performance. The return figure is not a sum of monthly returns; it is the ratio of final value to starting capital.

The daily CSV and the JSON summary are available in this folder. The JSON records the assumptions, the drawdown
definition, the SHA-256 hash of the public CSV and the hashes of the research input and engine. No live signals or
private customer account data are included in these files. The bots' trading logic is proprietary and not published.
