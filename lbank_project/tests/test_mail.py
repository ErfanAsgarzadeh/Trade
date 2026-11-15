"""Optional e-mail: verification links, password recovery as a second channel, expiry reminders and the SMTP sender."""
import json
import re
import ssl
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_mail
from portal_mail import Mailer, MailError, queue_expiry_reminders, render, safe_address, send_pending
from portal_server import create_app
from portal_telegram import Worker
from db_targets import TARGETS, fresh_store

ORIGIN = 'https://avina.example';PASSWORD = 'disposable-test-password'
H = {'X-Portal-Request': '1', 'Origin': ORIGIN}


class Outbox:
    """A fake SMTP sender injected into the mailer; `fail` makes it raise like a refused connection."""
    def __init__(self):self.messages, self.fail = [], False
    def __call__(self, message):
        if self.fail:raise MailError('down')
        self.messages.append(message)


@pytest.fixture(params=TARGETS)
def setup(request, tmp_path):
    store = fresh_store(request.param, tmp_path)
    outbox = Outbox()
    mailer = Mailer('smtp.example', 587, '', '', 'Avina <noreply@avina.example>', sender=outbox)
    worker = Worker(store, lambda: {}, ORIGIN, mailer=mailer)
    with TestClient(create_app(store, origin=ORIGIN, secure=True), base_url=ORIGIN) as client:
        yield store, worker, outbox, client
    store.close()


def signup(client, name='alice', email='alice@example.com', lang='fa'):
    token = client.get('/api/register/token').json()['token']
    return client.post('/api/register', headers=H, json=dict(username=name, password=PASSWORD, password_confirmation=PASSWORD, email=email,
                                                             form_token=token, lang=lang))


@pytest.fixture(autouse=True)
def instant_forms(monkeypatch):
    import portal_store
    monkeypatch.setattr(portal_store, 'FORM_MIN_AGE', 0)


