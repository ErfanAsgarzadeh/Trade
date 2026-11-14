---
title: Stop-Losses in Futures Trading and Why They Belong on the Exchange
description: What a stop-loss is, how to place it, fixed versus trailing stops, and why a stop that lives only in a bot or in your head is not enough.
date: 2026-11-13
keywords: stop-loss, stop loss, futures stop-loss, trailing stop, risk control
---
A stop-loss is an order that closes a position when the price reaches a set level, so the loss cannot grow beyond a predefined amount. In leveraged futures trading a stop-loss is not optional; **it is part of the trade itself**.

## Why is a stop-loss vital in futures?

Say you open a trade at 10x leverage. A 5% move against you means roughly a 50% loss on that position's margin. If the move continues, the position nears liquidation and the exchange closes it with the full margin lost.

A stop-loss moves that decision from a moment of panic to a moment of calm. You decide before entering how much loss you accept, not while the price is racing against you.

## Where should the stop-loss be placed?

This is the most important and most overlooked part. A stop-loss takes three forms:

1. **A mental stop:** "if the price hits this level, I'll close." In practice most traders wait when the price gets there.
2. **A stop inside the software:** the bot watches the price and sends a close order when it hits the stop. If the bot stops, the server loses its connection or the exchange API is briefly unavailable, there is no stop-loss.
3. **A stop placed on the exchange:** the stop order sits on the exchange itself and is executed even if your bot or computer is off.

Only the third option truly protects you. One step further matters even more: **checking that the order really is on the exchange**. Exchanges sometimes show orders with a delay or round the price to the nearest allowed tick. After every entry and every stop move, Avina reads the stop back from the exchange and compares the stored price with the requested one.

## How do you choose where to put the stop?

A good stop-loss sits where, if the price reaches it, **your reason for entering is no longer valid**. Common approaches:

- **Market structure:** just below the last valid low for a long, or just above the last high for a short.
- **Volatility (ATR):** the stop distance is a multiple of the average true range; wider in a volatile market, tighter in a calm one.

A stop that is too tight is hit by normal market noise. A stop that is too wide makes each loss large. The way to balance this is to adjust the **position size**, not to move the stop. We explain this in [risk management in futures](/en/blog/futures-risk-management/).

## Fixed or trailing stop?

A **fixed stop** stays in place from entry to exit. It is simple, but it lets a winning trade give all its profit back.

A **trailing stop** follows the price when it moves in your favor but never moves back. For example, once the trade has gained as much as it risked, the stop moves to the entry price and then trails behind the price.

One golden rule: **a stop-loss only ever moves in the direction that reduces risk**. Widening a stop to "give the trade room" is the most common way to turn a small loss into a big one.

## Common mistakes

- Trading without a stop-loss "because it's only for a few minutes".
- Widening the stop when the price approaches it.
- Placing the stop by how much you can bear to lose instead of by market structure.
- Trusting a stop that exists only inside the bot.
- Not checking that the exchange actually registered the order.

## Summary

A stop-loss is your account's insurance. Decide it before entering, place it on the exchange, verify it after placing it, and only move it in the direction that reduces risk. If you use a trading bot, first ask where it places the stop. To learn more about bots, read [what is a trading bot](/en/blog/what-is-a-trading-bot/).
