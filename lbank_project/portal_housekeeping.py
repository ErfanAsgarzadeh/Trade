"""Daily cleanup of expired or old operational rows. Records that matter (orders, invoices, matched transfers, licenses,
admin events) are never touched."""
DAY = 86400
GATE = 'housekeeping:last'
# (table, condition on the clock `now`, age in seconds) in one list so the whole policy is visible at a glance.
RULES = (
    ('sessions', 'expires<=?', 0),
    ('telegram_link_codes', 'expires<?', 0),
    ('password_resets', 'expires<?', 0),
    ('email_tokens', 'expires<?', 0),
    ('login_limits', 'updated<?', DAY),
    ('attempts', 'start<?', 3600),
    ('telegram_outbox', 'sent IS NOT NULL AND sent<?', 7 * DAY),
    ('telegram_signal_sent', 'sent<?', 7 * DAY),
    ('mail_outbox', 'created<?', 7 * DAY),
    ('audit', 'at<?', 400 * DAY),
    ('payment_transfers', "status='unmatched' AND seen<?", 400 * DAY),
)


def due(store, now, every=DAY):
    with store.db() as db:
        row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (GATE,)).fetchone()
    return not row or now - row['next_at'] >= every


def housekeeping(store, now=None, every=DAY):
    """Run the cleanup at most once per `every` seconds across all processes. Returns {table: rows deleted}, or None when it
    is not due yet. The gate row is claimed and the deletes happen in one transaction, so two workers cannot both run it."""
    if now is None:
        with store.db() as db:now = store.database.clock(db)
    if not due(store, now, every):return None
    with store.db() as db:
        store.database.begin_write(db, 'housekeeping')
        row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (GATE,)).fetchone()
        if row and now - row['next_at'] < every:return None
        db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at', (GATE, now))
        return {table: db.execute(f'DELETE FROM {table} WHERE {condition}', (now - age,)).rowcount for table, condition, age in RULES}
