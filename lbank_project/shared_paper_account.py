"""One paper equity pool and entry-margin budget for the main bot, C3 and the PA sleeve.

Callers serialize entries/exits with engine.db.trade_lock. This does not route live orders.
"""
import math
import lbank_bot as bot

class SharedPaperAccount:
    def __init__(self, engine, store, config_reader, extra_sleeves=()):
        # store/config_reader = C3; extra_sleeves = further (store, config_reader) pairs with the same schema (PA)
        self.engine, self.store, self.config_reader = engine, store, config_reader
        self.sleeves = [(store, config_reader), *extra_sleeves]
        self.lock_path = engine.db.trade_lock

    def c3_component(self):
        """Realized + net unrealized P&L and margin of every sleeve (C3 and PA) on the shared account."""
        value = margin = 0.0
        for store, reader in self.sleeves:
            conf = reader()
            value += store.realized()
            for p in store.positions():
                price = self.engine.data.price(p['symbol'], cached=True)
                if not math.isfinite(price) or price <= 0:
                    raise ValueError('Invalid sleeve price: shared entries blocked')
                sign = 1 if p['side'] == 'long' else -1
                value += sign * (price-p['entry']) * p['qty'] - (price+p['entry']) * p['qty'] * conf['round_trip_fee']/2
                margin += p['qty'] * p['entry'] / p['isolated_leverage']
        return value, margin

    def equity(self):
        return max(0.0, self.engine.main_paper_equity() + self.c3_component()[0])

    def reserved_margin(self, exclude_main_symbol=None):
        main = sum(bot.position_margin(p) for p in self.engine.db.positions()
                   if p['symbol'] != exclude_main_symbol)
        return main + self.c3_component()[1]

    def available_margin(self, equity=None, exclude_main_symbol=None, leverage=5, fee_rate=.0012, margin_fraction=None):
        cfg = self.engine.config.read()
        if not cfg['bot_control']['dry_run_mode']:
            raise bot.LiveUnavailable(bot.LIVE_LIMITATION)
        eq = self.equity() if equity is None else equity
        fraction = cfg['risk_and_exit']['engaged_capital_pct'] if margin_fraction is None else margin_fraction
        free = max(0.0, eq*fraction-self.reserved_margin(exclude_main_symbol))
        # Reserve the new position's round-trip fee in the equity-based margin limit.
        return free / (1 + fraction*leverage*fee_rate)

    def snapshot(self):
        eq = self.equity()
        reserved = self.reserved_margin()
        allowed = eq*self.engine.config.read()['risk_and_exit']['engaged_capital_pct']
        return dict(equity_usd=eq, reserved_margin_usd=reserved, allowed_margin_usd=allowed,
                    free_margin_usd=max(0., allowed-reserved),
                    margin_pct=reserved/eq*100 if eq else None)
