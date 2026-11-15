"""Account security: password change and recovery, login limits, hashing cost, sign-up bot barrier, headers and two-step login."""
import hashlib
import json
from pathlib import Path
import sys
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_admin
import portal_totp
from db_targets import TARGETS, fresh_store
from portal_server import create_app
from portal_store import PortalStore, password_hash, scrypt_log_n, verify_password
from totp_helpers import AUTH, SKEW, Authenticator, enable_totp, extra, signup_token

ORIGIN = 'https://avina.example'
PASSWORD = 'disposable-test-password'
NEW = 'another-disposable-password'
H = {'X-Portal-Request': '1', 'Origin': ORIGIN}
GENERIC_422 = 'Invalid fields; check input length and required fields'


@pytest.fixture(params=TARGETS)
def store(request, tmp_path):
    store = fresh_store(request.param, tmp_path)
    store.create_user('manager', PASSWORD, 'm@example.com');store.set_admin('manager');enable_totp(store, 'manager')
    store.create_user('root', PASSWORD, 'r@example.com');store.set_admin('root')  # administrator who has not set up two-step login yet
    store.create_user('alice', PASSWORD, 'a@example.com');store.create_user('bob', PASSWORD, 'b@example.com')
    yield store
    store.close()


def uid(store, name):
    with store.db() as db:return db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()['id']


def link_telegram(store, name, chat, lang='en', notices=1):
    with store.db() as db:
        db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,?,?)',
                   (uid(store, name), chat, 'u', lang, notices, time.time()))


def outbox(store, chat=None):
    with store.db() as db:
        rows = db.execute('SELECT chat_id,text,protected FROM telegram_outbox ORDER BY created').fetchall()
    return [dict(r) for r in rows if chat is None or r['chat_id'] == chat]


def forget_ip_limits(store):
    with store.db() as db:db.execute('DELETE FROM attempts')


def sign_in(client, name, password=PASSWORD, **more):
    r = client.post('/api/login', headers=H, json=dict(username=name, password=password, **more))
    return r, ({**H, 'X-CSRF-Token': r.json()['csrf']} if r.status_code == 200 else None)


def as_user(client, name):
    r, headers = sign_in(client, name, **extra(name))
    assert r.status_code == 200, r.text
    return headers


@pytest.fixture
def app(store):
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        yield client


# ---- S5: hashing cost ------------------------------------------------------------------------------------------------

