"""Two-step login (TOTP) and Telegram-based password recovery. Standard library only; secrets are encrypted or hashed at rest."""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

import portal_totp
from portal_audit import record

RESET_LIFETIME = 600
RESET_ATTEMPTS = 5
RESET_COOLDOWN = 60
RECOVERY = re.compile(r'^[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$')


class SecurityConflict(ValueError):
    """The request does not fit the account's current two-step state."""


def _use_totp(store, db, user, code):
    """Accept a TOTP code once: the step must be newer than the last accepted one (atomic compare-and-set)."""
    if not user['totp_secret']:return False
    step = portal_totp.match(store.vault.decrypt(user['totp_secret'].encode()).decode(), code, user['totp_last_step'])
    return step is not None and db.execute('UPDATE users SET totp_last_step=? WHERE id=? AND totp_last_step<?',
                                           (step, user['id'], step)).rowcount == 1


def _use_recovery(db, user, code):
    code = str(code or '').strip().lower()
    if not RECOVERY.match(code) or not user['totp_recovery']:return False
    digest, hashes, hit = portal_totp.recovery_digest(code), json.loads(user['totp_recovery']), False
    for item in hashes:hit = hmac.compare_digest(item, digest) or hit
    if not hit:return False
    left = json.dumps([h for h in hashes if h != digest])
    if db.execute('UPDATE users SET totp_recovery=? WHERE id=? AND totp_recovery=?', (left, user['id'], user['totp_recovery'])).rowcount != 1:
        return False
    record(db, user['id'], 'recovery_code_used', user['id'], dict(remaining=len(hashes) - 1))
    return True


def accept_login_code(store, db, user, code):
    """A login code: the current authenticator code, or an unused recovery code."""
    return _use_totp(store, db, user, code) or _use_recovery(db, user, code)


def step_up(store, user_id, code):
    """True when `code` is a fresh authenticator code for this user. A time step can be used once."""
    with store.db() as db:
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        return bool(user) and _use_totp(store, db, user, code)


def setup(store, user_id):
    """A new pending secret (replacing any earlier pending one). Nothing changes for login until it is confirmed."""
    secret = portal_totp.new_secret()
    with store.db() as db:
        user = db.execute('SELECT username,totp_secret FROM users WHERE id=?', (user_id,)).fetchone()
        if user['totp_secret']:raise SecurityConflict('Two-step login is already on')
        db.execute('UPDATE users SET totp_pending=? WHERE id=?', (store.vault.encrypt(secret.encode()).decode(), user_id))
    return dict(secret=secret, uri=portal_totp.uri(secret, user['username']))


def enable(store, user_id, code):
    """Confirm the pending secret with a code from the app; returns the one-time recovery codes, or None for a wrong code."""
    with store.db() as db:
        store.database.begin_write(db, 'totp:' + user_id)
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if user['totp_secret']:raise SecurityConflict('Two-step login is already on')
        if not user['totp_pending']:raise SecurityConflict('Start the setup first')
        step = portal_totp.match(store.vault.decrypt(user['totp_pending'].encode()).decode(), code, user['totp_last_step'])
        if step is None:return None
        codes = portal_totp.recovery_codes()
        db.execute('UPDATE users SET totp_secret=totp_pending,totp_pending=NULL,totp_last_step=?,totp_recovery=? WHERE id=?',
                   (step, json.dumps([portal_totp.recovery_digest(c) for c in codes]), user_id))
        record(db, user_id, 'totp_enabled', user_id)
        return codes


def disable(store, user_id, code):
    """Turn two-step login off after a valid authenticator or recovery code. Returns whether it was turned off."""
    with store.db() as db:
        store.database.begin_write(db, 'totp:' + user_id)
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not user['totp_secret'] or not accept_login_code(store, db, user, code):return False
        db.execute('UPDATE users SET totp_secret=NULL,totp_pending=NULL,totp_last_step=0,totp_recovery=NULL WHERE id=?', (user_id,))
        record(db, user_id, 'totp_disabled', user_id)
        return True


