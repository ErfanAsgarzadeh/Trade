"""Housekeeping, the owner's watchdog and health endpoint, and the payment endpoint check."""
import json
import sys
import threading
import time
import urllib.error
import uuid

from fastapi.testclient import TestClient
import pytest

import portal_housekeeping
import portal_payments
import portal_watchdog
from portal_billing import Billing
from portal_housekeeping import DAY, housekeeping
from portal_payments import Payments, check_endpoints, check_main, DEFAULTS
from portal_server import create_app
from portal_telegram import Telegram, Worker
from pricing_helpers import enable_test_prices
from db_targets import TARGETS, fresh_store
from totp_helpers import enable_totp

ORIGIN = 'https://avina.example';PASSWORD = 'disposable-test-password'


@pytest.fixture(params=TARGETS)
def store(request, tmp_path):
    store = fresh_store(request.param, tmp_path)
    store.create_user('manager', PASSWORD, 'm@example.com');store.set_admin('manager');enable_totp(store, 'manager')
    store.create_user('alice', PASSWORD, 'a@example.com')
    enable_test_prices(store)
    yield store
    store.close()


def uid(store, name):
    with store.db() as db:return db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()['id']


def count(store, table, where='1=1'):
    with store.db() as db:return db.execute(f'SELECT COUNT(*) AS n FROM {table} WHERE {where}').fetchone()['n']


def make_order(store, name='alice'):
    user = uid(store, name);billing = Billing(store);quote = billing.quote(user, 10000, 1, product='signals')
    return user, billing.order(user, 10000, 1, 'subscription', str(uuid.uuid4()), quote['price_cents'], product='signals')['id']


def transfer(db, ref, status, seen):
    db.execute('INSERT INTO payment_transfers(tx_ref,network,token,from_address,to_address,amount_micro,block_time,seen,invoice_id,status) '
               "VALUES(?,'tron','USDT','a','b',1000000,?,?,NULL,?)", (ref, seen, seen, status))