def test_new_hashes_cost_more_and_an_old_hash_still_logs_in_and_is_upgraded(store, monkeypatch):
    monkeypatch.setenv('PORTAL_SCRYPT_LOG_N', '15')
    salt = 'ab' * 16
    legacy = salt + ':' + hashlib.scrypt(PASSWORD.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    assert verify_password(PASSWORD, legacy) == (True, True) and verify_password('wrong-password-here', legacy) == (False, False)
    with store.db() as db:db.execute('UPDATE users SET password=? WHERE username=?', (legacy, 'alice'))
    assert store.login('alice', 'wrong-password-here') is None
    with store.db() as db:assert db.execute("SELECT password FROM users WHERE username='alice'").fetchone()['password'] == legacy  # not touched
    assert store.login('alice', PASSWORD)
    with store.db() as db:upgraded = db.execute("SELECT password FROM users WHERE username='alice'").fetchone()['password']
    assert upgraded.startswith('scrypt:15:8:1:') and upgraded != legacy
    assert store.login('alice', PASSWORD) and verify_password(PASSWORD, upgraded) == (True, False)
    monkeypatch.setenv('PORTAL_SCRYPT_LOG_N', '10')  # a cheaper setting never downgrades an existing hash
    assert store.login('alice', PASSWORD)
    with store.db() as db:assert db.execute("SELECT password FROM users WHERE username='alice'").fetchone()['password'] == upgraded


def test_production_cost_is_two_to_the_seventeenth(monkeypatch):
    monkeypatch.delenv('PORTAL_SCRYPT_LOG_N')
    assert scrypt_log_n() == 17
    stored = password_hash('a-long-enough-password')  # needs about 128 MB: proves maxmem is large enough
    assert stored.startswith('scrypt:17:8:1:') and verify_password('a-long-enough-password', stored) == (True, False)
    monkeypatch.setenv('PORTAL_SCRYPT_LOG_N', 'garbage');assert scrypt_log_n() == 17
    monkeypatch.setenv('PORTAL_SCRYPT_LOG_N', '99');assert scrypt_log_n() == 20


# ---- S5: per-username login limit -----------------------------------------------------------------------------------------

def test_five_failures_lock_a_username_for_a_growing_time_and_success_resets(store):
    def locked_for(name):
        with store.db() as db:
            row = db.execute('SELECT locked_until FROM login_limits WHERE username=?', (name,)).fetchone()
            return round(row['locked_until'] - time.time()) if row else None

    def expire(name):
        with store.db() as db:db.execute('UPDATE login_limits SET locked_until=?,window_start=window_start-1 WHERE username=?', (time.time() - 1, name))

    for _ in range(4):store.login_failed('alice')
    assert store.lock_wait('alice') == 0 and store.login('alice', PASSWORD)  # four failures: still allowed, and success resets
    with store.db() as db:assert db.execute("SELECT 1 FROM login_limits WHERE username='alice'").fetchone() is None
    seen = []
    for _ in range(6):
        for _ in range(5):store.login_failed('alice')
        seen.append(locked_for('alice'));expire('alice')
    assert seen == [60, 120, 240, 480, 900, 900]  # 1, 2, 4, 8 minutes, then never more than 15
    for _ in range(5):store.login_failed('alice')
    assert store.lock_wait('alice') > 0 and store.lock_wait('bob') == 0
    expire('alice')
    assert store.lock_wait('alice') == 0 and store.login('alice', PASSWORD)  # the lock is time-limited: no permanent lock-out


def test_login_lock_is_enforced_over_http_hides_existence_and_is_shared(store):
    results = {}
    for name in ('alice', 'nobody-here'):
        forget_ip_limits(store)
        with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
            codes = [sign_in(client, name, 'not-the-right-password')[0].status_code for _ in range(5)]
            locked = sign_in(client, name)[0]  # the correct password does not help while locked
            results[name] = (codes, locked.status_code, locked.json(), 'Retry-After' in locked.headers)
        with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as other_process:  # a second app instance, same database
            assert sign_in(other_process, name)[0].status_code == 429
    assert results['alice'] == results['nobody-here'] == ([401] * 5, 429, {'detail': 'Too many failed attempts for this account; try again later'}, True)
    forget_ip_limits(store)
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        assert sign_in(client, 'bob')[0].status_code == 200  # other users are not affected
        with store.db() as db:db.execute("UPDATE login_limits SET locked_until=0 WHERE username='alice'")
        assert sign_in(client, 'alice')[0].status_code == 200


# ---- S5: sign-up bot barrier, S8 -----------------------------------------------------------------------------------------

def test_signup_needs_an_old_enough_signed_untouched_form(store, app):
    def post(**changes):
        body = dict(username='fresh-user', password=PASSWORD, password_confirmation=PASSWORD, email='fresh@example.com', form_token=signup_token(store))
        body.update(changes)
        return app.post('/api/register', headers=H, json=body)
    token = app.get('/api/register/token').json()['token']
    stamp, mac = token.split('.')
    bad = {'too fast': token, 'missing': '', 'garbage': 'x.y', 'tampered': f'{int(stamp) - 100}.{mac}',
           'too old': store.form_token(now=time.time() - 7300), 'honeypot': None}
    answers = []
    for name, value in bad.items():
        forget_ip_limits(store)
        r = post(website='http://spam.example') if name == 'honeypot' else post(form_token=value)
        answers.append((r.status_code, r.json()))
    assert answers == [(422, {'detail': GENERIC_422})] * len(bad)
    with store.db() as db:assert db.execute('SELECT COUNT(*) AS n FROM users WHERE username=?', ('fresh-user',)).fetchone()['n'] == 0
    forget_ip_limits(store)
    time.sleep(3.1)
    assert post(form_token=token).status_code == 201  # the token issued above is valid after 3 seconds
    forget_ip_limits(store)
    assert post(username='fresh-two', email='fresh2@example.com', form_token=store.form_token(now=time.time() - 3.5)).status_code == 201
    assert app.get('/api/register/token').headers['cache-control'] == 'no-store'


def test_a_taken_username_and_a_taken_email_get_the_same_answer(store, app):
    base = dict(password=PASSWORD, password_confirmation=PASSWORD, form_token=signup_token(store))
    name_taken = app.post('/api/register', headers=H, json=dict(base, username='alice', email='new-one@example.com'))
    mail_taken = app.post('/api/register', headers=H, json=dict(base, username='new-name', email='A@example.com'))
    both_taken = app.post('/api/register', headers=H, json=dict(base, username='alice', email='a@example.com'))
    assert name_taken.status_code == mail_taken.status_code == both_taken.status_code == 409
    assert name_taken.json() == mail_taken.json() == both_taken.json() == {'detail': 'Username or email unavailable'}


# ---- S9: email needs the password -----------------------------------------------------------------------------------------

def test_changing_the_email_needs_the_current_password(store, app):
    h = as_user(app, 'alice')
    assert app.put('/api/me/email', headers=h, json={'email': 'x@example.com'}).status_code == 422
    wrong = app.put('/api/me/email', headers=h, json={'email': 'x@example.com', 'current_password': 'not-my-password'})
    assert wrong.status_code == 403
    with store.db() as db:assert db.execute("SELECT email FROM users WHERE username='alice'").fetchone()['email'] == 'a@example.com'
    assert app.put('/api/me/email', headers=h, json={'email': 'x@example.com', 'current_password': PASSWORD}).json() == {'email': 'x@example.com'}


# ---- S10: headers -----------------------------------------------------------------------------------------------------------

def test_security_headers_and_the_proxy_leaves_them_to_the_application(store, app):
    for path in ('/', '/api/me', '/healthz'):
        headers = app.get(path).headers
        assert headers['permissions-policy'] == 'camera=(), microphone=(), geolocation=(), payment=()'
        assert headers['cross-origin-opener-policy'] == 'same-origin'
        assert headers['strict-transport-security'] == 'max-age=31536000; includeSubDomains'
        assert headers['x-frame-options'] == 'DENY' and 'frame-ancestors' in headers['content-security-policy']
    caddy = (Path(__file__).resolve().parents[1] / 'Caddyfile').read_text()
    assert 'Strict-Transport-Security' not in caddy and 'X-Content-Type-Options' not in caddy and 'Referrer-Policy' not in caddy
    assert '-Server' in caddy and 'header_down -Server' in caddy


# ---- S2: password change and sessions ---------------------------------------------------------------------------------------

def test_password_change_ends_every_session_and_opens_a_fresh_one(store):
    link_telegram(store, 'alice', 501, notices=0)
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as one, TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as two:
        h = as_user(one, 'alice');as_user(two, 'alice')
        body = dict(current_password=PASSWORD, new_password=NEW, new_password_confirmation=NEW)
        assert one.put('/api/me/password', json=body).status_code == 403  # CSRF
        short = dict(body, new_password='short', new_password_confirmation='short')
        assert one.put('/api/me/password', headers=h, json=short).status_code == 422
        assert one.put('/api/me/password', headers=h, json=dict(body, new_password_confirmation=NEW + 'x')).status_code == 422
        assert one.put('/api/me/password', headers=h, json=dict(body, extra=1)).status_code == 422
        wrong = one.put('/api/me/password', headers=h, json=dict(body, current_password='not-my-password'))
        assert wrong.status_code == 403 and store.login('alice', PASSWORD)
        old_cookie = one.cookies.get('trade_session')
        done = one.put('/api/me/password', headers=h, json=body)
        assert done.status_code == 200 and done.json()['csrf'] != h['X-CSRF-Token']
        assert 'HttpOnly' in done.headers['set-cookie'] and one.cookies.get('trade_session') != old_cookie
        assert one.get('/api/me').status_code == 200 and two.get('/api/me').status_code == 401  # every other session is gone
        forget_ip_limits(store)
        assert sign_in(one, 'alice')[0].status_code == 401 and sign_in(one, 'alice', NEW)[0].status_code == 200
        fresh = {**H, 'X-CSRF-Token': done.json()['csrf']}
        assert one.get('/api/me').status_code == 200 and fresh
    with store.db() as db:
        assert db.execute("SELECT 1 FROM admin_events WHERE action='password_changed' AND actor_id=?", (uid(store, 'alice'),)).fetchone()
        assert db.execute("SELECT password FROM users WHERE username='alice'").fetchone()['password'].startswith('scrypt:')
    notice = outbox(store, 501)  # sent although the user switched ordinary notices off
    assert len(notice) == 1 and 'password was changed' in notice[0]['text']


def test_wrong_current_passwords_are_counted_and_stop_at_the_limit(store, app):
    h = as_user(app, 'alice')
    body = dict(current_password='not-my-password', new_password=NEW, new_password_confirmation=NEW)
    codes = [app.put('/api/me/password', headers=h, json=body).status_code for _ in range(11)]
    assert codes == [403] * 10 + [429]
    assert app.put('/api/me/password', headers=h, json=dict(body, current_password=PASSWORD)).status_code == 429  # right password, but throttled
    assert store.login('alice', PASSWORD)  # the password was never changed


def test_sign_out_other_devices_keeps_only_this_session(store):
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as one, TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as two, \
            TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as bobs:
        h = as_user(one, 'alice');as_user(two, 'alice');as_user(bobs, 'bob')
        assert one.post('/api/me/sessions/revoke-others').status_code == 403  # CSRF
        assert one.post('/api/me/sessions/revoke-others', headers=h).json() == {'revoked': 1}
        assert one.get('/api/me').status_code == 200 and two.get('/api/me').status_code == 401 and bobs.get('/api/me').status_code == 200
        assert one.post('/api/me/sessions/revoke-others', headers=h).json() == {'revoked': 0}


# ---- S2: recovery through Telegram -------------------------------------------------------------------------------------------

def reset_body(code, **more):
    return dict(dict(username='alice', code=code, new_password=NEW, new_password_confirmation=NEW), **more)


def test_recovery_code_goes_only_to_a_linked_telegram_and_the_answer_never_differs(store, app):
    link_telegram(store, 'alice', 601, lang='fa');link_telegram(store, 'bob', 602, lang='en')
    with store.db() as db:db.execute("UPDATE users SET disabled=1 WHERE username='bob'")
    store.create_user('carol', PASSWORD, 'c@example.com')  # exists, no Telegram
    answers = []
    for name in ('alice', 'bob', 'carol', 'nobody-here'):
        forget_ip_limits(store)
        r = app.post('/api/password-reset/request', headers=H, json={'username': name})
        answers.append((r.status_code, r.json()))
    assert answers == [(202, answers[0][1])] * 4
    assert app.post('/api/password-reset/request', json={'username': 'alice'}).status_code == 403  # same-origin check
    sent = outbox(store)
    assert [m['chat_id'] for m in sent] == [601]  # disabled, unlinked and unknown accounts get nothing
    digits = [w for w in sent[0]['text'].replace('\n', ' ').split() if w.isdigit() and len(w) == 8]
    assert len(digits) == 1 and 'آوینا' in sent[0]['text']
    with store.db() as db:
        row = db.execute('SELECT * FROM password_resets').fetchone()
        assert row['code_hash'] != digits[0] and digits[0] not in row['code_hash'] and 590 < row['expires'] - row['created'] < 610 and row['attempts'] == 0
    forget_ip_limits(store)
    assert app.post('/api/password-reset/request', headers=H, json={'username': 'alice'}).status_code == 202
    assert len(outbox(store)) == 1  # a request inside the cool-down queues nothing new


def issue_code(store, app, name='alice', age=0):
    forget_ip_limits(store)
    with store.db() as db:db.execute('DELETE FROM password_resets')
    assert app.post('/api/password-reset/request', headers=H, json={'username': name}).status_code == 202
    text = outbox(store)[-1]['text']
    with store.db() as db:db.execute('UPDATE password_resets SET created=created-?,expires=expires-?', (age, age))
    return next(w for w in text.replace('\n', ' ').split() if w.isdigit() and len(w) == 8)


def test_confirming_a_recovery_code_sets_the_password_and_ends_all_sessions(store, app):
    link_telegram(store, 'alice', 601, lang='en')
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as other:
        as_user(other, 'alice')
        code = issue_code(store, app)
        assert 'Your Avina password recovery code' in outbox(store)[-1]['text']
        r = app.post('/api/password-reset/confirm', headers=H, json=reset_body(code))
        assert r.status_code == 200 and other.get('/api/me').status_code == 401
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) AS n FROM password_resets').fetchone()['n'] == 0 and db.execute('SELECT COUNT(*) AS n FROM sessions WHERE user_id=?', (uid(store, 'alice'),)).fetchone()['n'] == 0
        assert db.execute("SELECT 1 FROM admin_events WHERE action='password_reset'").fetchone()
    forget_ip_limits(store)
    assert store.login('alice', NEW) and store.login('alice', PASSWORD) is None
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body(code)).status_code == 403  # a code works once
    assert 'password was changed with a recovery code' in outbox(store)[-1]['text']


