"""Keys that can withdraw are refused where the exchange reports permissions; elsewhere the customer must confirm."""
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from db_targets import TARGETS, fresh_store
from portal_exchanges import MultiExchangeReader, WithdrawalEnabled, catalog, withdrawal_enabled, UnsupportedAccount
from portal_jobs import AccountQueue
from portal_server import create_app
from portal_store import PortalStore
from portal_worker import AccountWorker
from test_multi_exchange import FakeClient

ORIGIN = 'https://portal.test';PASSWORD = 'long-user-password'


class Perm(FakeClient):
    withdraw = False
    binance_reply = None
    okx_perm = 'read_only,trade'

    def sapiGetAccountApiRestrictions(self):
        return self.binance_reply if self.binance_reply is not None else dict(enableReading=True, enableWithdrawals=self.withdraw)

    def privateGetAccountConfig(self):
        return dict(code='0', data=[dict(perm='read_only,withdraw,trade' if self.withdraw else self.okx_perm)])


def reader(withdraw=False, **extra):
    made = []

    def factory(name, params):
        client = Perm(name, params)
        client.withdraw = withdraw
        for key, value in extra.items():setattr(client, key, value)
        made.append(client)
        return client
    return MultiExchangeReader(factory), made


def connection(exchange_id, market='spot'):
    return dict(exchange_id=exchange_id, market=market, api_key='user-owned-api-key', secret='user-owned-secret', passphrase='pp')


@pytest.mark.parametrize('exchange_id,market', [('binance', 'spot'), ('binance', 'futures'), ('okx', 'spot'), ('okx', 'futures')])
def test_withdrawal_key_is_refused_before_any_balance_is_read(exchange_id, market):
    r, made = reader(withdraw=True)
    with pytest.raises(WithdrawalEnabled):r.snapshot(connection(exchange_id, market))
    assert all(not c.calls for c in made) and all(c.closed for c in made)   # No balance or position call was made.
    r, made = reader(withdraw=False)
    assert r.snapshot(connection(exchange_id, market))['balances']


def test_binance_futures_checks_permissions_on_the_binance_client():
    r, made = reader()
    r.snapshot(connection('binance', 'futures'))
    assert [c.name for c in made] == ['binanceusdm', 'binance'] and all(c.closed for c in made)


@pytest.mark.parametrize('exchange_id,bad', [('binance', {}), ('binance', {'enableWithdrawals': 'false'})])
def test_unreadable_permission_reports_are_never_treated_as_safe(exchange_id, bad):
    r, _ = reader(binance_reply=bad)
    with pytest.raises(ValueError):r.snapshot(connection(exchange_id))


def test_okx_permission_parsing_is_exact():
    class Client:
        def __init__(self, perm):self.perm = perm
        def privateGetAccountConfig(self):return dict(data=[dict(perm=self.perm)])
    assert withdrawal_enabled('okx', Client('read_only, withdraw')) is True
    assert withdrawal_enabled('okx', Client('read_only,trade')) is False
    assert withdrawal_enabled('okx', Client('withdrawals_pending')) is False
    with pytest.raises(UnsupportedAccount):withdrawal_enabled('bybit', Client('x'))
    with pytest.raises(ValueError):withdrawal_enabled('okx', type('C', (), {'privateGetAccountConfig': lambda self: dict(data=[])})())


def test_catalog_says_which_exchanges_report_permissions():
    flags = {e['id']: e['permission_check'] for e in catalog()}
    assert flags['binance'] and flags['okx'] and not flags['bybit'] and not flags['lbank'] and not flags['thetruetrade']


