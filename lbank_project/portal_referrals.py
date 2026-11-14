"""Referral codes and admin-defined referral programs.

A program decides what the invited customer gets (a discount on their first N
purchases) and what the inviter gets (account credit, a commission paid as
credit, or a discount coupon), optionally with tiers by the number of paying
friends. Rewards are granted only when a referred customer's order is approved,
so creating accounts alone never earns anything. Credits and coupons are
reserved by a pending order and released if it is cancelled or rejected.
"""
from decimal import Decimal, ROUND_FLOOR
import json
import re
import secrets
import time
import uuid

CODE = re.compile(r'^[A-Z0-9][A-Z0-9-]{2,23}$')
ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
PRODUCTS = ('autotrade', 'signals')
DEFAULT_SETTINGS = dict(enabled=False, attach_days=7, credit_max_percent=100)
DAY = 86400


class ReferralConflict(ValueError):
    pass


def clean_code(value):
    code = str(value or '').strip().upper()
    if not CODE.fullmatch(code):raise ValueError('Invalid referral code')
    return code


def cents(usd):
    return int((Decimal(str(usd)) * 100).to_integral_value(rounding=ROUND_FLOOR))


def mask(username):
    return username[:2] + '***' if username else ''


def _number(value, low, high, name):
    if isinstance(value, bool):raise ValueError('Invalid ' + name)
    try:number = Decimal(str(value))
    except Exception:raise ValueError('Invalid ' + name) from None
    if not number.is_finite() or number < low or number > high:raise ValueError('Invalid ' + name)
    return float(number.quantize(Decimal('0.01')))