def test_housekeeping_deletes_only_what_is_stale_and_runs_once_a_day(store):
    now = time.time();old = now - 401 * DAY;user = uid(store, 'alice');manager = uid(store, 'manager')
    owner, order_id = make_order(store)
    with store.db() as db:
        sql = lambda q, *a: db.execute(q, a)
        sql('INSERT INTO sessions VALUES(?,?,?,?)', 'expired-s', user, 'c', now - 5);sql('INSERT INTO sessions VALUES(?,?,?,?)', 'live-s', user, 'c', now + 500)
        sql('INSERT INTO telegram_link_codes VALUES(?,?,?,?)', 'old-code', user, 'fa', now - 5);sql('INSERT INTO telegram_link_codes VALUES(?,?,?,?)', 'new-code', manager, 'fa', now + 500)
        sql('INSERT INTO password_resets VALUES(?,?,?,0,?)', user, 'h', now - 5, now - 900)
        sql('INSERT INTO email_tokens VALUES(?,?,?,?,?)', 'old-t', manager, 'm@example.com', now - 9e4, now - 5)
        sql('INSERT INTO login_limits VALUES(?,?,?,?,?,?)', 'olduser', 1, now, 0, 0, now - 2 * DAY);sql('INSERT INTO login_limits VALUES(?,?,?,?,?,?)', 'newuser', 1, now, 0, 0, now - 100)
        sql('INSERT INTO attempts VALUES(?,?,1)', 'old-client', now - 2 * 3600);sql('INSERT INTO attempts VALUES(?,?,1)', 'new-client', now - 30)
        sql('INSERT INTO telegram_outbox(id,chat_id,text,created,sent) VALUES(?,?,?,?,?)', 'sent-old', 1, 't', now - 9 * DAY, now - 8 * DAY)
        sql('INSERT INTO telegram_outbox(id,chat_id,text,created,sent) VALUES(?,?,?,?,?)', 'sent-new', 1, 't', now - 9 * DAY, now - 6 * DAY)
        sql('INSERT INTO telegram_outbox(id,chat_id,text,created,sent) VALUES(?,?,?,?,NULL)', 'unsent-old', 1, 't', now - 9 * DAY)
        sql('INSERT INTO telegram_signal_sent VALUES(?,?,?)', user, 'old-sig', now - 8 * DAY);sql('INSERT INTO telegram_signal_sent VALUES(?,?,?)', user, 'new-sig', now - DAY)
        sql('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', user, 'old-event', old);sql('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', user, 'new-event', now - 399 * DAY)
        transfer(db, 'tron:old-unmatched', 'unmatched', old);transfer(db, 'tron:new-unmatched', 'unmatched', now - 399 * DAY);transfer(db, 'tron:old-matched', 'matched', old)
        sql('INSERT INTO admin_events(id,actor_id,action,target,details,at) VALUES(?,?,?,?,?,?)', 'ae', manager, 'old_action', 't', '{}', old)
        sql('INSERT INTO mail_outbox(id,to_address,subject,body,created) VALUES(?,?,?,?,?)', 'old-mail', 'a@example.com', 's', 'b', now - 8 * DAY)
    result = housekeeping(store, now)
    assert result and all(result[t] >= 1 for t in ('sessions', 'telegram_link_codes', 'password_resets', 'email_tokens', 'login_limits', 'attempts',
                                                  'telegram_outbox', 'telegram_signal_sent', 'audit', 'payment_transfers', 'mail_outbox'))
    assert count(store, 'sessions', "token_hash='expired-s'") == 0 and count(store, 'sessions', "token_hash='live-s'") == 1
    assert count(store, 'telegram_link_codes') == 1 and count(store, 'password_resets') == 0 and count(store, 'email_tokens') == 0
    assert count(store, 'login_limits', "username='olduser'") == 0 and count(store, 'login_limits', "username='newuser'") == 1
    assert count(store, 'attempts', "client='old-client'") == 0 and count(store, 'attempts', "client='new-client'") == 1
    assert count(store, 'telegram_outbox', "id='sent-old'") == 0 and count(store, 'telegram_outbox', "id IN ('sent-new','unsent-old')") == 2
    assert count(store, 'telegram_signal_sent') == 1 and count(store, 'audit', "event='old-event'") == 0 and count(store, 'audit', "event='new-event'") == 1
    assert count(store, 'payment_transfers', "tx_ref='tron:old-unmatched'") == 0
    assert count(store, 'payment_transfers', "tx_ref IN ('tron:new-unmatched','tron:old-matched')") == 2   # Matched transfers are never deleted.
    assert count(store, 'admin_events', "id='ae'") == 1 and count(store, 'license_orders', f"id='{order_id}'") == 1 and count(store, 'users') == 2
    assert housekeeping(store, now + 3600) is None                       # Not due again for 24 hours.
    assert housekeeping(store, now + DAY + 1) is not None


def test_only_one_process_runs_the_daily_cleanup(store):
    if not store.database.postgres:pytest.skip('Concurrency is a PostgreSQL concern; SQLite serialises writers')
    now = time.time();results = []
    threads = [threading.Thread(target=lambda: results.append(housekeeping(store, now))) for _ in range(4)]
    [t.start() for t in threads];[t.join() for t in threads]
    assert sum(r is not None for r in results) == 1


def admin_chat(store, chat=111, lang='en'):
    with store.db() as db:
        db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,1,?)', (uid(store, 'manager'), chat, 'm', lang, time.time()))
    return chat


def messages(store, chat=111):
    with store.db() as db:return [r['text'] for r in db.execute('SELECT text FROM telegram_outbox WHERE chat_id=? ORDER BY created,id', (chat,)).fetchall()]


def gate(store, name, value):
    with store.db() as db:
        db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at', (name, value))


def configure(store):
    Payments(store).save_settings(uid(store, 'manager'), dict(tron_address='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
                                                              bsc_address='0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed', invoice_minutes=60))
    with store.db() as db:db.execute('DELETE FROM telegram_outbox')   # The wallet-change notices are not under test here.