def test_worker_marks_refused_key_wipes_credentials_and_does_not_read_again(tmp_path):
    store = PortalStore(tmp_path / 'p.db', Fernet.generate_key())
    try:
        user = store.create_user('alice', PASSWORD, 'a@example.com')
        store.save_connection(user, 'spot', 'alice-api-key', 'alice-secret-value', 'binance')
        queue = AccountQueue(store);queue.enqueue(user)
        r, made = reader(withdraw=True)
        assert AccountWorker(store, r, interval=0).once()
        cache = store.cache(user)
        assert cache['status'] == 'withdrawal_enabled' and cache['snapshot'] is None
        stored = store.connection(user, decrypt=True)
        assert stored['api_key'] == '' and stored['secret'] == ''           # The refused key is not kept.
        with store.db() as db:
            assert 'connection_refused_withdrawal' in [x['event'] for x in db.execute('SELECT event FROM audit WHERE user_id=?', (user,)).fetchall()]
            db.execute('UPDATE account_cache SET checked=1')
        queue.enqueue(user)
        calls_before = sum(len(c.calls) for c in made)
        assert AccountWorker(store, r, interval=0).once() and store.cache(user)['status'] == 'withdrawal_enabled'
        assert sum(len(c.calls) for c in made) == calls_before
    finally:store.close()


def login(client, name='alice'):
    r = client.post('/api/login', headers={'X-Portal-Request': '1'}, json=dict(username=name, password=PASSWORD))
    assert r.status_code == 200
    return {'X-Portal-Request': '1', 'X-CSRF-Token': r.json()['csrf']}


def test_form_requires_the_acknowledgement_where_permissions_cannot_be_read_and_stores_it(tmp_path):
    store = PortalStore(tmp_path / 'p.db', Fernet.generate_key())
    user = store.create_user('alice', PASSWORD, 'a@example.com')
    try:
        with TestClient(create_app(store, origin=ORIGIN, secure=True), base_url=ORIGIN) as client:
            h = login(client)
            body = dict(exchange_id='bybit', market='spot', api_key='alice-api-key', secret='alice-secret-value')
            refused = client.put('/api/me/connection', headers=h, json=body)
            assert refused.status_code == 422 and 'withdrawal' in refused.json()['detail']
            assert client.put('/api/me/connection', headers=h, json=dict(body, no_withdrawal_ack=False)).status_code == 422
            assert not store.connection(user)
            assert client.put('/api/me/connection', headers=h, json=dict(body, no_withdrawal_ack=True)).status_code == 200
            # Exchanges whose permissions are read from the exchange need no tick, and no acknowledgement is recorded for them.
            assert client.put('/api/me/connection', headers=h, json=dict(body, exchange_id='binance')).status_code == 200
            exchanges = client.get('/api/exchanges').json()['exchanges']
            assert {e['id']: e['permission_check'] for e in exchanges}['binance'] is True
        with store.db() as db:
            events = [x['event'] for x in db.execute("SELECT event FROM audit WHERE event LIKE 'connection_saved%' ORDER BY id").fetchall()]
        assert events == ['connection_saved:no_withdrawal_ack', 'connection_saved']
    finally:store.close()


@pytest.mark.parametrize('backend', TARGETS)
def test_refusal_rolls_back_the_key_and_job_together(backend, tmp_path, monkeypatch):
    store = fresh_store(backend, tmp_path)
    try:
        owner = store.create_user('alice', PASSWORD)
        store.save_connection(owner, 'spot', 'fixture-key', 'fixture-secret', 'binance')
        queue = AccountQueue(store)
        queue.enqueue(owner)
        job = queue.claim(interval=0)
        wipe = store.wipe_connection_in_transaction

        def interrupted(*args):
            wipe(*args)
            raise RuntimeError('test interruption')

        with monkeypatch.context() as patch:
            patch.setattr(store, 'wipe_connection_in_transaction', interrupted)
            with pytest.raises(RuntimeError, match='test interruption'):
                queue.finish(job, None, 'withdrawal_enabled', wipe_refused_key=True)
        assert store.connection(owner, decrypt=True)['api_key'] == 'fixture-key'
        assert store.cache(owner)['status'] == 'refreshing'
        assert queue.finish(job, None, 'withdrawal_enabled', wipe_refused_key=True)
        assert store.connection(owner, decrypt=True)['api_key'] == ''
        assert store.cache(owner)['status'] == 'withdrawal_enabled'
    finally:
        store.close()