def rows(store, table, where='1=1'):
    with store.db() as db:return [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE {where}').fetchall()]


def link_from(message):
    return re.search(r'https://avina\.example(/en)?/verify-email\?token=[\w-]+', message.get_content()).group(0)


def test_everything_is_off_without_smtp_and_says_so(setup):
    store, worker, outbox, client = setup
    assert signup(client).status_code == 201
    assert rows(store, 'mail_outbox') == [] and rows(store, 'email_tokens') == []
    me = client.get('/api/me').json()
    assert me['mail_enabled'] is False and me['email_verified'] is False and me['email'] == 'alice@example.com'
    assert client.post('/api/me/email/verify', headers={**H, 'X-CSRF-Token': me['csrf']}, json={}).status_code == 409
    worker.mailer = Mailer()                       # Nothing configured: the worker sends nothing and refreshes no gate.
    assert not worker.mailer.configured and send_pending(store, worker.mailer) == 0 and rows(store, 'service_gate', "name='mail:enabled'") == []


def test_signup_queues_a_link_the_worker_sends_and_the_page_confirms_it(setup):
    store, worker, outbox, client = setup
    worker.background()                                                     # Worker is up: mail counts as enabled.
    assert signup(client, lang='en').status_code == 201
    queued = rows(store, 'mail_outbox')
    assert len(queued) == 1 and queued[0]['to_address'] == 'alice@example.com' and queued[0]['sent'] is None
    tokens = rows(store, 'email_tokens')
    assert len(tokens) == 1 and len(tokens[0]['token_hash']) == 64 and abs(tokens[0]['expires'] - tokens[0]['created'] - 86400) < 1
    assert worker.background() and len(outbox.messages) == 1
    message = outbox.messages[0]
    assert message['To'] == 'alice@example.com' and message['From'] == 'Avina <noreply@avina.example>' and 'Confirm your Avina email' in message['Subject']
    url = link_from(message)
    assert '/en/verify-email' in url and tokens[0]['token_hash'] != url.split('token=')[1]    # Only a hash is stored.
    assert rows(store, 'mail_outbox')[0]['body'] == '' and rows(store, 'mail_outbox')[0]['sent']
    assert client.get('/api/me').json()['mail_enabled'] is True
    page = client.get(url.replace(ORIGIN, ''))
    assert page.status_code == 200 and '<html lang="en" dir="ltr"' in page.text and 'is confirmed' in page.text
    assert '<script>' not in page.text and 'noindex' in page.text and page.headers['cache-control'] == 'no-store'
    assert client.get('/api/me').json()['email_verified'] is True
    again = client.get(url.replace(ORIGIN, ''))
    assert again.status_code == 400 and 'not valid' in again.text
    assert client.get('/verify-email?token=nope').status_code == 400 and 'پیوند' in client.get('/verify-email?token=nope').text


def test_persian_is_the_default_language_and_expired_or_replaced_links_fail(setup):
    store, worker, outbox, client = setup
    worker.background();signup(client);worker.background()
    url = link_from(outbox.messages[0])
    assert '/en/' not in url and 'تأیید ایمیل' in outbox.messages[0]['Subject']
    with store.db() as db:db.execute('UPDATE email_tokens SET expires=?', (time.time() - 1,))
    assert client.get(url.replace(ORIGIN, '')).status_code == 400
    assert client.get('/api/me').json()['email_verified'] is False


def test_changing_the_address_unverifies_it_and_old_links_stop_working(setup):
    store, worker, outbox, client = setup
    worker.background();csrf = signup(client).json()['csrf'];worker.background()
    first = link_from(outbox.messages[0])
    me = {**H, 'X-CSRF-Token': csrf}
    changed = client.put('/api/me/email', headers=me, json=dict(email='new@example.com', current_password=PASSWORD, lang='en'))
    assert changed.status_code == 200
    worker.background()
    assert client.get(first.replace(ORIGIN, '')).status_code == 400                      # Replaced by the new link.
    second = link_from(outbox.messages[-1])
    assert outbox.messages[-1]['To'] == 'new@example.com' and '/en/' in second
    assert client.get(second.replace(ORIGIN, '')).status_code == 200 and client.get('/api/me').json()['email_verified'] is True
    client.put('/api/me/email', headers=me, json=dict(email='new@example.com', current_password=PASSWORD))
    assert client.get('/api/me').json()['email_verified'] is True                       # The same address stays verified.
    client.put('/api/me/email', headers=me, json=dict(email='third@example.com', current_password=PASSWORD))
    assert client.get('/api/me').json()['email_verified'] is False


def test_resend_is_rate_limited_and_refused_once_verified(setup):
    store, worker, outbox, client = setup
    worker.background();csrf = signup(client).json()['csrf']
    me = {**H, 'X-CSRF-Token': csrf}
    cooling = client.post('/api/me/email/verify', headers=me, json={})
    assert cooling.status_code == 429 and cooling.headers['retry-after'] == '60'        # A link was queued by the sign-up just now.
    with store.db() as db:db.execute('UPDATE email_tokens SET created=created-120')
    assert client.post('/api/me/email/verify', headers=me, json={'lang': 'en'}).status_code == 202
    assert len(rows(store, 'email_tokens')) == 1 and len(rows(store, 'mail_outbox')) == 2
    worker.background()
    client.get(link_from(outbox.messages[-1]).replace(ORIGIN, ''))
    assert client.post('/api/me/email/verify', headers=me, json={}).status_code == 409
    assert client.post('/api/me/email/verify', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json={}).status_code in (401, 403)


def reset_code(message):
    return re.search(r'\b(\d{8})\b', message.get_content()).group(1)


def test_password_recovery_code_also_goes_to_a_verified_address_only(setup):
    store, worker, outbox, client = setup
    worker.background();signup(client);worker.background()
    asked = lambda name: client.post('/api/password-reset/request', headers=H, json=dict(username=name))
    unverified = asked('alice')
    unknown = asked('nobody')
    assert unverified.status_code == unknown.status_code == 202 and unverified.json() == unknown.json()
    worker.background();assert len(outbox.messages) == 1 and 'verify-email' in outbox.messages[0].get_content()   # No code for an unverified address.
    client.get(link_from(outbox.messages[0]).replace(ORIGIN, ''))
    with store.db() as db:db.execute('UPDATE password_resets SET created=created-3600')
    assert asked('alice').status_code == 202 and worker.background() and len(outbox.messages) == 2
    code = reset_code(outbox.messages[1])
    assert 'recovery code' in outbox.messages[1]['Subject'] or 'بازیابی' in outbox.messages[1]['Subject']
    done = client.post('/api/password-reset/confirm', headers=H, json=dict(username='alice', code=code, new_password='another-long-password', new_password_confirmation='another-long-password'))
    assert done.status_code == 200 and store.login('alice', 'another-long-password')
    assert rows(store, 'mail_outbox', "sent IS NOT NULL")[-1]['body'] == ''            # The sent code is not kept.


def test_recovery_by_mail_works_alongside_telegram_and_when_mail_is_off(setup):
    store, worker, outbox, client = setup
    worker.background();signup(client)
    user = rows(store, 'users')[0]['id']
    with store.db() as db:
        db.execute('UPDATE users SET email_verified=1 WHERE id=?', (user,))
        db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,1,?)', (user, 9, 'a', 'en', time.time()))
    client.post('/api/password-reset/request', headers=H, json=dict(username='alice'))
    chat = rows(store, 'telegram_outbox', 'chat_id=9')
    mail = [m for m in rows(store, 'mail_outbox') if 'recovery code' in m['subject']]
    assert len(chat) == 1 and len(mail) == 1
    assert re.search(r'\d{8}', chat[0]['text']).group(0) in mail[0]['body'] and 'recovery code' in mail[0]['subject']   # Same code, Telegram language.
    with store.db() as db:db.execute("DELETE FROM service_gate WHERE name='mail:enabled'");db.execute('DELETE FROM password_resets');db.execute('DELETE FROM mail_outbox')
    client.post('/api/password-reset/request', headers=H, json=dict(username='alice'))
    assert rows(store, 'mail_outbox') == [] and len(rows(store, 'telegram_outbox', 'chat_id=9')) == 2   # Mail off: Telegram still works.


