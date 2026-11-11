"""Entry-only live risk limits for the Live mirror (from the reviewed 2026-11-08 server deployment, now in the repo).

Fractions use 0.01 for 1%. They cannot guarantee a loss ceiling through gaps, fees or liquidation. Daily loss is measured
from the UTC start-of-day observed account equity; deposits and withdrawals require operator review. Existing exits are
never blocked. A limit that is reached (RiskLimit) skips that entry; missing or invalid data (ExchangeError) blocks it.
"""
from datetime import datetime, timezone
import math

from exchanges import ExchangeError

KEYS = ('risk_per_trade_pct', 'max_total_open_risk_pct', 'max_daily_loss_pct',
        'max_drawdown_pct', 'max_margin_usage_pct')
DEFAULTS = dict(risk_per_trade_pct=0.03, max_total_open_risk_pct=0.10, max_daily_loss_pct=0.05,
                max_drawdown_pct=0.20, max_margin_usage_pct=0.60)


class RiskLimit(ExchangeError):
    """A configured live risk limit is reached: skip the entry (not an exchange or data error)."""


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExchangeError('Live risk value missing or invalid')
    if not math.isfinite(value) or value <= 0:
        raise ExchangeError('Live risk value missing or invalid')
    return float(value)


def policy(config):
    values = {key: positive(config.get(key)) for key in KEYS}
    if any(value > 1 for value in values.values()):
        raise ExchangeError('Live risk fractions must be in (0, 1]')
    if values['risk_per_trade_pct'] > values['max_total_open_risk_pct']:
        raise ExchangeError('Per-trade risk exceeds total risk limit')
    return values


def entry_budget(config, state, exchange, symbol, side, qty, price, stop, now, save):
    limits = policy(config)
    equity = positive(exchange.equity())
    available = exchange.available_balance()
    if isinstance(available, bool) or not isinstance(available, (int, float)) or not math.isfinite(available) or available < 0:
        raise ExchangeError('Live available balance missing or invalid')
    for value in (qty, price, stop):
        positive(value)
    if side not in ('long', 'short') or not (
            stop < price if side == 'long' else stop > price):
        raise ExchangeError('Invalid live risk stop direction')
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    ledger = state.get('risk_ledger')
    if ledger is None:
        ledger = dict(day=day, day_equity=equity, peak_equity=equity)
    else:
        ledger = dict(ledger)
        positive(ledger.get('day_equity'))
        positive(ledger.get('peak_equity'))
        old_day = ledger.get('day')
        if not isinstance(old_day, str) or old_day > day:
            raise ExchangeError('Live risk ledger date invalid or clock moved backwards')
        if old_day != day:
            ledger.update(day=day, day_equity=equity)
    ledger['peak_equity'] = max(equity, ledger['peak_equity'])
    state['risk_ledger'] = ledger
    save()  # Baselines survive restart and rejected entries.
    if equity <= ledger['day_equity'] * (1 - limits['max_daily_loss_pct']):
        raise RiskLimit('Live daily loss limit reached; entries blocked until the next UTC day')
    if equity <= ledger['peak_equity'] * (1 - limits['max_drawdown_pct']):
        raise RiskLimit('Live drawdown limit reached; entries blocked')
    positions = exchange.positions()
    managed = state['managed']
    if set(positions) - set(managed):
        raise RiskLimit('Positions not opened by the mirror are open on the account; their risk cannot be verified')
    total_risk = 0.0
    symbol_risk = 0.0
    for name, pos in positions.items():
        owner = managed[name]
        if owner.get('side') != pos.side:
            raise ExchangeError('Live risk ownership direction mismatch')
        px = positive(exchange.price(name))
        sl = positive(owner.get('stop'))
        if pos.side not in ('long', 'short') or not (
                sl < px if pos.side == 'long' else sl > px):
            raise ExchangeError('Existing live stop is crossed or invalid')
        exchange.verify_stop(pos, sl)
        risk = positive(pos.qty) * abs(px - sl)
        total_risk += risk
        if name == symbol:
            symbol_risk = risk
    # Budget uses current price-to-stop loss, plus 0.2% notional for fees/drift.
    new_risk = qty * (abs(price - stop) + price * .002)
    if symbol_risk + new_risk > equity * limits['risk_per_trade_pct']:
        raise RiskLimit('Live per-trade risk limit exceeded')
    if total_risk + new_risk > equity * limits['max_total_open_risk_pct']:
        raise RiskLimit('Live total open risk limit exceeded')
    margin = qty * price / positive(config.get('leverage')) * 1.05
    used = max(0.0, equity - available)
    if used + margin > equity * limits['max_margin_usage_pct']:
        raise RiskLimit('Live margin usage limit exceeded')