def test_wrong_expired_and_overused_codes_all_get_the_same_refusal(store, app):
    link_telegram(store, 'alice', 601, lang='en')
    code = issue_code(store, app)
    wrong = '00000000' if code != '00000000' else '11111111'
    refusals = []
    for body in (reset_body(wrong), reset_body(wrong, username='nobody-here'), dict(reset_body(wrong), username='bob')):
        forget_ip_limits(store)
        r = app.post('/api/password-reset/confirm', headers=H, json=body)
        refusals.append((r.status_code, r.json()))
    assert refusals == [(403, {'detail': 'Invalid or expired code'})] * 3
    with store.db() as db:assert db.execute('SELECT attempts FROM password_resets').fetchone()['attempts'] == 1
    for _ in range(4):
        forget_ip_limits(store);app.post('/api/password-reset/confirm', headers=H, json=reset_body(wrong))
    forget_ip_limits(store)
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body(code)).status_code == 403  # five wrong tries burn the code
    assert store.login('alice', PASSWORD)
    code = issue_code(store, app, age=601)  # older than ten minutes
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body(code)).status_code == 403
    first = issue_code(store, app);second = issue_code(store, app)  # a new request replaces the earlier code
    forget_ip_limits(store)
    if first != second:assert app.post('/api/password-reset/confirm', headers=H, json=reset_body(first)).status_code == 403
    forget_ip_limits(store)
    assert app.post('/api/password-reset/confirm', headers=H, json=dict(reset_body(second), new_password_confirmation='different-password')).status_code == 422
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body('12ab')).status_code == 422
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body(second)).status_code == 200