def _integer(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:raise ValueError('Invalid ' + name)
    return value


def _products(value):
    if not isinstance(value, (list, tuple)) or not value or any(p not in PRODUCTS for p in value):
        raise ValueError('Choose at least one product')
    return [p for p in PRODUCTS if p in value]


def validate_config(raw):
    """Normalize a program definition; unknown keys are dropped."""
    if not isinstance(raw, dict):raise ValueError('Invalid program')
    ee, er = raw.get('referee') or {}, raw.get('referrer') or {}
    kind = ee.get('type', 'none')
    if kind not in ('none', 'percent', 'fixed'):raise ValueError('Invalid referee discount type')
    referee = dict(type=kind, value=_number(ee.get('value', 0), 0, 100 if kind == 'percent' else 100000, 'referee discount'),
                   purchases=_integer(ee.get('purchases', 1), 0, 100, 'number of discounted purchases'),
                   window_days=_integer(ee.get('window_days', 0), 0, 3650, 'discount window'),
                   min_order_usd=_number(ee.get('min_order_usd', 0), 0, 1000000, 'minimum order'),
                   products=_products(ee.get('products', list(PRODUCTS))))
    if kind != 'none' and referee['value'] <= 0:raise ValueError('The referee discount must be positive')
    kind = er.get('type', 'none')
    if kind not in ('none', 'credit', 'commission', 'coupon'):raise ValueError('Invalid referrer reward type')
    high = 100000 if kind == 'credit' else 100
    trigger = er.get('trigger', 'first')
    if trigger not in ('first', 'every'):raise ValueError('Invalid reward trigger')
    tiers = er.get('tiers') or []
    if not isinstance(tiers, list) or len(tiers) > 10:raise ValueError('At most 10 tiers')
    tiers = sorted((dict(referrals=_integer(t.get('referrals'), 2, 100000, 'tier size'),
                         value=_number(t.get('value'), 0.01, high, 'tier reward')) for t in tiers if isinstance(t, dict)),
                   key=lambda t: t['referrals'])
    if len({t['referrals'] for t in tiers}) != len(tiers):raise ValueError('Tier sizes must differ')
    referrer = dict(type=kind, value=_number(er.get('value', 0), 0, high, 'referrer reward'), trigger=trigger,
                    max_per_referee=_integer(er.get('max_per_referee', 0), 0, 1000, 'rewards per friend'),
                    hold_days=_integer(er.get('hold_days', 0), 0, 365, 'hold period'),
                    expiry_days=_integer(er.get('expiry_days', 0), 0, 3650, 'reward expiry'),
                    max_total_usd=_number(er.get('max_total_usd', 0), 0, 10000000, 'reward cap'),
                    min_order_usd=_number(er.get('min_order_usd', 0), 0, 1000000, 'minimum order'),
                    products=_products(er.get('products', list(PRODUCTS))), tiers=tiers if kind != 'none' else [])
    if kind != 'none' and referrer['value'] <= 0:raise ValueError('The referrer reward must be positive')
    return dict(referee=referee, referrer=referrer)


class Referrals:
    def __init__(self, store):
        self.store = store

    # ---------- settings and programs ----------
    def settings(self, db):
        row = db.execute("SELECT value FROM site_settings WHERE name='referrals'").fetchone()
        return DEFAULT_SETTINGS | (json.loads(row['value']) if row else {})

    def _program(self, db, pid):
        row = db.execute('SELECT * FROM referral_programs WHERE id=?', (pid,)).fetchone() if pid else None
        return dict(row, config=json.loads(row['config'])) if row else None

    @staticmethod
    def _live(program, now):
        return bool(program and program['active'] and (program['starts'] is None or program['starts'] <= now)
                    and (program['ends'] is None or now < program['ends']))

    def _default(self, db):
        row = db.execute('SELECT id FROM referral_programs WHERE is_default=1 ORDER BY updated DESC LIMIT 1').fetchone()
        return self._program(db, row['id']) if row else None

    def program_for(self, db, referral, now):
        """A code bound to a campaign uses that program; personal codes follow the default program."""
        program = self._program(db, referral['program_id']) if referral['program_id'] else self._default(db)
        return program if self._live(program, now) else None

    # ---------- codes and attribution ----------
    def _personal_code(self, db, user):
        row = db.execute('SELECT code FROM referral_codes WHERE user_id=? AND personal=1 AND active=1 '
                         'ORDER BY created DESC LIMIT 1', (user,)).fetchone()
        if row:return row['code']
        for _ in range(20):
            code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
            if not db.execute('SELECT 1 FROM referral_codes WHERE code=?', (code,)).fetchone():
                db.execute('INSERT INTO referral_codes(code,user_id,personal,created) VALUES(?,?,1,?)', (code, user, time.time()))
                return code
        raise ReferralConflict('Could not create a code; try again')

    def set_code(self, user, value):
        code = clean_code(value)
        if len(code) < 4:raise ValueError('Invalid referral code')
        with self.store.db() as db:
            self.store.database.begin_write(db, 'referral-codes')
            if db.execute('SELECT 1 FROM referral_codes WHERE code=?', (code,)).fetchone():
                raise ReferralConflict('This code is taken')
            if db.execute('SELECT COUNT(*) AS n FROM referral_codes WHERE user_id=? AND personal=1', (user,)).fetchone()['n'] >= 5:
                raise ReferralConflict('You can change your code at most 4 times')
            # Earlier codes keep working, so links already shared are never broken.
            db.execute('INSERT INTO referral_codes(code,user_id,personal,created) VALUES(?,?,1,?)', (code, user, time.time()))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'referral_code_changed', time.time()))
        return dict(code=code)

    def _usable_code(self, db, code, now):
        row = db.execute('SELECT c.*,u.disabled FROM referral_codes c LEFT JOIN users u ON u.id=c.user_id WHERE c.code=?',
                         (code,)).fetchone()
        if not row or not row['active'] or row['disabled']:raise ValueError('Invalid referral code')
        if row['program_id'] and not self._live(self._program(db, row['program_id']), now):raise ValueError('Invalid referral code')
        if row['max_uses'] and row['uses'] >= row['max_uses']:raise ReferralConflict('This code has reached its limit')
        return row

    def attach(self, db, user, value, now=None):
        """Record who invited `user`. Call inside the caller's write transaction."""
        now = time.time() if now is None else now
        if not self.settings(db)['enabled']:raise ReferralConflict('Referrals are not active')
        row = self._usable_code(db, clean_code(value), now)
        if row['user_id'] == user:raise ReferralConflict('You cannot use your own code')
        if db.execute('SELECT 1 FROM referrals WHERE user_id=?', (user,)).fetchone():raise ReferralConflict('A referral code is already applied')
        if row['user_id'] and db.execute('SELECT 1 FROM referrals WHERE user_id=? AND referrer_id=?', (row['user_id'], user)).fetchone():
            raise ReferralConflict('You cannot use the code of someone you invited')
        db.execute('INSERT INTO referrals(user_id,referrer_id,code,program_id,created) VALUES(?,?,?,?,?)',
                   (user, row['user_id'], row['code'], row['program_id'], now))
        db.execute('UPDATE referral_codes SET uses=uses+1 WHERE code=?', (row['code'],))
        db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'referral_attached', now))

    def attach_later(self, user, value, now=None):
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'billing:' + user)
            if not self._can_attach(db, user, now):raise ReferralConflict('A referral code can no longer be added to this account')
            self.attach(db, user, value, now)
        return self.account(user, now)

    def _can_attach(self, db, user, now):
        settings = self.settings(db)
        if not settings['enabled'] or db.execute('SELECT 1 FROM referrals WHERE user_id=?', (user,)).fetchone():return False
        if db.execute("SELECT 1 FROM license_orders WHERE user_id=? AND status='approved'", (user,)).fetchone():return False
        joined = db.execute("SELECT MIN(at) AS at FROM audit WHERE user_id=? AND event='registered'", (user,)).fetchone()['at']
        return joined is None or now < joined + settings['attach_days'] * DAY

    def lookup(self, value, now=None):
        """Public: tell a visitor what a code gives them, without revealing who owns it."""
        now = time.time() if now is None else now
        try:code = clean_code(value)
        except ValueError:return dict(valid=False)
        with self.store.db() as db:
            if not self.settings(db)['enabled']:return dict(valid=False)
            try:row = self._usable_code(db, code, now)
            except ValueError:return dict(valid=False)
            program = self.program_for(db, dict(program_id=row['program_id']), now)
        return dict(valid=True, code=code, offer=program['config']['referee'] if program else None)

    # ---------- pricing ----------
    def _available(self, db, user, kind, now):
        return db.execute("SELECT * FROM referral_rewards WHERE user_id=? AND kind=? AND status='active' AND remaining>0 "
                          'AND available_at<=? AND (expires IS NULL OR expires>?) ORDER BY expires IS NULL,expires,created',
                          (user, kind, now, now)).fetchall()

    def price(self, db, user, quote, now, reserve_order=None):
        """Apply the referee discount, then the best coupon, then credit. Returns (payable cents, lines)."""
        total = remaining = int(quote['price_cents'])
        lines = []
        settings = self.settings(db)
        if not settings['enabled'] or total <= 0:return total, lines
        referral = db.execute('SELECT * FROM referrals WHERE user_id=?', (user,)).fetchone()
        program = self.program_for(db, referral, now) if referral else None
        offer = program['config']['referee'] if program else None
        if (offer and offer['type'] != 'none' and quote['product'] in offer['products'] and total >= cents(offer['min_order_usd'])
                and (not offer['window_days'] or now < referral['created'] + offer['window_days'] * DAY)):
            used = db.execute("SELECT COUNT(*) AS n FROM license_orders WHERE user_id=? AND status='approved' AND referee_discount_cents>0",
                              (user,)).fetchone()['n']
            if not offer['purchases'] or used < offer['purchases']:
                off = total * Decimal(str(offer['value'])) / 100 if offer['type'] == 'percent' else Decimal(cents(offer['value']))
                off = min(remaining, int(off.to_integral_value(rounding=ROUND_FLOOR)))
                if off > 0:
                    remaining -= off
                    lines.append(dict(kind='referee', cents=off, percent=offer['value'] if offer['type'] == 'percent' else None))
        coupons = self._available(db, user, 'coupon', now)
        if coupons and remaining > 0:
            best = max(coupons, key=lambda r: r['value'])
            off = min(remaining, remaining * best['value'] // 10000)
            if off > 0:
                remaining -= off
                lines.append(dict(kind='coupon', cents=off, percent=best['value'] / 100))
                if reserve_order:
                    db.execute('UPDATE referral_rewards SET remaining=0 WHERE id=?', (best['id'],))
                    db.execute('INSERT INTO referral_credit_uses(order_id,reward_id,cents) VALUES(?,?,?)', (reserve_order, best['id'], off))
        limit = min(remaining, total * int(settings['credit_max_percent']) // 100)
        used = 0
        for row in self._available(db, user, 'credit', now):
            if used >= limit:break
            take = min(row['remaining'], limit - used)
            used += take
            if reserve_order:
                db.execute('UPDATE referral_rewards SET remaining=remaining-? WHERE id=?', (take, row['id']))
                db.execute('INSERT INTO referral_credit_uses(order_id,reward_id,cents) VALUES(?,?,?)', (reserve_order, row['id'], take))
        if used:
            remaining -= used
            lines.append(dict(kind='credit', cents=used, percent=None))
        return remaining, lines

    def release(self, db, order_id):
        """Give back the credit and coupon a cancelled or rejected order had reserved."""
        for use in db.execute('SELECT u.reward_id,u.cents,r.kind FROM referral_credit_uses u JOIN referral_rewards r ON r.id=u.reward_id '
                              'WHERE u.order_id=?', (order_id,)).fetchall():
            if use['kind'] == 'coupon':db.execute('UPDATE referral_rewards SET remaining=1 WHERE id=?', (use['reward_id'],))
            else:db.execute('UPDATE referral_rewards SET remaining=remaining+? WHERE id=?', (use['cents'], use['reward_id']))
        db.execute('DELETE FROM referral_credit_uses WHERE order_id=?', (order_id,))

    # ---------- rewards ----------
    def on_approved(self, db, order, now):
        """Grant the inviter's reward for an approved purchase, at most once per order."""
        referral = db.execute('SELECT * FROM referrals WHERE user_id=?', (order['user_id'],)).fetchone()
        if not referral or not referral['referrer_id'] or not self.settings(db)['enabled']:return None
        program = self.program_for(db, referral, now)
        rule = program['config']['referrer'] if program else None
        if not rule or rule['type'] == 'none' or order['product'] not in rule['products']:return None
        listed = order['list_price_cents'] if order['list_price_cents'] is not None else order['price_cents']
        if listed < cents(rule['min_order_usd']):return None
        referrer = referral['referrer_id']
        if db.execute('SELECT disabled FROM users WHERE id=?', (referrer,)).fetchone()['disabled']:return None
        if db.execute('SELECT 1 FROM referral_rewards WHERE order_id=?', (order['id'],)).fetchone():return None
        prior = db.execute("SELECT COUNT(*) AS n FROM referral_rewards WHERE user_id=? AND referee_id=? AND source='referral'",
                           (referrer, order['user_id'])).fetchone()['n']
        if rule['trigger'] == 'first' and prior:return None
        if rule['trigger'] == 'every' and rule['max_per_referee'] and prior >= rule['max_per_referee']:return None
        friends = db.execute("SELECT COUNT(DISTINCT referee_id) AS n FROM referral_rewards WHERE user_id=? AND source='referral'",
                             (referrer,)).fetchone()['n'] + (0 if prior else 1)
        value = rule['value']
        for tier in rule['tiers']:
            if friends >= tier['referrals']:value = tier['value']
        if rule['type'] == 'coupon':
            kind, amount = 'coupon', int(round(value * 100))
        else:
            kind = 'credit'
            amount = cents(value) if rule['type'] == 'credit' else int(order['price_cents'] * Decimal(str(value)) / 100)
            if rule['max_total_usd']:
                granted = db.execute("SELECT COALESCE(SUM(value),0) AS n FROM referral_rewards WHERE user_id=? AND kind='credit' "
                                     "AND source='referral' AND status='active'", (referrer,)).fetchone()['n']
                amount = min(amount, cents(rule['max_total_usd']) - int(granted))
        if amount <= 0:return None
        available = now + rule['hold_days'] * DAY
        rid = str(uuid.uuid4())
        db.execute('INSERT INTO referral_rewards(id,user_id,kind,value,remaining,source,referee_id,order_id,program_id,status,created,available_at,expires) '
                   "VALUES(?,?,?,?,?,'referral',?,?,?,'active',?,?,?)",
                   (rid, referrer, kind, amount, amount if kind == 'credit' else 1, order['user_id'], order['id'], program['id'], now, available,
                    available + rule['expiry_days'] * DAY if rule['expiry_days'] else None))
        from portal_telegram import notify
        if kind == 'credit':
            fa, en = f'{amount / 100:.2f} دلار اعتبار خرید', f'${amount / 100:.2f} of purchase credit'
        else:
            fa, en = f'کوپن {amount / 100:g}٪ تخفیف', f'a {amount / 100:g}% discount coupon'
        notify(db, referrer, f'🎁 یکی از دوستانی که دعوت کرده بودید خرید کرد و {fa} گرفتید.',
               f'🎁 A friend you invited made a purchase, and you earned {en}.')
        return rid

    def _rewards(self, db, user, now, limit=30):
        rows = db.execute('SELECT r.*,u.username AS referee FROM referral_rewards r LEFT JOIN users u ON u.id=r.referee_id '
                          'WHERE r.user_id=? ORDER BY r.created DESC LIMIT ?', (user, limit)).fetchall()
        return [dict(id=r['id'], kind=r['kind'], value=r['value'], remaining=r['remaining'], source=r['source'],
                     referee=mask(r['referee']), note=r['note'], created=r['created'], available_at=r['available_at'],
                     expires=r['expires'], state=self._state(r, now)) for r in rows]

    @staticmethod
    def _state(row, now):
        if row['status'] == 'void':return 'void'
        if row['remaining'] <= 0:return 'used'
        if row['expires'] is not None and row['expires'] <= now:return 'expired'
        return 'pending' if row['available_at'] > now else 'available'

    def account(self, user, now=None):
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'billing:' + user)
            settings = self.settings(db)
            if not settings['enabled']:return dict(enabled=False)
            code = self._personal_code(db, user)
            program = self._default(db)
            program = program if self._live(program, now) else None
            referral = db.execute('SELECT * FROM referrals WHERE user_id=?', (user,)).fetchone()
            own = self.program_for(db, referral, now) if referral else None
            used = db.execute("SELECT COUNT(*) AS n FROM license_orders WHERE user_id=? AND status='approved' AND referee_discount_cents>0",
                              (user,)).fetchone()['n']
            signups = db.execute('SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=?', (user,)).fetchone()['n']
            paying = db.execute("SELECT COUNT(DISTINCT r.user_id) AS n FROM referrals r JOIN license_orders o ON o.user_id=r.user_id "
                                "WHERE r.referrer_id=? AND o.status='approved'", (user,)).fetchone()['n']
            earned = db.execute("SELECT COALESCE(SUM(value),0) AS n FROM referral_rewards WHERE user_id=? AND kind='credit' AND status='active'",
                                (user,)).fetchone()['n']
            balance = sum(r['remaining'] for r in self._available(db, user, 'credit', now))
            pending = db.execute("SELECT COALESCE(SUM(remaining),0) AS n FROM referral_rewards WHERE user_id=? AND kind='credit' "
                                 "AND status='active' AND available_at>?", (user, now)).fetchone()['n']
            coupons = [dict(percent=r['value'] / 100, expires=r['expires']) for r in self._available(db, user, 'coupon', now)]
            rewards = self._rewards(db, user, now)
            can_attach = self._can_attach(db, user, now)
        return dict(enabled=True, code=code, program=program['config'] if program else None,
                    referred=dict(code=referral['code'], offer=own['config']['referee'] if own else None, used=used) if referral else None,
                    can_attach=can_attach, stats=dict(signups=signups, paying=paying, earned_cents=int(earned)),
                    balance_cents=int(balance), pending_cents=int(pending), coupons=coupons, rewards=rewards,
                    credit_max_percent=settings['credit_max_percent'])

    # ---------- administration ----------
    def _write(self, actor, function):
        from portal_audit import require_admin
        with self.store.db() as db:
            self.store.database.begin_write(db, 'admin-authority')
            require_admin(db, actor)
            return function(db)

    def save_settings(self, actor, values):
        from portal_audit import record
        settings = dict(enabled=bool(values.get('enabled')),
                        attach_days=_integer(values.get('attach_days', 7), 0, 365, 'days to add a code'),
                        credit_max_percent=_integer(values.get('credit_max_percent', 100), 0, 100, 'credit share'))

        def run(db):
            db.execute('INSERT INTO site_settings(name,value,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated=excluded.updated',
                       ('referrals', json.dumps(settings), time.time()))
            record(db, actor, 'referral_settings', 'referrals', settings)
            return settings
        return self._write(actor, run)

    def save_program(self, actor, pid, name, config, active, is_default, starts=None, ends=None):
        from portal_audit import record
        name = str(name or '').strip()
        if not 2 <= len(name) <= 80:raise ValueError('Program name must be 2 to 80 characters')
        config = validate_config(config)
        for value in (starts, ends):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):raise ValueError('Invalid date')
        if starts is not None and ends is not None and ends <= starts:raise ValueError('The end must be after the start')

        def run(db):
            now = time.time()
            if pid and not db.execute('SELECT 1 FROM referral_programs WHERE id=?', (pid,)).fetchone():raise LookupError('Program not found')
            target = pid or str(uuid.uuid4())
            if is_default:db.execute('UPDATE referral_programs SET is_default=0 WHERE id!=?', (target,))
            if pid:
                db.execute('UPDATE referral_programs SET name=?,config=?,active=?,is_default=?,starts=?,ends=?,updated=? WHERE id=?',
                           (name, json.dumps(config), int(bool(active)), int(bool(is_default)), starts, ends, now, pid))
            else:
                db.execute('INSERT INTO referral_programs(id,name,config,active,is_default,starts,ends,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                           (target, name, json.dumps(config), int(bool(active)), int(bool(is_default)), starts, ends, now, now))
            record(db, actor, 'referral_program_saved', target, dict(name=name, active=bool(active), default=bool(is_default)))
            return dict(self._program(db, target))
        return self._write(actor, run)

    def delete_program(self, actor, pid):
        from portal_audit import record

        def run(db):
            for table in ('referral_codes', 'referrals', 'referral_rewards'):
                if db.execute(f'SELECT 1 FROM {table} WHERE program_id=? LIMIT 1', (pid,)).fetchone():
                    raise ReferralConflict('This program is in use; deactivate it instead')
            if db.execute('DELETE FROM referral_programs WHERE id=?', (pid,)).rowcount != 1:raise LookupError('Program not found')
            record(db, actor, 'referral_program_deleted', pid)
            return dict(status='deleted')
        return self._write(actor, run)

    def save_code(self, actor, value, owner=None, program_id=None, label='', max_uses=0, active=True, create=True):
        from portal_audit import record
        code = clean_code(value)
        label = str(label or '').strip()[:80]
        max_uses = _integer(max_uses, 0, 1000000, 'usage limit')

        def run(db):
            user = None
            if owner:
                row = db.execute('SELECT id FROM users WHERE username=?', (str(owner).strip().lower(),)).fetchone()
                if not row:raise ValueError('Unknown username')
                user = row['id']
            if program_id and not db.execute('SELECT 1 FROM referral_programs WHERE id=?', (program_id,)).fetchone():
                raise ValueError('Unknown program')
            exists = db.execute('SELECT * FROM referral_codes WHERE code=?', (code,)).fetchone()
            if create:
                if exists:raise ReferralConflict('This code is taken')
                db.execute('INSERT INTO referral_codes(code,user_id,program_id,label,active,max_uses,personal,created) VALUES(?,?,?,?,?,?,0,?)',
                           (code, user, program_id or None, label, int(bool(active)), max_uses, time.time()))
            else:
                if not exists:raise LookupError('Code not found')
                db.execute('UPDATE referral_codes SET program_id=?,label=?,active=?,max_uses=? WHERE code=?',
                           (program_id or None, label, int(bool(active)), max_uses, code))
            record(db, actor, 'referral_code_saved', code, dict(owner=owner or None, program=program_id or None, active=bool(active)))
            return dict(code=code)
        return self._write(actor, run)

    def grant(self, actor, username, kind, value, note='', expiry_days=0):
        from portal_audit import record
        from portal_telegram import notify
        if kind not in ('credit', 'coupon'):raise ValueError('Unknown reward type')
        amount = cents(_number(value, 0.01, 100000 if kind == 'credit' else 100, 'amount'))
        expiry_days = _integer(expiry_days, 0, 3650, 'expiry')
        note = str(note or '').strip()[:200]

        def run(db):
            row = db.execute('SELECT id FROM users WHERE username=?', (str(username or '').strip().lower(),)).fetchone()
            if not row:raise ValueError('Unknown username')
            now, rid = time.time(), str(uuid.uuid4())
            db.execute('INSERT INTO referral_rewards(id,user_id,kind,value,remaining,source,note,status,created,available_at,expires) '
                       "VALUES(?,?,?,?,?,'admin',?,'active',?,?,?)",
                       (rid, row['id'], kind, amount, amount if kind == 'credit' else 1, note, now, now,
                        now + expiry_days * DAY if expiry_days else None))
            record(db, actor, 'referral_reward_granted', rid, dict(username=username, kind=kind, value=amount))
            if kind == 'credit':
                notify(db, row['id'], f'🎁 {amount / 100:.2f} دلار اعتبار خرید به حساب آوینای شما اضافه شد.',
                       f'🎁 ${amount / 100:.2f} of purchase credit was added to your Avina account.')
            else:
                notify(db, row['id'], f'🎁 یک کوپن {amount / 100:g}٪ تخفیف به حساب آوینای شما اضافه شد.',
                       f'🎁 A {amount / 100:g}% discount coupon was added to your Avina account.')
            return dict(id=rid)
        return self._write(actor, run)

    def void(self, actor, rid):
        from portal_audit import record

        def run(db):
            if db.execute("UPDATE referral_rewards SET status='void',remaining=0 WHERE id=? AND status='active'", (rid,)).rowcount != 1:
                raise LookupError('Reward not found')
            record(db, actor, 'referral_reward_voided', rid)
            return dict(status='void')
        return self._write(actor, run)

    def admin_overview(self, now=None):
        now = time.time() if now is None else now
        with self.store.db() as db:
            settings = self.settings(db)
            programs = []
            for row in db.execute('SELECT * FROM referral_programs ORDER BY is_default DESC,created DESC').fetchall():
                stats = db.execute('SELECT COUNT(*) AS n FROM referrals WHERE program_id=?' if not row['is_default'] else
                                   'SELECT COUNT(*) AS n FROM referrals WHERE program_id=? OR program_id IS NULL', (row['id'],)).fetchone()['n']
                rewards = db.execute("SELECT COUNT(*) AS n,COALESCE(SUM(CASE WHEN kind='credit' THEN value ELSE 0 END),0) AS credit "
                                     'FROM referral_rewards WHERE program_id=?', (row['id'],)).fetchone()
                programs.append(dict(id=row['id'], name=row['name'], config=json.loads(row['config']), active=bool(row['active']),
                                     is_default=bool(row['is_default']), starts=row['starts'], ends=row['ends'], live=self._live(row, now),
                                     referrals=stats, rewards=rewards['n'], credit_cents=int(rewards['credit'])))
            codes = [dict(r, active=bool(r['active']), personal=bool(r['personal'])) for r in db.execute(
                'SELECT c.code,c.label,c.active,c.max_uses,c.uses,c.personal,c.created,c.program_id,u.username AS owner,'
                '(SELECT COUNT(DISTINCT o.user_id) FROM referrals r JOIN license_orders o ON o.user_id=r.user_id '
                " WHERE r.code=c.code AND o.status='approved') AS paying "
                'FROM referral_codes c LEFT JOIN users u ON u.id=c.user_id WHERE c.personal=0 OR c.uses>0 '
                'ORDER BY c.personal,c.created DESC LIMIT 200').fetchall()]
            top = [dict(r) for r in db.execute(
                'SELECT u.username,COUNT(*) AS signups,'
                "(SELECT COUNT(DISTINCT o.user_id) FROM referrals x JOIN license_orders o ON o.user_id=x.user_id WHERE x.referrer_id=r.referrer_id AND o.status='approved') AS paying,"
                "(SELECT COALESCE(SUM(value),0) FROM referral_rewards w WHERE w.user_id=r.referrer_id AND w.kind='credit' AND w.status='active') AS credit_cents "
                'FROM referrals r JOIN users u ON u.id=r.referrer_id GROUP BY r.referrer_id,u.username ORDER BY signups DESC LIMIT 20').fetchall()]
            recent = [dict(id=r['id'], username=r['username'], kind=r['kind'], value=r['value'], source=r['source'], note=r['note'],
                           referee=r['referee'], created=r['created'], state=self._state(r, now)) for r in db.execute(
                'SELECT w.*,u.username,e.username AS referee FROM referral_rewards w JOIN users u ON u.id=w.user_id '
                'LEFT JOIN users e ON e.id=w.referee_id ORDER BY w.created DESC LIMIT 50').fetchall()]
            totals = dict(
                referrals=db.execute('SELECT COUNT(*) AS n FROM referrals').fetchone()['n'],
                paying=db.execute("SELECT COUNT(DISTINCT r.user_id) AS n FROM referrals r JOIN license_orders o ON o.user_id=r.user_id WHERE o.status='approved'").fetchone()['n'],
                discount_cents=int(db.execute("SELECT COALESCE(SUM(list_price_cents-price_cents),0) AS n FROM license_orders WHERE status='approved' AND list_price_cents IS NOT NULL").fetchone()['n']),
                credit_cents=int(db.execute("SELECT COALESCE(SUM(value),0) AS n FROM referral_rewards WHERE kind='credit' AND status='active'").fetchone()['n']),
                outstanding_cents=int(db.execute("SELECT COALESCE(SUM(remaining),0) AS n FROM referral_rewards WHERE kind='credit' AND status='active' AND (expires IS NULL OR expires>?)", (now,)).fetchone()['n']))
        for row in top:row['credit_cents'] = int(row['credit_cents'])
        return dict(settings=settings, programs=programs, codes=codes, top=top, rewards=recent, totals=totals)
