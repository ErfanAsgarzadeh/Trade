---
title: What Is a Backtest and How Not to Be Fooled by One
description: A backtest tests a strategy on past data. Learn which numbers to look at, which assumptions to question and which signs mean a result is too good to be true.
date: 2026-11-13
keywords: backtest, strategy backtest, backtest results, drawdown, overfitting
---
A backtest runs a trading strategy's rules on past market data to see what result those rules would have produced over that period. Every serious trading bot should have one. But a backtest, like any tool, can mislead.

## What does a good backtest show?

The total return figure carries the least information. Ask for these too:

- **Test period:** six months in a bull market proves almost nothing. A good period spans several years and covers rising, falling and sideways markets.
- **Maximum drawdown:** the largest fall of the balance from its previous peak. It shows how much you would have to endure in the worst stretch.
- **Year-by-year returns:** if most of the profit came from one year or one trade, the result is fragile.
- **Number of trades:** twenty trades can be luck. Hundreds of trades build more confidence.
- **Equity curve:** a curve that suddenly jumps is different from one that grows steadily.

## Assumptions to question

Every backtest is a set of assumptions. These matter most:

1. **Fees:** in futures, the fee on each side of a trade is usually 0.02% to 0.06%. For a strategy that trades often, fees can eat the entire profit.
2. **Slippage:** the price an order fills at is not always the candle's price, especially in fast moves.
3. **Funding:** perpetual futures exchange a funding payment between longs and shorts every few hours.
4. **Look-ahead bias:** did the strategy use information that was not yet available at decision time, such as the close of a candle that had not closed?
5. **Coin selection:** if only coins we now know succeeded were tested, the result is optimistic.

## Overfitting: the biggest enemy of a backtest

Overfitting means tuning parameters so precisely to past data that the strategy has memorized the past rather than learned the market. Common signs:

- Many parameters with very precise values, such as "a 47-day moving average".
- A result that collapses when the parameters change slightly.
- An equity curve with almost no drawdown.

The best test for overfitting is a **forward test**: running the strategy on a period not used in its design, or live with small capital.

## Signs a result is too good to be true

- Returns in the thousands of percent with no mention of drawdown.
- Win rates above 90% alongside claims of low risk.
- No raw data or calculation method you can check independently.
- Promises of "guaranteed profit" or "no losses".

## How is Avina's record published?

Avina's backtest covers five years, from the start of 2021 to the end of 2025, running all three engines on one shared account. A 0.06% fee per side, slippage and recorded funding are included. The daily data, the summary and the calculation method can be downloaded on the [home page](/en/#backtest).

The limits are stated plainly too: this is a historical simulation, order-book depth and a full liquidation model are not rebuilt, and the settings were tested on this same history, so overfitting risk exists. No past result guarantees future profit.

## Summary

A backtest is necessary but not sufficient. Look past the return figure to drawdown, test period, cost assumptions and data transparency. A result you cannot check yourself is only a claim. For the practical side, also read [risk management in futures](/en/blog/futures-risk-management/).
