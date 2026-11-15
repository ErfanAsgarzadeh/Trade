"""Health checks for the owner. `checks()` reads the heartbeats and queues the workers leave in the database; `run()` turns
changes into ONE Telegram message per incident to every linked administrator, and one more when it clears.

Gate rows used (service_gate): payments:heartbeat, payments:ok:<network>, payments:verify_failures / payments:verify_failed_at
(written by portal_payments), license-issuer:heartbeat (portal_issuer), and alert:<key> (this module: when the incident began).
The account worker records no heartbeat, so its queue is judged from account_jobs: a job due for many minutes means nothing claims it.
A watchdog inside the telegram-worker cannot see that the whole server is down; use an external check on /healthz for that."""
import time

HEARTBEAT_STALE = 300       # 5 minutes without a heartbeat
NETWORK_STALE = 900         # 15 minutes without a successful chain read
APPROVAL_SLOW = 600         # 10 minutes in the queue or running
QUEUE_STALE = 600
UNMATCHED_WINDOW = 30 * 86400
NETWORKS = (('tron', 'TRON'), ('bsc', 'BSC'))

# key -> (Persian, English) headline of the incident; the detail line is appended in English (numbers and gate names only).
TITLES = {
    'payment_worker': ('کارگر پرداخت پاسخ نمی‌دهد', 'The payment worker is not responding'),
    'payment_check_tron': ('خواندن پرداخت‌های TRON ناموفق است', 'Reading TRON payments is failing'),
    'payment_check_bsc': ('خواندن پرداخت‌های BSC ناموفق است', 'Reading BSC payments is failing'),
    'payment_verify': ('تأیید پرداخت با منبع دوم ناموفق است', 'Second-source payment verification is failing'),
    'issuer_heartbeat': ('سرویس صدور لایسنس پاسخ نمی‌دهد', 'The license issuer is not responding'),
    'approval_stuck': ('تأیید لایسنس بیش از ۱۰ دقیقه مانده است', 'A license approval has been waiting more than 10 minutes'),
    'approval_failed': ('صدور لایسنس ناموفق بوده است', 'A license approval failed'),
    'unmatched_transfer': ('واریز بدون فاکتور رسیده است', 'An incoming transfer matched no invoice'),
    'account_queue': ('صف خواندن حساب‌ها گیر کرده است', 'The account read queue is stalled'),
}


def _gates(db, *prefixes):
    """service_gate rows whose name starts with one of the prefixes (bound parameters: the SQL text holds no percent sign)."""
    where = ' OR '.join('name LIKE ?' for _ in prefixes)
    return {row['name']: row['next_at'] for row in db.execute('SELECT name,next_at FROM service_gate WHERE ' + where,
                                                              tuple(p + '%' for p in prefixes)).fetchall()}


def _age(now, then):
    return 'never seen' if then is None else f'{int((now - then) // 60)} min ago'


