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
import product_pricing as pricing

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
        state=state, product=p.get('product','autotrade'),
        signals_allowed=start<=now<end,
        entries_allowed=state in ('active','grace') and p.get('product','autotrade')=='autotrade')


class Billing:
    def __init__(self, store):
        self.store = store

    def _document(self, db, user):
        row = db.execute('SELECT document FROM capital_licenses WHERE user_id=?', (user,)).fetchone()
        return row['document'] if row else None

    def snapshot(self, user, now=None):
        with self.store.db() as db:
            document = self._document(db, user)
            orders = db.execute('SELECT id,cap_usd,months,kind,product,price_cents,status,created,updated '
                                'FROM license_orders WHERE user_id=? ORDER BY created DESC LIMIT 30', (user,)).fetchall()
        return dict(license=public_license(document, now), orders=[dict(r) for r in orders],
                    payment_mode='manual_review', cashflow_monitoring='operator_verified')

    def _quote(self, db, user, cap, months, kind, now, product='autotrade'):
        price_cents(cap,months)  # Validate the supported capital tier and term, never the legacy price.
        config=pricing.settings(db,product)
        try:cost=pricing.priced(config,cap,months)
        except ValueError as exc:raise BillingConflict(str(exc)) from None
        if kind not in ('subscription','upgrade'):raise ValueError('Unknown purchase kind')
        document=self._document(db,user)
        p=json.loads(document)['payload'] if document else None
        active=p is not None and timestamp(p['expires_at'])>now
        if kind=='upgrade':
            if not active or months!=p['months']:raise BillingConflict('No active license with that duration')
            previous_product=p.get('product','autotrade')
            if previous_product=='autotrade' and product=='signals':
                raise BillingConflict('Switch to signals after the current license expires')
            if product==previous_product and cap<=p['cap_usd']:raise BillingConflict('Choose a higher capital tier')
            if cap<p['cap_usd']:raise BillingConflict('An upgrade cannot reduce capital tier')
            # Freeze the paid full-period price on the signed license; tariff changes
            # must not retroactively change the customer's upgrade credit.
            old_price=p.get('full_price_cents',price_cents(p['cap_usd'],p['months']))
            difference=cost-old_price
            start,end=timestamp(p['not_before']),timestamp(p['expires_at'])
            if difference<=0 or not start<=now<end:raise BillingConflict('Upgrade price must exceed the current plan')
            cost=int((Decimal(difference)*Decimal(str(end-now))/Decimal(str(end-start))).to_integral_value(rounding='ROUND_CEILING'))
        else:
            if active:raise BillingConflict('Upgrade the active license or renew after expiry')
            start,end=now,add_months(now,months)
        return dict(cap_usd=cap,months=months,kind=kind,product=product,price_cents=cost,
                    full_price_cents=pricing.priced(config,cap,months),currency='USD',
                    price_version=config['version'],starts_at=iso(start),expires_at=iso(end))

    def quote(self,user,cap,months,kind='subscription',now=None,product='autotrade'):
        with self.store.db() as db:
            return self._quote(db,user,cap,months,kind,time.time() if now is None else now,product)

    def order(self, user, cap, months, kind, request_key, expected_price_cents, now=None, product='autotrade'):
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'billing:' + user)
            existing = db.execute('SELECT * FROM license_orders WHERE user_id=? AND request_key=?',
                                  (user, request_key)).fetchone()
            if existing:
                if ((existing['cap_usd'], existing['months'], existing['kind'],existing['product']) != (cap, months, kind,product)
                        or existing['price_cents'] > expected_price_cents
                        or (kind == 'subscription' and existing['price_cents'] != expected_price_cents)):
                    raise BillingConflict('Request key was already used for another order')
                return dict(id=existing['id'], status=existing['status'], already_exists=True)
            if db.execute("SELECT id FROM license_orders WHERE user_id=? AND status='pending'", (user,)).fetchone():
                raise BillingConflict('Cancel or finish your pending order first')
            quote = self._quote(db, user, cap, months, kind, now,product)
            # Proration can fall by cents between preview and submit; never charge more than accepted.
            if quote['price_cents'] > expected_price_cents or (kind == 'subscription' and quote['price_cents'] != expected_price_cents):
                raise BillingConflict('Price changed; request a fresh quote')
            oid = str(uuid.uuid4())
            db.execute('INSERT INTO license_orders(id,user_id,cap_usd,months,kind,price_cents,price_version,status,created,updated,request_key,product) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (oid, user, cap, months, kind, quote['price_cents'], quote['price_version'], 'pending', now, now, request_key,product))
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

    def approve(self, oid, private, account_id=None, equity=None, payment_ref=None, now=None,approval_job=None):
        """Call only after independently verifying payment, account UID and USD equity."""
        # Signed ISO timestamps have microsecond precision. Compare the approval
        # result against the same canonical clock, never an earlier float fraction.
        now = timestamp(iso(time.time() if now is None else now))
        if not isinstance(payment_ref,str) or not re.fullmatch(r'[A-Za-z0-9:._-]{4,120}', payment_ref):
            raise ValueError('A unique verified payment reference is required')
        with self.store.db() as db:
            row = db.execute('SELECT user_id FROM license_orders WHERE id=?', (oid,)).fetchone()
            if not row:
                raise BillingConflict('Order not found')
            user = row['user_id']
            self.store.database.begin_write(db,'admin-authority' if approval_job else 'billing:'+user)
            if approval_job and self.store.database.postgres:self.store.database.begin_write(db,'billing:'+user)
            if approval_job:
                from portal_audit import require_admin
                job=db.execute('SELECT * FROM license_approvals WHERE id=? AND order_id=?',(approval_job['id'],oid)).fetchone()
                clock=self.store.database.clock(db)
                if not job or job['state']!='running' or job['lease_token']!=approval_job['lease_token'] or job['lease_until']<=clock:
                    raise BillingConflict('Signing lease is no longer valid')
                require_admin(db,job['requested_by'])
            owner=db.execute('SELECT disabled FROM users WHERE id=?',(user,)).fetchone()
            if owner['disabled']:raise BillingConflict('Customer is disabled')
            order = db.execute('SELECT * FROM license_orders WHERE id=?', (oid,)).fetchone()
            if order['status'] != 'pending':
                raise BillingConflict('Order is no longer pending')
            username=db.execute('SELECT username FROM users WHERE id=?',(user,)).fetchone()['username']
            product=order['product']
            if product=='signals':
                account_id='signals:'+username
                equity=money(order['cap_usd'],positive=True)
            else:
                if not isinstance(account_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9:._-]{2,119}',account_id):
                    raise ValueError('A verified exchange-prefixed account UID is required')
                equity=money(equity,positive=True)

            if order['kind'] == 'subscription' and equity > order['cap_usd']:
                raise BillingConflict('Verified equity exceeds the selected tier')
            old = self._document(db, user)
            if old and product=='autotrade' and json.loads(old)['payload'].get('product','autotrade')=='autotrade' and json.loads(old)['payload']['account_id'] != account_id:
                raise BillingConflict('License is bound to a different exchange account')
            quote = self._quote(db, user, order['cap_usd'], order['months'], order['kind'], now,product)
            if order['price_version'] != quote['price_version']:
                raise BillingConflict('Price version changed; create a new order')
            if order['kind'] == 'subscription' and quote['price_cents'] != order['price_cents']:
                raise BillingConflict('Order price changed')
            username = db.execute('SELECT username FROM users WHERE id=?', (user,)).fetchone()['username']
            previous = json.loads(old)['payload'] if old else None
            upgrading = order['kind'] == 'upgrade'
            funded = money(previous['funded_capital_usd']) if upgrading and previous.get('product','autotrade')==product else equity
            if product=='autotrade' and previous and previous.get('product')=='signals' and equity>order['cap_usd']:
                raise BillingConflict('Verified equity exceeds the selected tier')
            if funded > order['cap_usd']:
                raise BillingConflict('Funded capital exceeds the selected tier')
            payload = dict(schema=2, customer_id=username, license_id=str(uuid.uuid4()),
                           plan='capital-all-three', product=product,full_price_cents=quote['full_price_cents'],issued_at=iso(now), not_before=quote['starts_at'],
                           expires_at=quote['expires_at'], account_id=account_id,
                           cap_usd=order['cap_usd'], months=order['months'],
                           capital_at_activation_usd=str(funded), funded_capital_usd=str(funded),
                           grace_ends_at=None, price_version=quote['price_version'],
                           bots=['main', 'c3', 'pa'])
            document = sign(payload, private, old)
            # A unique account_id also prevents accidental sharing across portal customers.
            db.execute('INSERT INTO capital_licenses(user_id,account_id,document,updated) VALUES(?,?,?,?) '
                       'ON CONFLICT(user_id) DO UPDATE SET account_id=excluded.account_id,document=excluded.document,updated=excluded.updated',
                       (user, account_id, document, now))
            db.execute("UPDATE license_orders SET status='approved',payment_ref=?,updated=? WHERE id=?",
                       (payment_ref, now, oid))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'license_order_approved:' + oid, now))
            db.execute("UPDATE license_approvals SET state='completed',lease_token=NULL,lease_until=0,error_code=NULL,updated=? WHERE order_id=?",(now,oid))
            from portal_audit import record
            record(db,job['requested_by'] if approval_job else None,'license_issued',oid,dict(license_id=payload['license_id']))
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
            if p.get('product','autotrade')!='autotrade':raise BillingConflict('Signal subscriptions do not track exchange deposits')
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
