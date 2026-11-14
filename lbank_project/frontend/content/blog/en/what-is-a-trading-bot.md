---
title: What Is a Trading Bot? A Complete Guide to Crypto Trading Bots
description: How a trading bot works, what it can and cannot do, and what to check before you choose a crypto trading bot.
date: 2026-11-13
keywords: trading bot, crypto trading bot, automated trading, algorithmic trading, futures bot
---
A trading bot is software that watches the market according to predefined rules and sends buy and sell orders for you. The rules can be simple, such as "buy when the price breaks above its 20-day high", or a combination of indicators, trend filters and risk rules.

A trading bot is not magic. The one thing it does better than a person is to **follow the rules every time, without fatigue and without emotion**. If the rules are poor, the bot follows the poor rules just as faithfully.

## How does a trading bot work?

Most crypto trading bots have four main parts:

1. **Market data:** it reads prices and volume live or in fixed intervals, such as 15-minute candles.
2. **Entry and exit logic:** rules that decide when to enter a trade, in which direction (long or short) and when to exit.
3. **Risk management:** position size, stop-loss placement and a cap on total account risk.
4. **Execution:** sending orders to the exchange through an API key and checking that each order was actually placed.

The fourth part gets the least attention but matters a great deal in practice. A bot that believes it has a stop-loss in place, when the exchange never registered it, can take a large loss on the first sharp move.

## The advantages of a trading bot

- **Around-the-clock execution:** crypto markets never close. A bot makes the same decision at 4 a.m. as at 4 p.m.
- **No emotional decisions:** fear and greed are the two main reasons new traders lose. A bot is not scared by its last loss or careless after a winning streak.
- **Disciplined risk management:** a bot sizes every position with the same formula and never moves a stop-loss "in case the price comes back".
- **Testable:** a bot's rules can be tested on past data. This is called a [backtest](/en/blog/how-to-read-a-backtest/).

## The limits and risks of trading bots

Anyone offering you a trading bot with "guaranteed profit" is either misleading you or does not understand the market. The real limits are:

- **Changing market conditions:** a strategy that excelled in a trending market can lose repeatedly in a sideways one.
- **Overfitting:** rules tuned so tightly to past data that they only explain the past will not work in the future.
- **Execution risk:** slippage, exchange outages, network delays and software bugs all affect real results.
- **Leverage risk:** in futures, leverage magnifies gains and losses alike. Without sound [risk management](/en/blog/futures-risk-management/), even a good strategy can wipe out an account.

## Six questions to ask before choosing a trading bot

1. **Where is the money held?** Your capital should stay in your own exchange account, with the bot allowed to trade but not to withdraw. We cover this in detail in [safe API keys](/en/blog/safe-exchange-api-key/).
2. **Where is the stop-loss placed?** A stop-loss that only lives inside the bot stops working when the bot goes offline. It must be placed on the exchange. Read more in [stop-losses in futures trading](/en/blog/futures-stop-loss/).
3. **How are past results presented?** A single return figure is not enough. Ask for the maximum drawdown, the test period, the fees and the raw data.
4. **How much is risked per trade?** A good bot caps the risk of each trade and of the whole account.
5. **What happens when the bot goes offline?** Open positions must keep an active stop-loss even without the bot.
6. **Can you see the trades?** You should be able to see every trade, stop-loss and result in your own panel.

## How does Avina answer these questions?

Avina runs three independent trading engines on one account. Your funds stay in your own exchange account, every position carries a stop-loss on the exchange from the moment it opens, and the bot reads it back from the exchange after every change.

Avina's five-year backtest, with daily data and the calculation method, is published on the [home page](/en/#backtest). These are historical simulations, not live account results, and they guarantee no future profit.

## Summary

A trading bot is a tool for executing a strategy consistently, not a money machine. With sensible rules, controlled risk and reliable execution, a bot can add the discipline that people usually lack. Above all, judge the evidence, not the promises.
