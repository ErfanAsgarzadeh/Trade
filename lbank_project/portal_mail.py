"""Optional e-mail: verification links, a second password-recovery channel and expiry reminders.

Mail is never sent inside a web request. The web process only writes rows to `mail_outbox`; the telegram-worker sends them
with smtplib (STARTTLS or SSL) using SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD_FILE and SMTP_FROM. Without those the
whole feature is off: nothing is queued and the panel says so. The web process learns that mail works from a gate row the worker
refreshes ('mail:enabled'), so the SMTP password never reaches the web container. Bodies are plain text built from fixed
templates; the only values in them are a link, a code or a date, and no user text ever reaches a header."""
from email.message import EmailMessage
import hashlib
import os
from pathlib import Path
import secrets
import smtplib
import ssl
import time
import uuid

ENABLED_GATE = 'mail:enabled'
ENABLED_FRESH = 300           # The worker refreshes the gate every loop; older than this means mail is not being sent.
VERIFY_LIFETIME = 86400
VERIFY_COOLDOWN = 60
MAX_ATTEMPTS = 5
BRAND = 'Avina'

TEMPLATES = {
    'verify': dict(
        fa=('تأیید ایمیل حساب آوینا', 'برای تأیید ایمیل حساب آوینای خود این پیوند را باز کنید (۲۴ ساعت معتبر است):\n{link}\n\nاگر شما درخواست نکرده‌اید، این پیام را نادیده بگیرید.'),
        en=('Confirm your Avina email', 'Open this link to confirm the email address of your Avina account (valid for 24 hours):\n{link}\n\nIf you did not ask for this, ignore this message.')),
    'reset': dict(
        fa=('کد بازیابی رمز عبور آوینا', 'کد بازیابی رمز عبور آوینا: {code}\nاین کد ۱۰ دقیقه معتبر است. اگر شما درخواست نکرده‌اید، آن را نادیده بگیرید و به کسی ندهید.'),
        en=('Your Avina password recovery code', 'Your Avina password recovery code: {code}\nIt is valid for 10 minutes. If you did not ask for it, ignore this message and tell no one.')),
    'expiry': dict(
        fa=('اشتراک آوینا {days} روز دیگر پایان می‌یابد', 'اشتراک آوینای شما در تاریخ {date} (UTC) پایان می‌یابد؛ حدود {days} روز دیگر.\nبرای تمدید وارد پنل خود شوید: {link}'),
        en=('Your Avina subscription ends in {days} day(s)', 'Your Avina subscription ends on {date} (UTC), in about {days} day(s).\nSign in to renew: {link}')),
}


class MailError(Exception):
    """The message could not be sent; the reason is never recorded because it may echo addresses or server banners."""


def render(name, lang, **values):
    """(subject, body) from a fixed template; `lang` falls back to Persian."""
    subject, body = TEMPLATES[name]['en' if lang == 'en' else 'fa']
    return subject.format(**values), body.format(**values)


def safe_address(value):
    """The address itself, or ValueError. CR, LF and any other control character are refused (header injection)."""
    from portal_store import normal_email
    text = str(value or '')
    if any(ord(c) < 32 or ord(c) == 127 for c in text):raise ValueError('Invalid address')
    return normal_email(text)