def test_recovery_requests_are_rate_limited_per_address_and_per_username(store, app):
    codes = [app.post('/api/password-reset/request', headers=H, json={'username': 'nobody-here'}).status_code for _ in range(11)]
    assert codes == [202] * 10 + [429]
    forget_ip_limits(store)
    with store.db() as db:db.execute("INSERT INTO attempts VALUES('reset-user:alice',?,10)", (time.time(),))
    assert app.post('/api/password-reset/request', headers=H, json={'username': 'alice'}).status_code == 429
    assert app.post('/api/password-reset/confirm', headers=H, json=reset_body('12345678')).status_code == 429


# ---- S1: two-step login -----------------------------------------------------------------------------------------------------

def test_totp_matches_the_rfc_6238_vectors_and_accepts_one_step_either_side():
    secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'  # ASCII 12345678901234567890, the RFC 6238 SHA-1 test key
    assert portal_totp.code_at(secret, 59 // 30) == '287082' and portal_totp.code_at(secret, 1111111109 // 30) == '081804'
    now = 1_700_000_000;step = now // 30
    assert portal_totp.match(secret, portal_totp.code_at(secret, step), 0, now) == step
    assert portal_totp.match(secret, portal_totp.code_at(secret, step - 1), 0, now) == step - 1
    assert portal_totp.match(secret, portal_totp.code_at(secret, step + 1), 0, now) == step + 1
    assert portal_totp.match(secret, portal_totp.code_at(secret, step - 2), 0, now) is None
    assert portal_totp.match(secret, portal_totp.code_at(secret, step + 2), 0, now) is None
    assert portal_totp.match(secret, portal_totp.code_at(secret, step), step, now) is None  # a used step is never accepted again
    assert portal_totp.match(secret, '12345', 0, now) is None and portal_totp.match(secret, 'abcdef', 0, now) is None
    assert portal_totp.uri(secret, 'root') == f'otpauth://totp/Avina%3Aroot?secret={secret}&issuer=Avina&algorithm=SHA1&digits=6&period=30'


def test_an_admin_without_two_step_login_can_read_and_set_up_but_not_change_anything(store, app):
    h = as_user(app, 'root')
    assert app.get('/api/admin/overview').status_code == 200 and app.get('/api/me').json()['totp_enabled'] is False
    for method, url, body in (('patch', '/api/admin/users/' + uid(store, 'alice'), {'disabled': True}), ('put', '/api/admin/payments', {}),
                              ('post', '/api/admin/telegram/broadcast', {'text': 'hi'}), ('post', '/api/admin/blog', {})):
        r = getattr(app, method)(url, headers=h, json=body)
        assert r.status_code == 403 and r.json() == {'detail': 'Two-factor setup required'}, url
    assert app.patch('/api/admin/users/' + uid(store, 'alice'), headers=as_user(app, 'manager'), json={'disabled': False}).status_code == 200  # TOTP admins pass


def test_setup_enable_login_recovery_and_disable(store, app):
    h = as_user(app, 'root')
    assert app.post('/api/me/totp/setup', headers=h, json={'current_password': 'not-my-password'}).status_code == 403
    assert app.post('/api/me/totp/enable', headers=h, json={'code': '123456'}).status_code == 409  # nothing pending yet
    setup = app.post('/api/me/totp/setup', headers=h, json={'current_password': PASSWORD}).json()
    secret = setup['secret']
    assert setup['uri'] == portal_totp.uri(secret, 'root') and len(secret) == 32
    with store.db() as db:
        row = db.execute("SELECT totp_secret,totp_pending FROM users WHERE username='root'").fetchone()
    assert row['totp_secret'] is None and secret not in row['totp_pending'] and store.vault.decrypt(row['totp_pending'].encode()).decode() == secret
    assert app.get('/api/me').json()['totp_enabled'] is False
    auth = Authenticator(secret)
    assert app.post('/api/me/totp/enable', headers=h, json={'code': '000000' if auth.code() != '000000' else '111111'}).status_code == 403
    assert app.post('/api/me/totp/enable', headers=h, json={'code': 'abc'}).status_code == 422
    forget_ip_limits(store)
    enabled = app.post('/api/me/totp/enable', headers=h, json={'code': auth.code()})
    codes = enabled.json()['recovery_codes']
    assert enabled.status_code == 200 and len(codes) == 10 and len(set(codes)) == 10
    with store.db() as db:
        row = db.execute("SELECT totp_secret,totp_pending,totp_recovery FROM users WHERE username='root'").fetchone()
        assert row['totp_pending'] is None and secret not in row['totp_secret'] and not any(c in row['totp_recovery'] for c in codes)
        assert len(json.loads(row['totp_recovery'])) == 10 and db.execute("SELECT 1 FROM admin_events WHERE action='totp_enabled'").fetchone()
    assert app.post('/api/me/totp/setup', headers=h, json={'current_password': PASSWORD}).status_code == 409  # already on
    assert app.get('/api/me').json()['totp_enabled'] is True
    assert app.patch('/api/admin/users/' + uid(store, 'alice'), headers=h, json={'disabled': False}).status_code == 200  # the guard now lets root through
    # Login: password alone is not enough.
    forget_ip_limits(store)
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        assert sign_in(client, 'root', 'not-my-password')[0].json() == {'detail': 'Invalid credentials'}  # two-step state is not revealed to wrong passwords
        missing = sign_in(client, 'root')[0]
        assert missing.status_code == 401 and missing.json() == {'detail': 'Two-factor code required'}
        assert sign_in(client, 'root', totp='123456')[0].json() == {'detail': 'Two-factor code required'}
        with store.db() as db:assert db.execute("SELECT failures FROM login_limits WHERE username='root'").fetchone()['failures'] == 3  # counted in the limiter
        good = auth.code()
        r, _ = sign_in(client, 'root', totp=good)
        assert r.status_code == 200 and client.get('/api/me').json()['username'] == 'root'
        with store.db() as db:assert db.execute("SELECT 1 FROM login_limits WHERE username='root'").fetchone() is None
        forget_ip_limits(store)
        assert sign_in(client, 'root', totp=good)[0].status_code == 401  # the same step cannot be used twice
        assert sign_in(client, 'root', totp=codes[0])[0].status_code == 200  # a recovery code works once
        forget_ip_limits(store)
        assert sign_in(client, 'root', totp=codes[0])[0].status_code == 401
        assert sign_in(client, 'root', totp=codes[1].upper())[0].status_code == 200
        with store.db() as db:assert len(json.loads(db.execute("SELECT totp_recovery FROM users WHERE username='root'").fetchone()['totp_recovery'])) == 8
        # Disabling needs the password and a code.
        forget_ip_limits(store)
        h = {**H, 'X-CSRF-Token': client.get('/api/me').json()['csrf']}
        assert client.post('/api/me/totp/disable', headers=h, json={'current_password': 'not-my-password', 'code': auth.code()}).status_code == 403
        assert client.post('/api/me/totp/disable', headers=h, json={'current_password': PASSWORD, 'code': '000000'}).status_code == 403
        assert client.get('/api/me').json()['totp_enabled'] is True
        assert client.post('/api/me/totp/disable', headers=h, json={'current_password': PASSWORD, 'code': codes[2]}).json() == {'status': 'disabled'}
        assert client.get('/api/me').json()['totp_enabled'] is False
        assert client.patch('/api/admin/users/' + uid(store, 'alice'), headers=h, json={'disabled': False}).json() == {'detail': 'Two-factor setup required'}
    with store.db() as db:assert db.execute("SELECT 1 FROM admin_events WHERE action='totp_disabled'").fetchone()


def test_customers_can_use_two_step_login_too(store, app):
    h = as_user(app, 'alice')
    secret = app.post('/api/me/totp/setup', headers=h, json={'current_password': PASSWORD}).json()['secret']
    assert app.post('/api/me/totp/enable', headers=h, json={'code': Authenticator(secret).code()}).status_code == 200
    forget_ip_limits(store)
    assert sign_in(app, 'alice')[0].json() == {'detail': 'Two-factor code required'}


def test_admin_sessions_last_two_hours_and_customer_sessions_twelve(store, app):
    cases = {'manager': 7200, 'alice': 43200}
    for name, seconds in cases.items():
        r, _ = sign_in(app, name, **extra(name))
        assert r.status_code == 200 and f'Max-Age={seconds}' in r.headers['set-cookie']
        with store.db() as db:
            expires = db.execute('SELECT MAX(expires) AS e FROM sessions WHERE user_id=?', (uid(store, name),)).fetchone()['e']
        assert abs(expires - time.time() - seconds) < 10
    forget_ip_limits(store)
    r = app.post('/api/register', headers=H, json=dict(username='fresh-user', password=PASSWORD, password_confirmation=PASSWORD, email='f@example.com', form_token=signup_token(store)))
    assert 'Max-Age=43200' in r.headers['set-cookie']


def test_the_three_sensitive_admin_actions_need_a_fresh_code_that_cannot_be_replayed(store, app):
    h = as_user(app, 'manager');auth = AUTH['manager']
    for url, body in (('/api/admin/payments', {'tron_address': ''}), ('/api/admin/telegram', {'token': ''}),
                      ('/api/admin/referrals/rewards', {'username': 'alice', 'kind': 'credit', 'value': 5})):
        method = app.put if url != '/api/admin/referrals/rewards' else app.post
        assert method(url, headers=h, json=body).status_code == 422, url  # the code field is mandatory
        assert method(url, headers=h, json=dict(body, totp='abcdef')).status_code == 422
        refused = method(url, headers=h, json=dict(body, totp='000000'))
        assert refused.status_code == 403 and refused.json() == {'detail': 'Invalid two-factor code'}, url
        code = auth.code()
        assert method(url, headers=h, json=dict(body, totp=code)).status_code in (200, 201), url
        replay = method(url, headers=h, json=dict(body, totp=code))
        assert replay.status_code == 403 and replay.json() == {'detail': 'Invalid two-factor code'}, url
        forget_ip_limits(store)
    # The previous step (within the allowed window) is valid once, but not after a newer step was used.
    older = portal_totp.code_at(auth.secret, int(portal_totp.now() // 30) - 1)
    assert app.put('/api/admin/payments', headers=h, json={'totp': older}).status_code == 403
    with store.db() as db:assert db.execute("SELECT COUNT(*) AS n FROM admin_events WHERE action IN ('payment_settings_saved','telegram_removed','referral_reward_granted')").fetchone()['n'] == 3
    # Other admin mutations do not ask for a code, and customers never reach any of this.
    assert app.patch('/api/admin/users/' + uid(store, 'alice'), headers=h, json={'disabled': False}).status_code == 200
    forget_ip_limits(store)
    alice = as_user(app, 'alice')
    assert app.put('/api/admin/payments', headers=alice, json={'totp': '123456'}).status_code == 403


def test_operator_cli_removes_two_step_login_for_a_lost_phone(tmp_path, monkeypatch, capsys):
    key = Fernet.generate_key();keyfile = tmp_path / 'portal.key';keyfile.write_bytes(key + b'\n')
    store = PortalStore(tmp_path / 'cli.db', key)
    store.create_user('root', PASSWORD, 'r@example.com');store.set_admin('root');enable_totp(store, 'root')
    token, _ = store.login('root', PASSWORD, AUTH['root'].code())
    run = lambda *args: (monkeypatch.setattr(sys, 'argv', ['portal_admin', '--db', str(tmp_path / 'cli.db'), '--key-file', str(keyfile), *args]), portal_admin.main())
    with pytest.raises(SystemExit):run('reset-totp', 'nobody-here')
    run('reset-totp', 'root')
    assert 'Two-step login removed' in capsys.readouterr().out
    assert store.session(token) is None and store.login('root', PASSWORD)
    with store.db() as db:
        row = db.execute("SELECT totp_secret,totp_pending,totp_recovery,totp_last_step FROM users WHERE username='root'").fetchone()
        assert tuple(row) == (None, None, None, 0) and db.execute("SELECT 1 FROM admin_events WHERE action='totp_reset'").fetchone()
    store.close()