def checks(store, now=None):
    """[{key, ok, detail, since, fingerprint}] where `since` is when the problem started (None when it cannot be told)."""
    with store.db() as db:
        now = store.database.clock(db) if now is None else now
        gates = _gates(db, 'payments:', 'license-issuer:', 'alert:')
        settings = {row['name']: (row['value'], row['updated']) for row in db.execute(
            "SELECT name,value,updated FROM site_settings WHERE name IN ('payment.tron_address','payment.bsc_address')").fetchall()}
        queued = db.execute("SELECT COUNT(*) AS n FROM license_approvals WHERE state='queued'").fetchone()['n']
        slow = db.execute("SELECT MIN(created) AS at, COUNT(*) AS n FROM license_approvals WHERE state IN ('queued','running') AND created<?",
                          (now - APPROVAL_SLOW,)).fetchone()
        failed = db.execute("SELECT MIN(a.updated) AS at, COUNT(*) AS n FROM license_approvals a JOIN license_orders o ON o.id=a.order_id "
                            "WHERE a.state='failed' AND o.status='pending'").fetchone()
        unmatched = db.execute('SELECT MIN(seen) AS first, MAX(seen) AS last, COUNT(*) AS n FROM payment_transfers '
                               "WHERE status='unmatched' AND seen>?", (now - UNMATCHED_WINDOW,)).fetchone()
        stalled = db.execute("SELECT MIN(not_before) AS at, COUNT(*) AS n FROM account_jobs WHERE state='queued' AND not_before<?",
                             (now - QUEUE_STALE,)).fetchone()
    out = []

    def add(key, ok, detail, since=None, fingerprint=None):
        out.append(dict(key=key, ok=bool(ok), detail=detail, since=None if ok else since, fingerprint=fingerprint))
    configured = {n: bool(settings.get(f'payment.{n}_address', ('',))[0]) for n, _ in NETWORKS}
    beat = gates.get('payments:heartbeat')
    if not any(configured.values()):
        add('payment_worker', True, 'no receiving address configured')
    else:
        stale = beat is None or now - beat > HEARTBEAT_STALE
        add('payment_worker', not stale, 'last heartbeat ' + _age(now, beat), beat)
    for network, label in NETWORKS:
        key = 'payment_check_' + network
        if not configured[network]:
            add(key, True, f'{label} not configured');continue
        last, changed = gates.get(f'payments:ok:{network}'), settings[f'payment.{network}_address'][1]
        # A freshly configured address gets a grace period before "never read" counts as a failure.
        stale = (now - last > NETWORK_STALE) if last is not None else (now - changed > NETWORK_STALE)
        add(key, not stale, f'last successful read {_age(now, last)}', last if last is not None else changed)
    failures = int(gates.get('payments:verify_failures') or 0)
    add('payment_verify', failures == 0, f'{failures} consecutive verification failures' if failures else 'second source agrees',
        gates.get('payments:verify_failed_at'))
    issuer = gates.get('license-issuer:heartbeat')
    stale = queued > 0 and (issuer is None or now - issuer > HEARTBEAT_STALE)
    add('issuer_heartbeat', not stale, f'{queued} approval(s) queued, last issuer heartbeat {_age(now, issuer)}', issuer)
    add('approval_stuck', not slow['n'], f"{slow['n']} approval(s) queued or running for over 10 minutes" if slow['n'] else 'no approval is slow', slow['at'])
    add('approval_failed', not failed['n'], f"{failed['n']} failed approval(s) on pending orders" if failed['n'] else 'no failed approval', failed['at'])
    add('unmatched_transfer', not unmatched['n'], f"{unmatched['n']} unmatched incoming transfer(s)" if unmatched['n'] else 'every transfer is matched',
        unmatched['first'], unmatched['last'])
    add('account_queue', not stalled['n'], f"{stalled['n']} account job(s) waiting over 10 minutes" if stalled['n'] else 'queue is moving', stalled['at'])
    return out


def health(store, now=None):
    """What GET /api/admin/health returns: [{key, ok, detail, since}]. `since` prefers the time the alert began."""
    with store.db() as db:
        began = {name[6:]: at for name, at in _gates(db, 'alert:').items() if not name.endswith(':fp')}
    return [dict(key=c['key'], ok=c['ok'], detail=c['detail'], since=None if c['ok'] else began.get(c['key'], c['since'])) for c in checks(store, now)]


def run(store, now=None):
    """Compare the checks with the recorded incidents and queue messages. Returns {'opened': [...], 'cleared': [...]}."""
    from portal_telegram import notify_admins
    results = checks(store, now)
    opened, cleared = [], []
    with store.db() as db:
        store.database.begin_write(db, 'watchdog')
        now = store.database.clock(db) if now is None else now
        gates = _gates(db, 'alert:')
        for item in results:
            gate, fp_gate = 'alert:' + item['key'], 'alert:' + item['key'] + ':fp'
            fa, en = TITLES[item['key']]
            if not item['ok']:
                new_fingerprint = item['fingerprint'] is not None and item['fingerprint'] > gates.get(fp_gate, 0)
                if gate in gates and not new_fingerprint:continue   # Already reported: an ongoing incident is announced once.
                db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',
                           (gate, gates.get(gate, item['since'] or now)))
                if item['fingerprint'] is not None:
                    db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',
                               (fp_gate, item['fingerprint']))
                notify_admins(db, f'🚨 آوینا: {fa}\n{item["detail"]}', f'🚨 Avina: {en}\n{item["detail"]}')
                opened.append(item['key'])
            elif gate in gates:
                db.execute('DELETE FROM service_gate WHERE name IN (?,?)', (gate, fp_gate))
                notify_admins(db, f'✅ آوینا: برطرف شد، {fa}', f'✅ Avina: resolved, {en}')
                cleared.append(item['key'])
    return dict(opened=opened, cleared=cleared)
