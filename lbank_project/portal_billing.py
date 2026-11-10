"""Owner-scoped subscription orders. Only an offline administrator can sign/activate.

Account identity, activation equity and external cashflows are verified by the
operator. Exchange balance snapshots alone cannot distinguish deposits from P&L.
No payment provider or live order routing is implied by an order request.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from capital_plans import (GRACE_SECONDS, VERSION, add_months, iso, money,
                           price_cents, prorated_cents)
from license_access import canonical, timestamp, verify_document


class BillingConflict(ValueError):
    pass


def sign(payload, private, previous=None):
    key = serialization.load_pem_private_key(Path(private).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Issuer key must be Ed25519')
    if previous:
        verify_document(previous, key.public_key().public_bytes(serialization.Encoding.PEM,
                                                               serialization.PublicFormat.SubjectPublicKeyInfo))
    return json.dumps(dict(payload=payload, signature=base64.b64encode(
        key.sign(canonical(payload))).decode('ascii')), ensure_ascii=False, indent=2)


def public_license(document, now=None):
    if not document:
        return dict(state='none', entries_allowed=False)
    now = time.time() if now is None else now
    p = json.loads(document)['payload']
    start, end = timestamp(p['not_before']), timestamp(p['expires_at'])
    state = 'not_yet_valid' if now < start else 'expired' if now >= end else 'active'
    funded = money(p['funded_capital_usd'])
    if state == 'active' and funded > p['cap_usd']:
        state = 'grace' if now < timestamp(p['grace_ends_at']) else 'capital_exceeded'
    return {k: p[k] for k in ('license_id', 'account_id', 'cap_usd', 'months', 'not_before',
                              'expires_at', 'capital_at_activation_usd', 'funded_capital_usd', 'grace_ends_at')} | dict(
        state=state, entries_allowed=state in ('active', 'grace'))


class Billing:
    def __init__(self, store):
        self.store = store

    def _document(self, db, user):
        row = db.execute('SELECT document FROM capital_licenses WHERE user_id=?', (user,)).fetchone()
        return row['document'] if row else None

    def snapshot(self, user, now=None):
        with self.store.db() as db:
            document = self._document(db, user)
            orders = db.execute('SELECT id,cap_usd,months,kind,price_cents,status,created,updated '
                                'FROM license_orders WHERE user_id=? ORDER BY created DESC LIMIT 30', (user,)).fetchall()
        return dict(license=public_license(document, now), orders=[dict(r) for r in orders],
                    payment_mode='manual_review', cashflow_monitoring='operator_verified')

    def _quote(self, db, user, cap, months, kind, now):
        cost = price_cents(cap, months)
        if kind not in ('subscription', 'upgrade'):
            raise ValueError('Unknown purchase kind')
        document = self._document(db, user)
        p = json.loads(document)['payload'] if document else None
        active = p is not None and timestamp(p['expires_at']) > now
        if kind == 'upgrade':
            if not active or months != p['months'] or cap <= p['cap_usd']:
                raise BillingConflict('Upgrade requires a higher tier with the current duration')
            start, end = timestamp(p['not_before']), timestamp(p['expires_at'])
            cost = prorated_cents(p['cap_usd'], cap, months, start, end, now)
        else:
            # No prepaid tier changes; renew after expiry or explicitly upgrade the current tier.
            if active:
                raise BillingConflict('An active license can only be upgraded; renew after expiry')
            start, end = now, add_months(now, months)
        return dict(cap_usd=cap, months=months, kind=kind, price_cents=cost,
                    currency='USD', price_version=VERSION, starts_at=iso(start), expires_at=iso(end))

    def quote(self, user, cap, months, kind='subscription', now=None):
        with self.store.db() as db:
            return self._quote(db, user, cap, months, kind, time.time() if now is None else now)

    def order(self, user, cap, months, kind, request_key, expected_price_cents, now=None):
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'billing:' + user)
            existing = db.execute('SELECT * FROM license_orders WHERE user_id=? AND request_key=?',
                                  (user, request_key)).fetchone()
            if existing:
                if ((existing['cap_usd'], existing['months'], existing['kind']) != (cap, months, kind)
                        or existing['price_cents'] > expected_price_cents
                        or (kind == 'subscription' and existing['price_cents'] != expected_price_cents)):
                    raise BillingConflict('Request key was already used for another order')
                return dict(id=existing['id'], status=existing['status'], already_exists=True)
            if db.execute("SELECT id FROM license_orders WHERE user_id=? AND status='pending'", (user,)).fetchone():
                raise BillingConflict('Cancel or finish your pending order first')
            quote = self._quote(db, user, cap, months, kind, now)
            # Proration can fall by cents between preview and submit; never charge more than accepted.
            if quote['price_cents'] > expected_price_cents or (kind == 'subscription' and quote['price_cents'] != expected_price_cents):
                raise BillingConflict('Price changed; request a fresh quote')
            oid = str(uuid.uuid4())
            db.execute('INSERT INTO license_orders(id,user_id,cap_usd,months,kind,price_cents,price_version,status,created,updated,request_key) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?)', (oid, user, cap, months, kind, quote['price_cents'], VERSION, 'pending', now, now, request_key))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'license_order_requested:' + oid, now))
            return dict(id=oid, status='pending', already_exists=False)

    def cancel(self, user, oid):
        with self.store.db() as db:
            self.store.database.begin_write(db, 'billing:' + user)
            if db.execute("UPDATE license_orders SET status='cancelled',updated=? WHERE id=? AND user_id=? AND status='pending'",
                          (time.time(), oid, user)).rowcount != 1:
                raise BillingConflict('Pending order not found')
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'license_order_cancelled:' + oid, time.time()))

    def document(self, user):
        with self.store.db() as db:
            document = self._document(db, user)
        if not document:
            raise BillingConflict('No issued license')
        return document

    def approve(self, oid, private, account_id, equity, payment_ref, now=None):
        """Call only after independently verifying payment, account UID and USD equity."""
        now = time.time() if now is None else now
        equity = money(equity, positive=True)
        if not re.fullmatch(r'[a-z0-9][a-z0-9:._-]{2,119}', account_id):
            raise ValueError('Use an exchange-prefixed account UID, e.g. binance:123456')
        if not re.fullmatch(r'[A-Za-z0-9:._-]{4,120}', payment_ref):
            raise ValueError('A unique verified payment reference is required')
        with self.store.db() as db:
            row = db.execute('SELECT user_id FROM license_orders WHERE id=?', (oid,)).fetchone()
            if not row:
                raise BillingConflict('Order not found')
            user = row['user_id']
            self.store.database.begin_write(db, 'billing:' + user)
            order = db.execute('SELECT * FROM license_orders WHERE id=?', (oid,)).fetchone()
            if order['status'] != 'pending':
                raise BillingConflict('Order is no longer pending')
            if order['kind'] == 'subscription' and equity > order['cap_usd']:
                raise BillingConflict('Verified equity exceeds the selected tier')
            old = self._document(db, user)
            if old and json.loads(old)['payload']['account_id'] != account_id:
                raise BillingConflict('License is bound to a different exchange account')
            quote = self._quote(db, user, order['cap_usd'], order['months'], order['kind'], now)
            if order['price_version'] != VERSION:
                raise BillingConflict('Price version changed; create a new order')
            if order['kind'] == 'subscription' and quote['price_cents'] != order['price_cents']:
                raise BillingConflict('Order price changed')
            username = db.execute('SELECT username FROM users WHERE id=?', (user,)).fetchone()['username']
            previous = json.loads(old)['payload'] if old else None
            upgrading = order['kind'] == 'upgrade'
            funded = money(previous['funded_capital_usd']) if upgrading else equity
            if funded > order['cap_usd']:
                raise BillingConflict('Funded capital exceeds the selected tier')
            payload = dict(schema=2, customer_id=username, license_id=str(uuid.uuid4()),
                           plan='capital-all-three', issued_at=iso(now), not_before=quote['starts_at'],
                           expires_at=quote['expires_at'], account_id=account_id,
                           cap_usd=order['cap_usd'], months=order['months'],
                           capital_at_activation_usd=str(funded), funded_capital_usd=str(funded),
                           grace_ends_at=None, price_version=VERSION,
                           bots=['main', 'c3', 'pa'])
            document = sign(payload, private, old)
            # A unique account_id also prevents accidental sharing across portal customers.
            db.execute('INSERT INTO capital_licenses(user_id,account_id,document,updated) VALUES(?,?,?,?) '
                       'ON CONFLICT(user_id) DO UPDATE SET document=excluded.document,updated=excluded.updated',
                       (user, account_id, document, now))
            db.execute("UPDATE license_orders SET status='approved',payment_ref=?,updated=? WHERE id=?",
                       (payment_ref, now, oid))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'license_order_approved:' + oid, now))
            return public_license(document, now)

    def cashflow(self, username, private, event_id, amount, now=None):
        """Record a VERIFIED external deposit/withdrawal, never trading P&L.

        The resulting license must be installed on the customer runtime. Repeated
        event IDs are idempotent; a deposit during an existing breach never resets grace.
        """
        now = time.time() if now is None else now
        if not re.fullmatch(r'[A-Za-z0-9:._-]{4,120}', event_id):
            raise ValueError('A stable external transfer ID is required')
        try:
            value = Decimal(str(amount))
            if not value.is_finite() or value == 0 or abs(value) > Decimal('1000000000'):
                raise ValueError('Invalid external cashflow')
            value = value.quantize(Decimal('.01'))
            if value == 0:
                raise ValueError('Cashflow must be at least one cent')
        except Exception:
            raise ValueError('Invalid external cashflow') from None
        with self.store.db() as db:
            owner = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if not owner:
                raise ValueError('Unknown customer')
            user = owner['id']
            self.store.database.begin_write(db, 'billing:' + user)
            old = db.execute('SELECT amount_usd FROM license_cashflows WHERE user_id=? AND event_id=?', (user, event_id)).fetchone()
            if old:
                if Decimal(old['amount_usd']) != value:
                    raise BillingConflict('Transfer ID already recorded with a different amount')
                return public_license(self._document(db, user), now)
            document = self._document(db, user)
            if not document:
                raise BillingConflict('No issued license')
            p = json.loads(document)['payload']
            funded = max(Decimal('0'), money(p['funded_capital_usd']) + value)
            money(funded)
            p['funded_capital_usd'] = str(funded)
            if funded > p['cap_usd']:
                p['grace_ends_at'] = p['grace_ends_at'] or iso(now + GRACE_SECONDS)
            else:
                p['grace_ends_at'] = None
            signed = sign(p, private, document)
            db.execute('UPDATE capital_licenses SET document=?,updated=? WHERE user_id=?', (signed, now, user))
            db.execute('INSERT INTO license_cashflows VALUES(?,?,?,?)', (user, event_id, str(value), now))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'license_cashflow:' + event_id, now))
            return public_license(signed, now)
