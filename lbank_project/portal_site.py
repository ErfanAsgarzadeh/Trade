"""Administrator-editable contact details shown on the public contact page and in Organization JSON-LD."""
import re
import time

from portal_audit import record, require_admin

FIELDS = ('support_email', 'telegram_id', 'telegram_link', 'other_line')
LIMITS = dict(support_email=120, telegram_id=65, telegram_link=120, other_line=160)
EMAIL = re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,80}\.[A-Za-z]{2,24}$')
TELEGRAM_ID = re.compile(r'^@?[A-Za-z0-9_]{4,64}$')
TELEGRAM_LINK = re.compile(r'^https://t\.me/[A-Za-z0-9_+/-]{2,100}$')
CONTROL = re.compile(r'[\x00-\x1f\x7f<>]')


def read(store):
    """{field: str}; empty strings for unset values."""
    try:
        with store.db() as db:
            rows = db.execute('SELECT name,value FROM site_settings WHERE name LIKE ?', ('site.%',)).fetchall()
    except Exception:
        rows = []
    values = {r['name'][5:]: r['value'] for r in rows}
    return {f: values.get(f, '') for f in FIELDS}


def clean(data):
    out = {}
    for field in FIELDS:
        value = str(data.get(field) or '').strip()
        if len(value) > LIMITS[field] or CONTROL.search(value):raise ValueError('Invalid ' + field)
        out[field] = value
    if out['support_email'] and not EMAIL.match(out['support_email']):raise ValueError('Invalid support_email')
    if out['telegram_id'] and not TELEGRAM_ID.match(out['telegram_id']):raise ValueError('Invalid telegram_id')
    if out['telegram_link'] and not TELEGRAM_LINK.match(out['telegram_link']):raise ValueError('Telegram link must start with https://t.me/')
    return out


def save(store, actor, data):
    values = clean(data)
    now = time.time()
    with store.db() as db:
        store.database.begin_write(db, 'site-info')
        require_admin(db, actor)
        for field, value in values.items():
            if value:
                db.execute('INSERT INTO site_settings(name,value,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET '
                           'value=excluded.value,updated=excluded.updated', ('site.' + field, value, now))
            else:
                db.execute('DELETE FROM site_settings WHERE name=?', ('site.' + field,))
        record(db, actor, 'site_info.update', 'site_info', {'fields': [f for f, v in values.items() if v]})
    return values
