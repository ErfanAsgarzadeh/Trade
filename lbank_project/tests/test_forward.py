"""Forward test: summary from fixture runtimes (formats written by lbank_bot.py, c3_sleeve.py, pa_sleeve.py), API, privacy."""
import json
import sqlite3
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_forward
from portal_forward import ForwardTest, PUBLIC_KEYS, BOT_KEYS, compute, public
from portal_server import create_app
from portal_store import PortalStore
from totp_helpers import enable_totp, extra

DAY = 86400
ORIGIN = 'https://portal.test'
PASSWORD = 'disposable-test-password'
CLOSES = [10050, 10150, 10100, 9900, 9950, 10200, 10400, 10300, 10250, 10500, 10600, 10550, 10400, 10700, 10800, 10750, 10900, 11000, 11100]


def build_runtime(root, today, closes=CLOSES, history=True, initial=10000.0, partial_line=True):
    """equity_history.jsonl ({"t","equity"}), main trade_history/runtime, C3 and PA trades tables, as the bots create them."""
    root.mkdir(parents=True, exist_ok=True)
    start = today - len(closes) * DAY
    if history:
        lines = [json.dumps({'t': start + 10 * 3600, 'equity': initial})]
        lines += [json.dumps({'t': start + (k + 1) * DAY - 3600, 'equity': v}) for k, v in enumerate(closes)]
        lines.append(json.dumps({'t': today + 3600, 'equity': 99999.0}))  # today: must never be published
        text = '\n'.join(lines) + '\n'
        if partial_line:
            text += '{"t": 17'  # being written right now
        (root / 'equity_history.jsonl').write_text(text)
    at = lambda k: start + k * DAY + 5 * 3600
    with sqlite3.connect(root / 'lbank_ichimoku_bot.db') as db:
        db.execute('CREATE TABLE trade_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL, pnl_usd REAL NOT NULL, closed_at INTEGER NOT NULL, qty REAL NOT NULL, entry_price REAL NOT NULL, exit_price REAL NOT NULL, reason TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 1)')
        db.execute('CREATE TABLE runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO runtime VALUES('paper_initial_equity',?)", (str(initial),))
        for k, pnl, dry in ((1, 100, 1), (2, -50, 1), (3, 200, 1), (4, -100, 1), (5, 999, 0), (len(closes) + 1, 777, 1)):
            db.execute('INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason,dry_run) VALUES(?,?,?,?,?,?,?,?,?)',
                       ('BTC/USDT:USDT', 'long', pnl, int(at(k)) if k <= len(closes) else int(today + 60), 1.5, 61234.5, 62000.25, 'tp1', dry))
    for name, rows in (('c3_sleeve.db', ((2, 50), (5, -25))), ('pa_sleeve.db', ((3, 30),))):
        with sqlite3.connect(root / name) as db:
            db.execute('CREATE TABLE trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,entry REAL,exit REAL,qty REAL,opened REAL,closed REAL,pnl REAL,reason TEXT)')
            for k, pnl in rows:
                db.execute('INSERT INTO trades(symbol,side,entry,exit,qty,opened,closed,pnl,reason) VALUES(?,?,?,?,?,?,?,?,?)',
                           ('ETH/USDT:USDT', 'short', 3111.1, 3000.9, 2.5, at(k) - 100, at(k), pnl, 'stop'))
    return root


def midnight(ts=None):
    return int((time.time() if ts is None else ts) // DAY) * DAY


@pytest.fixture
def store(tmp_path):
    s = PortalStore(tmp_path / 'portal.db', Fernet.generate_key())
    yield s
    s.close()


def test_summary_numbers_from_fixture_runtime(tmp_path):
    today = midnight(1_781_000_000)
    root = build_runtime(tmp_path / 'rt', today)
    summary = compute(root, today + 12 * 3600)
    assert summary['available'] and not summary['collecting']
    assert summary['days'] == 19 and summary['equity_basis'] == 'mark_to_market'
    assert summary['data_through'] == time.strftime('%Y-%m-%d', time.gmtime(today - 1))
    assert summary['current_index'] == 111.0 and summary['total_return_pct'] == 11.0
    assert summary['max_drawdown_pct'] == round((9900 / 10150 - 1) * 100, 2)
    assert summary['best_day_pct'] == round((10700 / 10400 - 1) * 100, 2)
    assert summary['worst_day_pct'] == round((9900 / 10100 - 1) * 100, 2)
    assert summary['trades'] == 7  # the non-paper row and today's row are excluded
    assert summary['win_rate_pct'] == round(4 / 7 * 100, 1)
    assert summary['profit_factor'] == round(380 / 175, 2)
    assert len(summary['series']) == 19 and summary['series'][-1]['v'] == 111.0
    bots = {b['id']: b for b in summary['bots']}
    assert [b['id'] for b in summary['bots']] == ['falcon', 'wave_rider', 'phoenix']
    assert bots['falcon']['trades'] == 4 and bots['falcon']['win_rate_pct'] == 50.0 and bots['falcon']['contribution_pct'] == 1.5
    assert bots['wave_rider']['trades'] == 2 and bots['phoenix']['trades'] == 1 and bots['phoenix']['win_rate_pct'] == 100.0
    assert sum(m['r'] for m in summary['monthly']) != 0 and all(len(m['m']) == 7 for m in summary['monthly'])


def test_public_json_has_only_allow_listed_keys_and_no_method_or_size_leak(tmp_path):
    today = midnight(1_781_000_000)
    out = public(compute(build_runtime(tmp_path / 'rt', today), today + 100))
    assert set(out) <= PUBLIC_KEYS
    assert all(set(b) <= BOT_KEYS for b in out['bots'])
    text = json.dumps(out, ensure_ascii=False)
    for secret in ('BTC', 'ETH', 'USDT', '61234', '62000', '3111', 'tp1', 'stop', '10000', '99999', 'dry_run', 'symbol', 'entry', 'qty'):
        assert secret not in text, secret


def test_realized_fallback_when_no_equity_history(tmp_path):
    today = midnight(1_781_000_000)
    summary = compute(build_runtime(tmp_path / 'rt', today, history=False), today + 5)
    assert summary['equity_basis'] == 'realized'
    # 100 + 50 + 200 - 100 ... cumulative realised P&L of paper rows over 10000
    assert summary['current_index'] == round(100 + (100 - 50 + 200 - 100 + 50 - 25 + 30) / 10000 * 100, 2)


def test_empty_partial_and_missing_inputs_do_not_raise(tmp_path):
    today = midnight(1_781_000_000)
    empty = tmp_path / 'empty';empty.mkdir()
    assert compute(empty, today) is None
    (empty / 'equity_history.jsonl').write_text('{"t": 5')
    assert compute(empty, today) is None
    (empty / 'lbank_ichimoku_bot.db').write_bytes(b'not a database')
    assert compute(empty, today) is None
    # one bot database missing and a half-written history line are tolerated
    root = build_runtime(tmp_path / 'rt', today)
    (root / 'pa_sleeve.db').unlink()
    summary = compute(root, today + 1)
    assert summary['trades'] == 6
    assert public(None) == {'available': False}


def test_fewer_than_seven_days_is_the_collecting_state_without_statistics(tmp_path):
    today = midnight(1_781_000_000)
    root = build_runtime(tmp_path / 'rt', today, closes=[10010, 10020, 10030])
    out = public(compute(root, today + 1))
    assert out == dict(available=False, collecting=True, days=3, start_date=out['start_date'])


def test_not_configured_reports_unavailable(store, monkeypatch, tmp_path):
    monkeypatch.setenv('PORTAL_FORWARD_TEST_DIR', str(tmp_path / 'nope'))
    assert ForwardTest(store).summary() == {'available': False}
    monkeypatch.delenv('PORTAL_FORWARD_TEST_DIR')
    assert ForwardTest(store, directory=str(tmp_path / 'nope')).summary() == {'available': False}


def test_cache_for_five_minutes_snapshot_and_survival_after_rotation(store, tmp_path):
    today = midnight(1_781_000_000)
    root = build_runtime(tmp_path / 'rt', today)
    now = [today + 3600]
    service = ForwardTest(store, directory=str(root), clock=lambda: now[0])
    first = service.summary()
    assert first['available'] and first['days'] == 19
    with store.db() as db:
        rows = db.execute('SELECT day,payload FROM forward_snapshots').fetchall()
    assert len(rows) == 1 and rows[0]['day'] == first['data_through']
    assert set(json.loads(rows[0]['payload'])) <= PUBLIC_KEYS
    (root / 'equity_history.jsonl').unlink()
    for name in ('lbank_ichimoku_bot.db', 'c3_sleeve.db', 'pa_sleeve.db'):(root / name).unlink()
    now[0] += 200
    assert service.summary() == first  # cached
    now[0] += 200  # more than 5 minutes after the first computation
    survived = service.summary()
    assert survived['available'] and survived['total_return_pct'] == 11.0 and set(survived) <= PUBLIC_KEYS
    status = service.admin_status()
    assert status['directory_found'] and status['last_snapshot'] == first['data_through'] and not status['hidden']


@pytest.fixture
def api(tmp_path, monkeypatch):
    s = PortalStore(tmp_path / 'portal.db', Fernet.generate_key())
    s.create_user('manager', PASSWORD);s.set_admin('manager');enable_totp(s, 'manager')
    root = build_runtime(tmp_path / 'rt', midnight())
    monkeypatch.setenv('PORTAL_FORWARD_TEST_DIR', str(root))
    with TestClient(create_app(s, origin=ORIGIN), base_url=ORIGIN) as client:
        yield client, s
    s.close()


def admin_headers(client):
    r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN},
                    json=dict(username='manager', password=PASSWORD, **extra('manager')))
    assert r.status_code == 200, r.text
    return {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}


