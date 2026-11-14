"""Stablecoin payments straight to the owner's wallet, confirmed on-chain without the customer entering a hash.

Each invoice asks for a unique amount (the order price plus a few thousandths of a dollar), so an incoming transfer
of exactly that amount to the owner's address identifies the order. A separate watcher process reads confirmed
USDT/USDC transfers on TRON (TRC20) and BNB Smart Chain (BEP20) from public endpoints and marks invoices paid. Nothing
here holds a private key: the site only reads public chain data. Settings (receiving addresses) are changed by an
administrator and audited.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
import signal
import threading
import time
import urllib.request
import uuid

from portal_audit import record, require_admin

MICRO = 1_000_000
TOKENS = {
    ('tron', 'USDT'): dict(contract='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', decimals=6, coin=195, label='USDT · TRC20 (TRON)',
                           trust='c195_tTR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', explorer='https://tronscan.org/#/transaction/'),
    ('bsc', 'USDT'): dict(contract='0x55d398326f99059fF775485246999027B3197955', decimals=18, coin=20000714,
                          label='USDT · BEP20 (BNB Smart Chain)', chain_id=56,
                          trust='c20000714_t0x55d398326f99059fF775485246999027B3197955', explorer='https://bscscan.com/tx/'),
    ('bsc', 'USDC'): dict(contract='0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', decimals=18, coin=20000714,
                          label='USDC · BEP20 (BNB Smart Chain)', chain_id=56,
                          trust='c20000714_t0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', explorer='https://bscscan.com/tx/'),
}
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
DEFAULTS = dict(tron_address='', bsc_address='', invoice_minutes='60', auto_approver='',
                bsc_rpc='https://bsc-rpc.publicnode.com', trongrid_url='https://api.trongrid.io')
LATE_WINDOW = 24 * 3600        # A payment for an expired invoice is still matched within this window.
BSC_CONFIRMATIONS = 15
BSC_MAX_RANGE = 2000          # Blocks per query; endpoints that refuse this get 50-block queries instead.
BSC_SMALL_RANGE = 50
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class PaymentConflict(ValueError):
    """The order cannot take a payment now (not pending, method disabled, no free unique amount)."""


# ---- Address checks ----------------------------------------------------------------------------------------------

def tron_address(value):
    """A valid TRON base58check address (version 0x41), or ValueError."""
    value = str(value or '').strip()
    if not re.fullmatch('[' + B58 + ']{34}', value) or not value.startswith('T'):raise ValueError('Invalid TRON address')
    number = 0
    for char in value:number = number * 58 + B58.index(char)
    raw = number.to_bytes(25, 'big')
    if raw[0] != 0x41 or hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] != raw[21:]:
        raise ValueError('Invalid TRON address checksum')
    return value


def bsc_address(value):
    """A 0x address; mixed case must carry a valid EIP-55 checksum. Stored as given, compared in lower case."""
    value = str(value or '').strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):raise ValueError('Invalid BNB Smart Chain address')
    body = value[2:]
    if body != body.lower() and body != body.upper():
        digest = keccak256(body.lower().encode()).hex()
        if any((c.upper() if int(d, 16) >= 8 else c.lower()) != c for c, d in zip(body, digest)):
            raise ValueError('Invalid BNB Smart Chain address checksum')
    return value


def keccak256(data):
    """Keccak-256 (Ethereum's hash, not SHA3-256), for EIP-55 checksums."""
    rate, state = 136, [0] * 25
    rot = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
    rc = [0x1, 0x8082, 0x800000000000808A, 0x8000000080008000, 0x808B, 0x80000001, 0x8000000080008081,
          0x8000000000008009, 0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B, 0x800000000000008B, 0x8000000000008089,
          0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x800A, 0x800000008000000A, 0x8000000080008081,
          0x8000000000008080, 0x80000001, 0x8000000080008008]
    mask = (1 << 64) - 1
    padded = bytearray(data) + b'\x01'
    while len(padded) % rate:padded += b'\x00'
    padded[-1] |= 0x80
    for offset in range(0, len(padded), rate):
        for i in range(rate // 8):state[i] ^= int.from_bytes(padded[offset + 8 * i:offset + 8 * i + 8], 'little')
        for constant in rc:
            c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
            d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & mask) for x in range(5)]
            state = [state[i] ^ d[i % 5] for i in range(25)]
            b = [0] * 25
            for x in range(5):
                for y in range(5):
                    value, r = state[x + 5 * y], rot[x][y]
                    b[y + 5 * ((2 * x + 3 * y) % 5)] = ((value << r) | (value >> (64 - r))) & mask if r else value
            state = [b[i] ^ ((~b[(i % 5 + 1) % 5 + 5 * (i // 5)]) & b[(i % 5 + 2) % 5 + 5 * (i // 5)]) for i in range(25)]
            state[0] ^= constant
    return b''.join(state[i].to_bytes(8, 'little') for i in range(4))


def amount_text(micro):
    """Exact decimal amount the customer sends, e.g. 49.137."""
    whole, fraction = divmod(int(micro), MICRO)
    return f'{whole}.{fraction:06d}'.rstrip('0').rstrip('.')


# ---- Settings, invoices and matching --------------------------------------------------------------------------------

class Payments:
    def __init__(self, store):self.store = store

    def settings(self, db=None):
        def read(db):
            rows = db.execute("SELECT name,value FROM site_settings WHERE name LIKE 'payment.%'").fetchall()
            return {**DEFAULTS, **{row['name'][8:]: row['value'] for row in rows}}
        if db is not None:return read(db)
        with self.store.db() as db:return read(db)

    def methods(self, settings=None):
        settings = settings or self.settings()
        out = []
        for (network, token), info in TOKENS.items():
            if settings.get(network + '_address'):
                out.append(dict(network=network, token=token, label=info['label']))
        return out

    def save_settings(self, actor, values):
        clean = {}
        for key in ('tron_address', 'bsc_address'):
            value = str(values.get(key) or '').strip()
            clean[key] = (tron_address if key == 'tron_address' else bsc_address)(value) if value else ''
        minutes = int(values.get('invoice_minutes') or 60)
        if not 15 <= minutes <= 1440:raise ValueError('Invoice lifetime must be 15..1440 minutes')
        clean['invoice_minutes'] = str(minutes)
        for key, default in (('bsc_rpc', DEFAULTS['bsc_rpc']), ('trongrid_url', DEFAULTS['trongrid_url'])):
            value = str(values.get(key) or default).strip()
            if not re.fullmatch(r'https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?', value):raise ValueError(key + ' must be https')
            clean[key] = value
        clean['auto_approver'] = actor if values.get('auto_approve_signals') else ''
        now = time.time()
        with self.store.db() as db:
            self.store.database.begin_write(db, 'payments')
            require_admin(db, actor)
            before = self.settings(db)
            for key, value in clean.items():
                db.execute('INSERT INTO site_settings(name,value,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET '
                           'value=excluded.value,updated=excluded.updated', ('payment.' + key, value, now))
            changed = {k: v for k, v in clean.items() if before.get(k) != v}
            record(db, actor, 'payment_settings_saved', 'payments',
                   {k: (v if k != 'auto_approver' else bool(v)) for k, v in changed.items()})
        return self.admin_settings()

    def admin_settings(self):
        settings = self.settings()
        with self.store.db() as db:
            gates = {row['name']: row['next_at'] for row in db.execute(
                "SELECT name,next_at FROM service_gate WHERE name LIKE 'payments:%'").fetchall()}
        return dict(tron_address=settings['tron_address'], bsc_address=settings['bsc_address'],
                    invoice_minutes=int(settings['invoice_minutes']), auto_approve_signals=bool(settings['auto_approver']),
                    bsc_rpc=settings['bsc_rpc'], trongrid_url=settings['trongrid_url'], methods=self.methods(settings),
                    watcher_seen=gates.get('payments:heartbeat'), checked={
                        'tron': gates.get('payments:ok:tron'), 'bsc': gates.get('payments:ok:bsc')})

    def _public(self, row):
        if not row:return None
        info = TOKENS[(row['network'], row['token'])]
        amount = amount_text(row['amount_micro'])
        send = (f'https://link.trustwallet.com/send?asset={info["trust"]}&address={row["address"]}&amount={amount}')
        return dict(id=row['id'], order_id=row['order_id'], network=row['network'], token=row['token'], label=info['label'],
                    address=row['address'], amount=amount, amount_micro=row['amount_micro'], status=row['status'],
                    created=row['created'], expires=row['expires'], paid_at=row['paid_at'], tx_ref=row['tx_ref'],
                    contract=info['contract'], decimals=info['decimals'], chain_id=info.get('chain_id'),
                    trust_link=send,
                    explorer_url=(info['explorer'] + row['tx_ref'].split(':')[1]) if row['tx_ref'] else None)

    def invoice(self, user, order_id):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM payment_invoices WHERE order_id=? AND user_id=? ORDER BY created DESC LIMIT 1',
                             (order_id, user)).fetchone()
        return self._public(row)

    def create_invoice(self, user, order_id, network, token, now=None):
        now = time.time() if now is None else now
        if (network, token) not in TOKENS:raise ValueError('Unknown payment method')
        with self.store.db() as db:
            self.store.database.begin_write(db, 'payments')
            settings = self.settings(db)
            address = settings.get(network + '_address')
            if not address:raise PaymentConflict('This payment method is not enabled')
            order = db.execute('SELECT * FROM license_orders WHERE id=? AND user_id=?', (order_id, user)).fetchone()
            if not order or order['status'] != 'pending':raise PaymentConflict('Only a pending order can be paid')
            if db.execute("SELECT 1 FROM payment_invoices WHERE order_id=? AND status='paid'", (order_id,)).fetchone():
                raise PaymentConflict('This order is already paid')
            current = db.execute("SELECT * FROM payment_invoices WHERE order_id=? AND status='open' AND expires>? "
                                 'ORDER BY created DESC LIMIT 1', (order_id, now)).fetchone()
            if current and (current['network'], current['token'], current['address']) == (network, token, address):
                return self._public(current)
            db.execute("UPDATE payment_invoices SET status='replaced' WHERE order_id=? AND status='open'", (order_id,))
            base = int(order['price_cents']) * 10_000
            # Unique among invoices that could still receive a payment for this token, so a transfer names one order.
            taken = {row['amount_micro'] for row in db.execute(
                "SELECT amount_micro FROM payment_invoices WHERE network=? AND token=? AND status IN ('open','expired','replaced') "
                'AND created>?', (network, token, now - LATE_WINDOW - 86400)).fetchall()}
            choices = [base + offset * 1000 for offset in range(1, 1000) if base + offset * 1000 not in taken]
            if not choices:raise PaymentConflict('No free payment amount; try again later')
            amount = choices[secrets.randbelow(len(choices))]
            invoice_id = str(uuid.uuid4())
            db.execute('INSERT INTO payment_invoices(id,order_id,user_id,network,token,address,amount_micro,status,created,expires) '
                       "VALUES(?,?,?,?,?,?,?,'open',?,?)",
                       (invoice_id, order_id, user, network, token, address, amount, now, now + int(settings['invoice_minutes']) * 60))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'payment_invoice_created:' + order_id, now))
            row = db.execute('SELECT * FROM payment_invoices WHERE id=?', (invoice_id,)).fetchone()
        return self._public(row)

    def record_transfer(self, network, token, tx_ref, sender, receiver, amount_micro, block_time, now=None):
        """Store one confirmed incoming transfer once and mark the matching invoice paid. Returns the invoice or None."""
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'payments')
            if db.execute('SELECT 1 FROM payment_transfers WHERE tx_ref=?', (tx_ref,)).fetchone():return None
            match = None
            if amount_micro is not None:
                match = db.execute(
                    "SELECT i.* FROM payment_invoices i JOIN license_orders o ON o.id=i.order_id WHERE i.network=? AND i.token=? "
                    "AND i.amount_micro=? AND lower(i.address)=lower(?) AND i.status IN ('open','expired','replaced') "
                    "AND o.status='pending' AND i.created<=? AND i.expires+?>=? ORDER BY i.created DESC LIMIT 1",
                    (network, token, amount_micro, receiver, block_time + 600, LATE_WINDOW, block_time)).fetchone()
            db.execute('INSERT INTO payment_transfers(tx_ref,network,token,from_address,to_address,amount_micro,block_time,seen,'
                       'invoice_id,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (tx_ref, network, token, sender, receiver, amount_micro if amount_micro is not None else -1, block_time,
                        now, match['id'] if match else None, 'matched' if match else 'unmatched'))
            if not match:return None
            db.execute("UPDATE payment_invoices SET status='paid',paid_at=?,tx_ref=? WHERE id=?", (now, tx_ref, match['id']))
            db.execute("UPDATE payment_invoices SET status='replaced' WHERE order_id=? AND id!=? AND status IN ('open','expired')",
                       (match['order_id'], match['id']))
            record(db, None, 'payment_received', match['order_id'], dict(tx_ref=tx_ref, network=network, token=token,
                                                                         amount=amount_text(amount_micro)))
            from portal_telegram import notify
            paid = amount_text(amount_micro) + ' ' + token
            notify(db, match['user_id'], f'✅ پرداخت {paid} شما روی شبکه تأیید شد. سفارش برای فعال‌سازی ثبت شد.',
                   f'✅ Your payment of {paid} is confirmed on-chain. Your order is queued for activation.')
            order = db.execute('SELECT product FROM license_orders WHERE id=?', (match['order_id'],)).fetchone()
            approver = self.settings(db)['auto_approver']
        if order['product'] == 'signals' and approver:
            # Signals need no exchange checks: queue the license for the signing service as the admin who enabled this.
            from portal_admin_store import AdminStore
            try:AdminStore(self.store).request_approval(approver, match['order_id'], tx_ref)
            except Exception:pass  # Stays paid and visible on the admin desk for a manual approval.
        return dict(match, status='paid', tx_ref=tx_ref)

    def expire(self, now=None):
        now = time.time() if now is None else now
        with self.store.db() as db:
            self.store.database.begin_write(db, 'payments')
            db.execute("UPDATE payment_invoices SET status='expired' WHERE status='open' AND expires<=?", (now,))
            # An order cancelled by the customer no longer takes payments.
            db.execute("UPDATE payment_invoices SET status='cancelled' WHERE status IN ('open','expired','replaced') AND order_id IN "
                       "(SELECT id FROM license_orders WHERE status!='pending')")

    def transfers(self, limit=50):
        with self.store.db() as db:
            rows = db.execute('SELECT t.*,i.order_id FROM payment_transfers t LEFT JOIN payment_invoices i ON i.id=t.invoice_id '
                              'ORDER BY t.seen DESC LIMIT ?', (limit,)).fetchall()
        out = []
        for row in rows:
            info = TOKENS.get((row['network'], row['token']), {})
            out.append(dict(row, amount=amount_text(row['amount_micro']) if row['amount_micro'] >= 0 else None,
                            explorer_url=info.get('explorer', '') + row['tx_ref'].split(':')[1]))
        return out

    def order_payments(self, order_ids):
        """Latest invoice per order, for the admin desk."""
        if not order_ids:return {}
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM payment_invoices WHERE order_id IN (' + ','.join('?' * len(order_ids)) + ') '
                              'ORDER BY created', tuple(order_ids)).fetchall()
        latest = {}
        for row in rows:
            if row['order_id'] not in latest or latest[row['order_id']]['status'] != 'paid':latest[row['order_id']] = row
        return {oid: self._public(row) for oid, row in latest.items()}


