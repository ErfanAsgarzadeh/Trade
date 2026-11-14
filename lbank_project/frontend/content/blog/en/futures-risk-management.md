---
title: Risk Management in Futures Trading: Position Size, Leverage and Drawdown
description: How to size a position with a simple formula, what real leverage is, why total account risk matters more than per-trade risk, and how a daily loss stop protects an account.
date: 2026-11-13
keywords: risk management, money management, position sizing, futures leverage, drawdown
---
Most traders who lose their accounts did not have a bad strategy; **they managed risk badly**. An average strategy with good risk management can last for years, while the best strategy in the world with uncontrolled risk will sooner or later zero the account.

## Step one: define risk per trade as a percentage of the account

The most common rule is to put only a small share of the account at risk on each trade, usually between 0.5% and 2%. "At risk" means the amount you lose if the [stop-loss](/en/blog/futures-stop-loss/) is hit, not the full position value.

Why so small? Because even good strategies have losing streaks. At 1% risk, ten losses in a row cost about 10% of the account. At 10% risk, the same ten losses wipe out about 65% of it, and you then need about a 186% gain just to get back to where you started.

## Step two: size the position from the stop-loss

The formula is simple:

> Position size = amount at risk ÷ distance from entry to stop-loss

Example: your account is $1,000 and you want to risk 1%, which is $10. The entry is $100 and the stop is $95, a distance of $5. The position size is 10 ÷ 5 = 2 units, a $200 position.

Note that **leverage is not in this formula**. Leverage only decides how much margin is locked to open the position. At 5x, this $200 position needs about $40 of margin; at 20x about $10. The real risk is the same $10 in both cases, as long as the stop-loss is in place.

## Know your real leverage

The leverage you pick on the exchange is not the account's real leverage. Real leverage is the total value of all open positions divided by the account balance. If a $1,000 account holds five $400 positions, its real leverage is 2, even if each position is set to 20x.

High selected leverage has a hidden danger: less margin is locked, so the liquidation price sits closer to the entry. If the stop-loss fails to execute for any reason, liquidation comes sooner.

## Step three: cap total account risk

Per-trade risk alone is not enough. With ten positions open at 2% risk each, 20% of the account is at risk. In crypto most coins move with Bitcoin, so those ten positions may in effect be one big bet.

That is why you need a **total risk cap** as well as a per-trade cap. For example, once the combined risk of all open positions reaches 10% of the account, no new trade is opened.

## Step four: a daily loss stop and a drawdown cap

- **Daily loss stop:** if the account loses, say, 5% in a day, no new trades are opened until the next day. Bad days usually get worse with rushed decisions.
- **Drawdown cap:** if the account falls, say, 20% from its peak, new entries stop until the situation is reviewed.
- **Margin usage cap:** part of the balance always stays free so that swings in open positions cannot push the account to the edge of liquidation.

## How does Avina manage risk?

Before every entry, Avina's risk engine checks all of these rules: the risk of that trade, the total risk of open positions, the day's loss, the drawdown from the peak balance and margin usage. Position size is calculated from your live account balance. If any cap is reached that entry is skipped, but exits from existing positions are never blocked.

These rules do not remove losses. In sharp price gaps, slippage and abnormal market conditions, the real loss can exceed the plan. The goal is that no single loss or bad day can knock the account out of the game.

## Summary

Risk management means knowing, before you enter, how much you lose in the worst case. Keep per-trade risk small, size positions from the stop-loss, know your real leverage and cap the whole account. To learn how to judge a strategy's results, read [what a backtest is](/en/blog/how-to-read-a-backtest/).