class Mailer:
    """SMTP sender configured from the environment. `sender(message)` can be replaced in tests."""

    def __init__(self, host='', port=587, user='', password='', sender_address='', sender=None):
        self.host, self.port, self.user, self.password, self.address = host, int(port), user, password, sender_address
        self.sender = sender or self._smtp

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        file = env.get('SMTP_PASSWORD_FILE')
        password = Path(file).read_text().strip() if file else ''
        return cls(env.get('SMTP_HOST', ''), env.get('SMTP_PORT') or 587, env.get('SMTP_USER', ''), password, env.get('SMTP_FROM', ''))

    @property
    def configured(self):
        if not (self.host and self.address) or any(ord(c) < 32 or ord(c) == 127 for c in self.address + self.host):return False
        try:safe_address(self.address.rsplit('<', 1)[-1].strip('> '));return True
        except ValueError:return False

    def message(self, to, subject, body):
        if '\r' in subject or '\n' in subject:raise ValueError('Invalid subject')
        message = EmailMessage()
        message['From'], message['To'], message['Subject'] = self.address, safe_address(to), subject
        message.set_content(body)
        return message

    def send(self, to, subject, body):
        if not self.configured:raise MailError('Mail is not configured')
        self.sender(self.message(to, subject, body))

    def _smtp(self, message):
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                client = smtplib.SMTP_SSL(self.host, self.port, timeout=20, context=context)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=20)
            with client:
                if self.port != 465:
                    client.ehlo();client.starttls(context=context);client.ehlo()
                if self.user:client.login(self.user, self.password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise MailError('SMTP failure') from None


# ---- Web side: queue only, never send ---------------------------------------------------------------------------------

def enabled(db, now=None):
    """True while the worker reports that SMTP is configured and it is sending."""
    now = time.time() if now is None else now
    row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (ENABLED_GATE,)).fetchone()
    return bool(row and now - row['next_at'] < ENABLED_FRESH)


def queue(db, to, subject, body, now=None):
    now = time.time() if now is None else now
    db.execute('INSERT INTO mail_outbox(id,to_address,subject,body,created,next_at) VALUES(?,?,?,?,?,?)',
               (str(uuid.uuid4()), safe_address(to), subject, body, now, now))


def request_verification(db, user, email, origin, lang='fa', now=None):
    """Replace any earlier link with a new 24-hour one and queue it. False (nothing stored) when mail is off."""
    now = time.time() if now is None else now
    if not enabled(db, now):return False
    token = secrets.token_urlsafe(32)
    db.execute('DELETE FROM email_tokens WHERE user_id=?', (user,))
    db.execute('INSERT INTO email_tokens(token_hash,user_id,email,created,expires) VALUES(?,?,?,?,?)',
               (hashlib.sha256(token.encode()).hexdigest(), user, email, now, now + VERIFY_LIFETIME))
    link = f'{origin}{"/en" if lang == "en" else ""}/verify-email?token={token}'
    queue(db, email, *render('verify', lang, link=link), now=now)
    return True


class Cooldown(Exception):
    """A verification link was sent less than a minute ago."""


def resend_verification(store, user, origin, lang='fa', now=None):
    """Panel button. LookupError when there is nothing to verify, Cooldown when asked too soon, False when mail is off."""
    now = time.time() if now is None else now
    with store.db() as db:
        store.database.begin_write(db, 'mail:' + user)
        row = db.execute('SELECT email,email_verified FROM users WHERE id=?', (user,)).fetchone()
        if not row or not row['email'] or row['email_verified']:raise LookupError('Nothing to verify')
        last = db.execute('SELECT MAX(created) AS at FROM email_tokens WHERE user_id=?', (user,)).fetchone()['at']
        if last and now - last < VERIFY_COOLDOWN:raise Cooldown()
        return request_verification(db, user, row['email'], origin, lang, now)


def verify(store, token, now=None):
    """Mark the address verified when the link is live and still matches the account's current address. Returns the user id or None."""
    now = time.time() if now is None else now
    if not token or len(token) > 100:return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store.db() as db:
        store.database.begin_write(db, 'mail:token')
        row = db.execute('SELECT user_id,email,expires FROM email_tokens WHERE token_hash=?', (digest,)).fetchone()
        if not row or row['expires'] < now:return None
        changed = db.execute('UPDATE users SET email_verified=1 WHERE id=? AND email=? AND disabled=0', (row['user_id'], row['email'])).rowcount
        db.execute('DELETE FROM email_tokens WHERE user_id=?', (row['user_id'],))
        if not changed:return None
        db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (row['user_id'], 'email_verified', now))
        return row['user_id']


# ---- Worker side ---------------------------------------------------------------------------------------------------------