def test_failed_sends_retry_with_backoff_and_stop_after_five_attempts(setup):
    store, worker, outbox, client = setup
    worker.background();signup(client)
    outbox.fail = True
    now = time.time()
    for attempt in range(1, 8):
        send_pending(store, worker.mailer, now)
        now += 3700
    row = rows(store, 'mail_outbox')[0]
    assert row['attempts'] == 5 and row['sent'] is None and outbox.messages == []
    outbox.fail = False
    assert send_pending(store, worker.mailer, now) == 0                                 # Gave up; nothing is sent forever.
    with store.db() as db:db.execute('UPDATE mail_outbox SET attempts=2,next_at=0')
    assert send_pending(store, worker.mailer, now) == 1 and len(outbox.messages) == 1


def license_document(license_id, ends):
    from capital_plans import iso
    return json.dumps(dict(payload=dict(license_id=license_id, expires_at=iso(ends)), signature='x'))


def test_expiry_reminders_once_per_license_and_threshold_on_each_available_channel(setup):
    store, worker, outbox, client = setup
    worker.background()
    now = time.time()
    users = {}
    for name, lang in (('alice', 'fa'), ('bob', 'en'), ('carol', 'fa')):
        users[name] = store.create_user(name, PASSWORD, name + '@example.com')
    eternal = store.create_user('dave', PASSWORD, 'dave@example.com')
    with store.db() as db:
        db.execute('UPDATE users SET email_verified=1 WHERE id IN (?,?)', (users['alice'], users['bob']))
        db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,1,?)', (users['bob'], 77, 'b', 'en', now))
        for name, ends in (('alice', now + 6.5 * 86400), ('bob', now + 6 * 86400), ('carol', now + 5 * 86400)):
            db.execute('INSERT INTO capital_licenses VALUES(?,?,?,?)', (users[name], 'acct-' + name, license_document('lic-' + name, ends), now))
        db.execute('INSERT INTO capital_licenses VALUES(?,?,?,?)', (eternal, 'acct-dave', license_document('lic-dave', now + 40 * 86400), now))
    with store.db() as db:db.execute("DELETE FROM service_gate WHERE name='reminders:last'")   # The worker's own empty run set the daily gate.
    assert queue_expiry_reminders(store, ORIGIN, now) == 2                                # carol has no channel; dave is far away.
    sent = {r['to_address']: r for r in rows(store, 'mail_outbox')}
    assert set(sent) == {'alice@example.com', 'bob@example.com'}
    assert 'Avina subscription ends in 7' in sent['bob@example.com']['subject'] and 'اشتراک آوینای شما' in sent['alice@example.com']['subject'] + sent['alice@example.com']['body']   # Persian by default, Telegram language otherwise.
    assert 'https://avina.example/en/dashboard/' in sent['bob@example.com']['body']
    chat = rows(store, 'telegram_outbox', 'chat_id=77')
    assert len(chat) == 1 and 'Your Avina subscription ends' in chat[0]['text']
    at = lambda t: (send_pending(store, worker.mailer, t), queue_expiry_reminders(store, ORIGIN, t))[1]   # The worker keeps the mail gate fresh as time moves on.
    assert at(now + 3600) == 0                         # Daily gate.
    assert at(now + 86400 + 1) == 0                   # Deduplicated per license and threshold.
    # Carol links Telegram later and still gets her reminder; the 1-day threshold follows for everyone.
    with store.db() as db:db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,1,?)', (users['carol'], 88, 'c', 'fa', now))
    assert at(now + 2 * 86400 + 5) == 1
    assert len(rows(store, 'telegram_outbox', 'chat_id=88')) == 1
    assert at(now + 5.5 * 86400 + 10) == 2             # alice and bob are now inside one day: only the 1-day message.
    days = sorted(r['threshold'] for r in rows(store, 'expiry_reminders', f"user_id='{users['alice']}'"))
    assert days == [1, 7] and len(rows(store, 'mail_outbox', "to_address='alice@example.com'")) == 2
    assert at(now + 7 * 86400) == 0                    # Expired licenses are not reminded.


