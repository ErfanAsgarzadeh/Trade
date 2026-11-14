---
title: Creating a Safe API Key for a Trading Bot, Without Withdrawal Access
description: What an API key is, which permissions to give a trading bot and which never to give, why IP restriction matters, and what to do if a key leaks.
date: 2026-11-13
keywords: API key, exchange API, trading bot security, withdrawal permission, IP whitelist
---
For a trading bot to trade in your exchange account, it needs an **API key**. An API key works like an access card: the exchange gives whoever holds it exactly the permissions you chose when you created it. So your account's security depends above all on which doors that card opens.

## What is an API key made of?

Most exchanges give you two strings:

- **API key:** the public identifier of the key.
- **Secret key:** the private secret that signs requests. It is usually shown only once.

Anyone holding both can talk to the exchange on your behalf, within the permissions you enabled for the key.

## Which permissions are needed and which are not?

A trading bot only needs:

- **Read account data:** balance, positions and open orders.
- **Trade:** open and close positions and place stop-loss orders.

It never needs:

- **Withdraw:** no trading bot needs withdrawals to trade. A key without withdrawal permission cannot move money out of your account even if it leaks.
- **Transfers between accounts or creating sub-accounts:** these are not needed for trading either.

If a service asks for a key with withdrawal permission, or asks you to deposit money into its own account, treat that as a serious warning sign.

## IP restriction: a second layer of security

Most exchanges let a key work only from specific IP addresses. If the bot runs on a server with a fixed IP, restrict the key to that IP. Then even if the key and secret leak, they will not work from anywhere else.

## Tips for keeping keys safe

1. **Create a separate key for each service.** If you stop using a service, you delete only its key.
2. **Never send keys by messenger, email or screenshot.** Enter them only in the service's own secure form.
3. **Do not store the secret where others can reach it.** If you do not need it, do not store it at all; you can always create a new key.
4. **Turn on two-factor authentication (2FA) on your exchange account.** Creating and deleting keys should require 2FA.
5. **Delete old keys regularly.**

## If you think a key has leaked

- Delete or disable the key in the exchange panel immediately.
- Check your open positions and orders.
- Change your exchange password and review signed-in devices.
- Create a new key with limited permissions and an IP restriction.

## What does Avina do with your API key?

Avina is **non-custodial**: you never deposit with Avina and your capital always stays in your own exchange account. The API key must be created without withdrawal permission, and Avina uses it only to read the account, open and close positions and place stop-losses. The key is stored encrypted.

## Summary

A safe API key means the least access needed: read and trade, no withdrawals, and restricted to one IP where possible. With these settings, the worst case is unwanted trades, which stop the moment you delete the key, rather than lost capital. Next, read [stop-losses in futures trading](/en/blog/futures-stop-loss/).