def send_pending(store, mailer, now=None, limit=20):
    """Refresh the 'mail is on' gate and send queued mail with retries (1 min, 2 min, ... up to an hour; five attempts).
    Returns how many were sent."""
    now = time.time() if now is None else now
    if not mailer.configured:return 0
    with store.db() as db:
        db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',
                   (ENABLED_GATE, now))
        rows = db.execute('SELECT id,to_address,subject,body,attempts FROM mail_outbox WHERE sent IS NULL AND attempts<? AND next_at<=? '
                          'ORDER BY created LIMIT ?', (MAX_ATTEMPTS, now, limit)).fetchall()
    sent = 0
    for row in rows:
        try:
            mailer.send(row['to_address'], row['subject'], row['body'])
        except (MailError, ValueError):
            with store.db() as db:
                db.execute('UPDATE mail_outbox SET attempts=attempts+1,next_at=? WHERE id=?',
                           (now + min(3600, 60 * 2 ** row['attempts']), row['id']))
            continue
        with store.db() as db:db.execute("UPDATE mail_outbox SET sent=?,body='' WHERE id=?", (now, row['id']))   # A sent code is not kept.
        sent += 1
    return sent


# ---- Expiry reminders (run once a day by the telegram-worker) ---------------------------------------------------------

REMINDER_DAYS = (7, 1)
REMINDER_GATE = 'reminders:last'


def queue_expiry_reminders(store, origin, now=None, every=86400):
    """One reminder per license per threshold (7 and 1 day before expiry), by Telegram (linked, notices on) and by e-mail
    (verified, mail on). A license already inside the 1-day window gets only the 1-day message. A threshold is recorded
    only when some channel took it, so a customer who links Telegram later is still reminded. Returns how many licenses were reminded."""
    import json
    from datetime import datetime, timezone
    from license_access import timestamp
    from portal_telegram import notify
    queued_total = 0
    with store.db() as db:
        store.database.begin_write(db, 'reminders')
        now = store.database.clock(db) if now is None else now
        row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (REMINDER_GATE,)).fetchone()
        if row and now - row['next_at'] < every:return 0
        db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at', (REMINDER_GATE, now))
        mail_on = enabled(db, now)
        for lic in db.execute('SELECT c.user_id,c.document,u.email,u.email_verified FROM capital_licenses c JOIN users u ON u.id=c.user_id '
                              'WHERE u.disabled=0').fetchall():
            payload = json.loads(lic['document'])['payload']
            end = timestamp(payload['expires_at'])
            left = end - now
            if left <= 0 or left > max(REMINDER_DAYS) * 86400:continue
            crossed = [d for d in REMINDER_DAYS if left <= d * 86400]
            days = min(crossed)
            done = {r['threshold'] for r in db.execute('SELECT threshold FROM expiry_reminders WHERE user_id=? AND license_id=?',
                                                       (lic['user_id'], payload['license_id'])).fetchall()}
            if days in done:continue
            link = db.execute('SELECT chat_id,lang,notices FROM telegram_links WHERE user_id=?', (lic['user_id'],)).fetchone()
            lang = link['lang'] if link else 'fa'
            values = dict(days=days, date=datetime.fromtimestamp(end, timezone.utc).strftime('%Y-%m-%d'),
                          link=origin + ('/en' if lang == 'en' else '') + '/dashboard/')
            channels = 0
            if link and link['notices']:
                notify(db, lic['user_id'], render('expiry', 'fa', **values)[1], render('expiry', 'en', **values)[1])
                channels += 1
            if mail_on and lic['email'] and lic['email_verified']:
                queue(db, lic['email'], *render('expiry', lang, **values), now=now)
                channels += 1
            if channels:
                for threshold in crossed:
                    db.execute('INSERT INTO expiry_reminders(user_id,license_id,threshold,sent) VALUES(?,?,?,?) ON CONFLICT DO NOTHING',
                               (lic['user_id'], payload['license_id'], threshold, now))
                queued_total += 1
    return queued_total