def reset_totp(store, username):
    """Operator CLI: remove two-step login for a user who lost the phone. All sessions end."""
    with store.db() as db:
        store.database.begin_write(db, 'totp:cli')
        user = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if not user:raise ValueError('Unknown user')
        db.execute('UPDATE users SET totp_secret=NULL,totp_pending=NULL,totp_last_step=0,totp_recovery=NULL WHERE id=?', (user['id'],))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        record(db, None, 'totp_reset', user['id'], dict(source='operator_cli'))


# ---- Password recovery through the linked Telegram account -------------------------------------------------------------

def _reset_digest(store, user_id, code):
    return hmac.new(store.token_key, f'reset:{user_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def request_reset(store, username, now=None):
    """Queue a one-time code to the user's Telegram. Silent in every case, so nothing reveals whether the account exists."""
    from portal_telegram import text
    now = time.time() if now is None else now
    with store.db() as db:
        store.database.begin_write(db, 'password-reset')
        user = db.execute('SELECT id,disabled FROM users WHERE username=?', (username,)).fetchone()
        link = db.execute('SELECT chat_id,lang FROM telegram_links WHERE user_id=?', (user['id'],)).fetchone() if user else None
        if not user or user['disabled'] or not link:return
        earlier = db.execute('SELECT created FROM password_resets WHERE user_id=?', (user['id'],)).fetchone()
        if earlier and now - earlier['created'] < RESET_COOLDOWN:return
        code = f'{secrets.randbelow(10 ** 8):08d}'
        db.execute('DELETE FROM password_resets WHERE user_id=?', (user['id'],))
        db.execute('INSERT INTO password_resets(user_id,code_hash,expires,attempts,created) VALUES(?,?,?,0,?)',
                   (user['id'], _reset_digest(store, user['id'], code), now + RESET_LIFETIME, now))
        db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                   (str(uuid.uuid4()), link['chat_id'], text(
                       link['lang'], f'کد بازیابی رمز عبور آوینا: {code}\nاین کد ۱۰ دقیقه معتبر است. اگر شما درخواست نکرده‌اید، آن را نادیده بگیرید و به کسی ندهید.',
                       f'Your Avina password recovery code: {code}\nIt is valid for 10 minutes. If you did not ask for it, ignore this message and tell no one.'), now))


def confirm_reset(store, username, code, password, now=None):
    """Set a new password when the code is right. False (and one attempt counted) otherwise; never says why."""
    from portal_store import password_hash
    from portal_telegram import notify
    now = time.time() if now is None else now
    code = str(code or '').strip()
    hashed = password_hash(password)  # Same work whether or not the account exists.
    with store.db() as db:
        store.database.begin_write(db, 'password-reset')
        user = db.execute('SELECT id,disabled FROM users WHERE username=?', (username,)).fetchone()
        row = db.execute('SELECT * FROM password_resets WHERE user_id=?', (user['id'],)).fetchone() if user else None
        live = bool(row and not user['disabled'] and row['expires'] > now and row['attempts'] < RESET_ATTEMPTS)
        expected = row['code_hash'] if live else _reset_digest(store, 'none', 'none')
        good = hmac.compare_digest(_reset_digest(store, user['id'] if user else 'none', code), expected) and live
        if not good:
            if live:db.execute('UPDATE password_resets SET attempts=attempts+1 WHERE user_id=?', (user['id'],))
            return False
        db.execute('UPDATE users SET password=? WHERE id=?', (hashed, user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        db.execute('DELETE FROM password_resets WHERE user_id=?', (user['id'],))
        db.execute('DELETE FROM login_limits WHERE username=?', (username,))
        record(db, user['id'], 'password_reset', user['id'], dict(via='telegram'))
        notify(db, user['id'], 'رمز عبور حساب آوینای شما با کد بازیابی تغییر کرد. اگر کار شما نبود فوراً با پشتیبانی تماس بگیرید.',
               'Your Avina password was changed with a recovery code. If this was not you, contact support immediately.', force=True)
    return True