def test_quiet_site_reports_nothing(store):
    admin_chat(store)
    assert portal_watchdog.run(store) == dict(opened=[], cleared=[]) and messages(store) == []
    assert all(c['ok'] for c in portal_watchdog.health(store))


def test_payment_worker_alert_is_sent_once_and_clears_with_one_recovery_message(store):
    admin_chat(store);configure(store);now = time.time() + 3600   # The addresses were saved an hour ago.
    gate(store, 'payments:heartbeat', now - 400);gate(store, 'payments:ok:tron', now - 10);gate(store, 'payments:ok:bsc', now - 10)
    assert portal_watchdog.run(store, now)['opened'] == ['payment_worker']
    assert portal_watchdog.run(store, now + 60) == dict(opened=[], cleared=[])
    assert portal_watchdog.run(store, now + 120) == dict(opened=[], cleared=[]) and len(messages(store)) == 1
    assert messages(store)[0].startswith('🚨 Avina: The payment worker is not responding')
    health = {c['key']: c for c in portal_watchdog.health(store, now + 120)}
    assert not health['payment_worker']['ok'] and health['payment_worker']['since'] == pytest.approx(now - 400)
    gate(store, 'payments:heartbeat', now + 130)
    assert portal_watchdog.run(store, now + 140)['cleared'] == ['payment_worker']
    assert len(messages(store)) == 2 and messages(store)[1].startswith('✅ Avina: resolved')
    assert portal_watchdog.run(store, now + 200) == dict(opened=[], cleared=[]) and len(messages(store)) == 2


def test_each_condition_has_its_own_incident(store):
    admin_chat(store);configure(store);now = time.time() + 3600
    gate(store, 'payments:heartbeat', now);gate(store, 'payments:ok:tron', now - 1000);gate(store, 'payments:ok:bsc', now)
    gate(store, 'payments:verify_failures', 3);gate(store, 'payments:verify_failed_at', now - 60)
    user, order_id = make_order(store)
    manager = uid(store, 'manager')
    with store.db() as db:
        db.execute("INSERT INTO license_approvals(id,order_id,requested_by,payload,payment_ref,state,lease_until,attempts,created,updated) VALUES(?,?,?,?,?,'queued',0,0,?,?)",
                   ('a1', order_id, manager, '{}', 'tron:x', now - 700, now - 700))
        db.execute("INSERT INTO account_jobs VALUES(?,?,'queued',NULL,0,?,0,?)", (user, 'rev', now - 900, now - 900))
        transfer(db, 'tron:orphan', 'unmatched', now - 30)
    opened = portal_watchdog.run(store, now)['opened']
    assert set(opened) == {'payment_check_tron', 'payment_verify', 'issuer_heartbeat', 'approval_stuck', 'unmatched_transfer', 'account_queue'}
    assert len(messages(store)) == 6
    # A second unmatched transfer is a new incident even though one is still open; nothing else repeats.
    with store.db() as db:transfer(db, 'tron:orphan2', 'unmatched', now + 40)
    assert portal_watchdog.run(store, now + 60)['opened'] == ['unmatched_transfer'] and len(messages(store)) == 7
    with store.db() as db:
        db.execute("UPDATE license_approvals SET state='failed',updated=? WHERE id='a1'", (now,))
    result = portal_watchdog.run(store, now + 120)
    assert 'approval_failed' in result['opened'] and set(result['cleared']) == {'issuer_heartbeat', 'approval_stuck'}
    health = {c['key']: c for c in portal_watchdog.health(store, now + 120)}
    assert not health['approval_failed']['ok'] and health['approval_failed']['since'] and health['payment_worker']['ok']
    assert set(health['approval_failed']) == {'key', 'ok', 'detail', 'since'}


def test_alerts_go_to_every_linked_admin_in_their_language(store):
    other = store.create_user('second', PASSWORD, 'x@example.com');store.set_admin('second')
    admin_chat(store, 111, 'en')
    with store.db() as db:
        db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,0,?)', (other, 222, 's', 'fa', time.time()))
    gate(store, 'payments:verify_failures', 1)
    portal_watchdog.run(store)
    assert messages(store, 111)[0].startswith('🚨 Avina: Second-source') and messages(store, 222)[0].startswith('🚨 آوینا:')   # Alerts ignore the notice preference.