# ---- Chain readers ------------------------------------------------------------------------------------------------

def fetch_json(url, payload=None, headers=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json',
                                                              'User-Agent': 'avina-payments/1', **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(2_000_000))


class Watcher:
    """Polls confirmed incoming transfers to the configured addresses and records them."""

    def __init__(self, store, fetch=fetch_json):
        self.store = store
        self.payments = Payments(store)
        self.fetch = fetch

    def _gate(self, name, value=None):
        with self.store.db() as db:
            if value is None:
                row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (name,)).fetchone()
                return row['next_at'] if row else None
            db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',
                       (name, value))

    def bsc(self, settings):
        address = settings['bsc_address'].lower()
        rpc = lambda method, params: self._rpc(settings['bsc_rpc'], method, params)
        safe = int(rpc('eth_blockNumber', []), 16) - BSC_CONFIRMATIONS
        key = 'payments:bsc:' + address
        cursor = self._gate(key)
        cursor = int(cursor) if cursor is not None else safe - 1200
        if cursor >= safe:return 0
        end = min(safe, cursor + BSC_MAX_RANGE)
        topic = '0x' + '0' * 24 + address[2:]

        def logs(contract, start, stop):
            query = lambda a, b: rpc('eth_getLogs', [dict(fromBlock=hex(a), toBlock=hex(b), address=contract,
                                                          topics=[TRANSFER_TOPIC, None, topic])])
            try:return query(start, stop)
            except RuntimeError:
                out = []
                for a in range(start, stop + 1, BSC_SMALL_RANGE):out += query(a, min(stop, a + BSC_SMALL_RANGE - 1))
                return out

        found = 0
        for (network, token), info in TOKENS.items():
            if network != 'bsc':continue
            for log in logs(info['contract'], cursor + 1, end):
                if log.get('removed') or log['address'].lower() != info['contract'].lower():continue
                value = int(log['data'], 16)
                micro = value // 10 ** 12 if value % 10 ** 12 == 0 else None  # 18 decimals; exact amounts only.
                sender = '0x' + log['topics'][1][-40:]
                ref = f'bsc:{log["transactionHash"]}:{int(log["logIndex"], 16)}'
                self.payments.record_transfer(network, token, ref, sender, address, micro, time.time())
                found += 1
        self._gate(key, end)
        return found

    def _rpc(self, url, method, params):
        reply = self.fetch(url, dict(jsonrpc='2.0', id=1, method=method, params=params))
        if 'error' in reply:raise RuntimeError('RPC error')
        return reply['result']

    def tron(self, settings):
        address = settings['tron_address']
        info = TOKENS[('tron', 'USDT')]
        key = 'payments:tron:' + address
        cursor = self._gate(key)
        cursor = int(cursor) if cursor is not None else int((time.time() - 7200) * 1000)
        url = (f'{settings["trongrid_url"]}/v1/accounts/{address}/transactions/trc20?only_to=true&only_confirmed=true'
               f'&limit=200&order_by=block_timestamp,asc&contract_address={info["contract"]}&min_timestamp={cursor}')
        reply = self.fetch(url)
        found = 0
        for item in reply.get('data', []):
            if (item.get('type', 'Transfer') != 'Transfer' or item.get('to') != address
                    or item.get('token_info', {}).get('address') != info['contract']):continue
            value = int(item['value'])
            ref = 'tron:' + item['transaction_id']
            self.payments.record_transfer('tron', 'USDT', ref, item.get('from', ''), address, value, item['block_timestamp'] / 1000)
            cursor = max(cursor, int(item['block_timestamp']))
            found += 1
        self._gate(key, cursor)
        return found

    def once(self):
        settings = self.payments.settings()
        self.payments.expire()
        self._gate('payments:heartbeat', time.time())
        for network in ('tron', 'bsc'):
            if not settings[network + '_address']:continue
            try:
                getattr(self, network)(settings)
                self._gate('payments:ok:' + network, time.time())
            except Exception:
                print(f'Payment check for {network} failed; retrying.', flush=True)


def main():
    from pathlib import Path
    from portal_database import configured_target
    from portal_store import PortalStore
    key = Path(os.environ['PORTAL_KEY_FILE']).read_bytes().strip()
    store = PortalStore(configured_target(), key)
    interval = float(os.getenv('PAYMENT_CHECK_SECONDS', '20'))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):signal.signal(sig, lambda *_: stop.set())
    watcher = Watcher(store)
    try:
        while not stop.is_set():
            try:watcher.once()
            except Exception:print('Payment watcher could not reach the database; retrying.', flush=True)
            stop.wait(interval)
    finally:store.close()


if __name__ == '__main__':main()