def test_addresses_and_headers_reject_line_breaks_and_templates_carry_no_user_text():
    for bad in ('a@example.com\r\nBcc: x@evil.example', 'a@example.com\n', 'a b@example.com', 'a@@example.com'):
        with pytest.raises(ValueError):safe_address(bad)
    mailer = Mailer('smtp.example', 587, '', '', 'Avina <noreply@avina.example>', sender=lambda m: None)
    with pytest.raises(ValueError):mailer.message('a@example.com\r\nBcc: x@evil.example', 's', 'b')
    with pytest.raises(ValueError):mailer.message('a@example.com', 'subject\r\nBcc: x@evil.example', 'b')
    assert not Mailer('smtp.example', 587, '', '', 'Avina <noreply@avina.example>\r\nBcc: x@evil.example').configured
    assert not Mailer('', 587, '', '', 'noreply@avina.example').configured and not Mailer('smtp.example', 587, '', '', 'not an address').configured
    with pytest.raises(MailError):Mailer().send('a@example.com', 's', 'b')
    subject, body = render('reset', 'en', code='12345678')
    assert '12345678' in body and '\n' not in subject
    assert render('verify', 'zz', link='L')[0] == render('verify', 'fa', link='L')[0]


def test_smtp_transport_uses_starttls_or_ssl_with_login(monkeypatch):
    log = []

    class Client:
        def __init__(self, host, port, timeout=None, context=None):log.append(('connect', type(self).__name__, host, port, context is not None))
        def __enter__(self):return self
        def __exit__(self, *a):return False
        def ehlo(self):log.append('ehlo')
        def starttls(self, context=None):log.append(('starttls', isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED))
        def login(self, user, password):log.append(('login', user, password))
        def send_message(self, message):log.append(('send', message['To']))

    class Plain(Client):pass

    class Secure(Client):pass
    monkeypatch.setattr(portal_mail.smtplib, 'SMTP', Plain);monkeypatch.setattr(portal_mail.smtplib, 'SMTP_SSL', Secure)
    Mailer('smtp.example', 587, 'user', 'pw', 'noreply@avina.example').send('a@example.com', 's', 'b')
    assert log == [('connect', 'Plain', 'smtp.example', 587, False), 'ehlo', ('starttls', True), 'ehlo', ('login', 'user', 'pw'), ('send', 'a@example.com')]
    log.clear()
    Mailer('smtp.example', 465, '', '', 'noreply@avina.example').send('a@example.com', 's', 'b')
    assert log == [('connect', 'Secure', 'smtp.example', 465, True), ('send', 'a@example.com')]
    monkeypatch.setattr(portal_mail.smtplib, 'SMTP', lambda *a, **k: (_ for _ in ()).throw(OSError('refused')))
    with pytest.raises(MailError):Mailer('smtp.example', 25, '', '', 'noreply@avina.example').send('a@example.com', 's', 'b')


def test_mailer_reads_the_password_from_a_secret_file(tmp_path):
    secret = tmp_path / 'smtp';secret.write_text('s3cret\n')
    mailer = Mailer.from_env(dict(SMTP_HOST='h', SMTP_PORT='465', SMTP_USER='u', SMTP_PASSWORD_FILE=str(secret), SMTP_FROM='noreply@avina.example'))
    assert (mailer.host, mailer.port, mailer.user, mailer.password, mailer.configured) == ('h', 465, 'u', 's3cret', True)
    assert not Mailer.from_env({}).configured