def test_admin_health_endpoint_is_admin_only_and_lists_the_checks(store):
    from totp_helpers import extra
    configure(store);gate(store, 'payments:verify_failures', 2)
    with TestClient(create_app(store, origin=ORIGIN, secure=True), base_url=ORIGIN) as client:
        assert client.get('/api/admin/health').status_code == 401
        client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='alice', password=PASSWORD))
        assert client.get('/api/admin/health').status_code == 403
        client.post('/api/logout', headers={'X-Portal-Request': '1', 'Origin': ORIGIN})
        response = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='manager', password=PASSWORD, **extra('manager')))
        assert response.status_code == 200
        health = client.get('/api/admin/health')
        assert health.status_code == 200
        rows = {r['key']: r for r in health.json()}
        assert set(rows) == set(portal_watchdog.TITLES) and set(rows['payment_verify']) == {'key', 'ok', 'detail', 'since'}
        assert rows['payment_verify']['ok'] is False and rows['approval_failed']['ok'] is True


def test_worker_background_runs_watchdog_once_a_minute_and_survives_a_failing_step(store, monkeypatch):
    admin_chat(store);gate(store, 'payments:verify_failures', 1)
    worker = Worker(store, lambda: {}, mailer=type('M', (), {'configured': False})())
    ran = worker.background(now=time.time())
    assert 'watchdog' in ran and len(messages(store)) == 1
    assert 'watchdog' not in worker.background(now=time.time() + 5)           # Within the same minute.
    assert 'watchdog' in worker.background(now=time.time() + 70)
    monkeypatch.setattr(portal_watchdog, 'run', lambda *a: 1 / 0)
    assert 'watchdog' not in worker.background(now=time.time() + 200) and 'housekeeping' in worker.background(now=time.time() + 300)


# ---- python portal_payments.py --check ----------------------------------------------------------------------------------

def test_endpoint_check_reports_each_endpoint_and_exits_non_zero_on_failure():
    calls = []

    def fetch(url, payload=None, headers=None, timeout=15):
        calls.append(url)
        if 'down.example' in url:raise urllib.error.URLError('refused')
        if 'explorer.example' in url:raise urllib.error.HTTPError(url, 404, 'nf', {}, None)
        return {'result': '0x10'} if payload else {'data': []}
    settings = dict(DEFAULTS, bsc_rpc='https://rpc.example', bsc_rpc_verify='https://rpc2.example', trongrid_url='https://grid.example',
                    tron_verify_url='https://explorer.example')
    assert [ok for *_, ok in check_endpoints(settings, fetch)] == [True, True, True, True]   # An HTTP 404 still proves the explorer answers.
    results = check_endpoints(dict(settings, bsc_rpc='https://down.example'), fetch)
    assert [ok for *_, ok in results] == [False, True, True, True]
    out = []
    code = check_main(fetch=lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError('x')), out=out.append)
    assert code == 1 and sum(l.startswith('unreachable') for l in out) == 4
    code = check_main(fetch=lambda url, payload=None, **k: {'result': '0x1'} if payload else {'data': []}, out=out.append)
    assert code == 0 and any(l.startswith('reachable') for l in out)


def test_payment_proxy_variable_maps_to_https_proxy_and_check_flag_is_honoured(monkeypatch):
    monkeypatch.setenv('PAYMENT_HTTPS_PROXY', 'http://proxy.internal:3128');monkeypatch.delenv('HTTPS_PROXY', raising=False)
    monkeypatch.setattr(sys, 'argv', ['portal_payments.py', '--check'])
    monkeypatch.setattr(portal_payments, 'check_main', lambda: 3)
    with pytest.raises(SystemExit) as stop:portal_payments.main()
    assert stop.value.code == 3
    import os
    assert os.environ['HTTPS_PROXY'] == 'http://proxy.internal:3128'
    monkeypatch.delenv('HTTPS_PROXY')