def test_public_api_is_cacheable_allow_listed_and_hideable(api):
    client, store = api
    r = client.get('/api/forward-test')
    assert r.status_code == 200 and r.headers['cache-control'] == 'public, max-age=300'
    body = r.json()
    assert body['available'] is True and set(body) <= PUBLIC_KEYS and body['days'] == 19
    assert '/forward-test/' in client.get('/sitemap.xml').text
    assert client.get('/api/admin/forward-test').status_code == 401
    headers = admin_headers(client)
    status = client.get('/api/admin/forward-test').json()
    assert status['directory_found'] and status['days'] == 19 and status['hidden'] is False
    assert client.put('/api/admin/forward-test', headers=headers, json={'hidden': True, 'x': 1}).status_code == 422
    assert client.put('/api/admin/forward-test', headers=headers, json={'hidden': True}).json()['hidden'] is True
    assert client.get('/api/forward-test').json() == {'available': False}
    sitemap = client.get('/sitemap.xml').text
    assert '/forward-test/' not in sitemap
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM admin_events WHERE action='forward_test.hide'").fetchone()['n'] == 1
    client.put('/api/admin/forward-test', headers=headers, json={'hidden': False})
    assert client.get('/api/forward-test').json()['available'] is True


def test_customer_cannot_flip_the_switch(api):
    client, store = api
    store.create_user('alice', PASSWORD)
    r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='alice', password=PASSWORD))
    h = {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}
    assert client.put('/api/admin/forward-test', headers=h, json={'hidden': True}).status_code == 403
    assert client.get('/api/admin/forward-test').status_code == 403


def test_api_unavailable_without_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('PORTAL_FORWARD_TEST_DIR', str(tmp_path / 'missing'))
    s = PortalStore(tmp_path / 'p.db', Fernet.generate_key())
    with TestClient(create_app(s, origin=ORIGIN), base_url=ORIGIN) as client:
        assert client.get('/api/forward-test').json() == {'available': False}
    s.close()
