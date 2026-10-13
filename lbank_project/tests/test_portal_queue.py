from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import time

from cryptography.fernet import Fernet
import pytest

from portal_store import PortalStore
from portal_jobs import AccountQueue,MissingConnection,QueueFull,RefreshLimited
from portal_worker import AccountWorker
from portal_migrate import migrate_sqlite


@pytest.fixture(params=['sqlite','postgres'])
def store(request,tmp_path):
    key=Fernet.generate_key()
    if request.param=='postgres':
        target=os.getenv('PORTAL_TEST_DATABASE_URL')
        if not target:pytest.skip('Disposable PostgreSQL test URL not configured')
        if os.getenv('PORTAL_TEST_ALLOW_RESET')!='1':pytest.fail('Set PORTAL_TEST_ALLOW_RESET=1 ONLY for a disposable test database')
        store=PortalStore(target,key)
        with store.db() as db:
            db.execute('TRUNCATE account_jobs,service_gate,account_cache,connections,sessions,attempts,audit,users RESTART IDENTITY CASCADE')
    else:store=PortalStore(tmp_path/'portal.db',key)
    store.create_user('alice','long-test-password');store.create_user('bob','long-test-password')
    yield store
    store.close()


def owner(store,username='alice'):
    return store.session(store.login(username,'long-test-password')[0])['id']


def test_parallel_enqueue_single_job_and_parallel_claim_fencing(store):
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:AccountQueue(store).enqueue(user),range(16)))
    assert sum(not r['already_pending'] for r in results)==1
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=list(pool.map(lambda _:AccountQueue(store).claim(interval=0),range(16)))
    claimed=[c for c in claims if c];assert len(claimed)==1
    job=claimed[0];queue=AccountQueue(store)
    assert queue.finish(job,{'balances':[1]},'verified_read_only')
    assert not queue.finish(job,{'balances':['duplicate']},'verified_read_only')
    assert store.cache(user)['snapshot']=={'balances':[1]}
    with pytest.raises(RefreshLimited):queue.enqueue(user)


def test_lease_expiry_recovery_rejects_old_worker_result(store):
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret')
    queue=AccountQueue(store);queue.enqueue(user);old=queue.claim(interval=0)
    with store.db() as db:db.execute('UPDATE account_jobs SET lease_until=0 WHERE user_id=?',(user,))
    new=queue.claim(interval=0)
    assert new['attempts']==2 and new['lease_token']!=old['lease_token']
    assert not queue.finish(old,{'balances':['stale']},'verified_read_only')
    assert queue.finish(new,{'balances':['new']},'verified_read_only')


def test_rotation_disconnect_disabled_user_and_expired_lease_cannot_publish(store):
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret')
    queue=AccountQueue(store);queue.enqueue(user);job=queue.claim(interval=0)
    store.save_connection(user,'spot','new-alice-key','new-secret-value')
    assert not queue.finish(job,{'balances':['old']},'verified_read_only') and store.cache(user) is None
    queue.enqueue(user);job=queue.claim(interval=0);store.disconnect(user)
    assert not queue.finish(job,{'balances':['old']},'verified_read_only')
    with pytest.raises(MissingConnection):queue.enqueue(user)
    store.save_connection(user,'spot','alice-api-key','alice-secret');queue.enqueue(user);job=queue.claim(interval=0)
    with store.db() as db:db.execute('UPDATE account_jobs SET lease_until=0 WHERE user_id=?',(user,))
    assert not queue.finish(job,{'balances':['expired']},'verified_read_only')
    with store.db() as db:db.execute('UPDATE users SET disabled=1 WHERE id=?',(user,))
    assert queue.claim(interval=0) is None


def test_retries_bounded_backoff_and_crashed_final_attempt(store):
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret')
    queue=AccountQueue(store);queue.enqueue(user)
    for attempt in (1,2):
        job=queue.claim(interval=0);assert job['attempts']==attempt
        assert queue.finish(job,None,'verification_failed',retry=True)
        assert queue.claim(interval=0) is None
        with store.db() as db:
            row=db.execute('SELECT not_before,updated FROM account_jobs WHERE user_id=?',(user,)).fetchone()
            assert row['not_before']-row['updated']==30*2**(attempt-1)
            db.execute('UPDATE account_jobs SET not_before=0 WHERE user_id=?',(user,))
    last=queue.claim(interval=0);assert last['attempts']==3
    with store.db() as db:db.execute('UPDATE account_jobs SET lease_until=0 WHERE user_id=?',(user,))
    assert queue.claim(interval=0) is None
    assert store.cache(user)['status']=='verification_failed'
    assert queue.summary()['states']=={'failed':1}


def test_global_rate_and_capacity_shared_across_workers(store):
    a=owner(store);b=owner(store,'bob')
    for u in (a,b):store.save_connection(u,'spot','test-api-key','test-secret-value')
    AccountQueue(store,max_pending=1).enqueue(a)
    with pytest.raises(QueueFull):AccountQueue(store,max_pending=1).enqueue(b)
    AccountQueue(store,max_pending=2).enqueue(b)
    first=AccountQueue(store).claim(interval=30);assert first
    assert AccountQueue(store).claim(interval=30) is None
    with store.db() as db:db.execute("UPDATE service_gate SET next_at=0 WHERE name='account-read:lbank'")
    second=AccountQueue(store).claim(interval=30)
    assert second and second['user_id']!=first['user_id']


def test_worker_exception_retry_and_owner_keys(store):
    import ccxt
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret')
    AccountQueue(store).enqueue(user)
    class BadReader:
        def snapshot(self,c):
            assert c['api_key']=='alice-api-key'
            raise ccxt.NetworkError('Contains sensitive secret: '+c['secret'])
    assert AccountWorker(store,BadReader(),interval=0).once()
    cache=store.cache(user)
    assert cache['status']=='retrying' and 'alice-secret' not in str(cache)


def test_database_failure_during_publish_keeps_lease_for_recovery(store,monkeypatch):
    user=owner(store);store.save_connection(user,'spot','alice-api-key','alice-secret');AccountQueue(store).enqueue(user)
    class Reader:
        def snapshot(self,c):return {'balances':[]}
    worker=AccountWorker(store,Reader(),interval=0)
    original=worker.queue.finish
    def unavailable(*args,**kwargs):raise sqlite3.OperationalError('Temporary database lock')
    monkeypatch.setattr(worker.queue,'finish',unavailable)
    with pytest.raises(sqlite3.OperationalError):worker.once()
    with store.db() as db:
        assert db.execute('SELECT state FROM account_jobs WHERE user_id=?',(user,)).fetchone()['state']=='running'
        db.execute('UPDATE account_jobs SET lease_until=0 WHERE user_id=?',(user,))
    assert store.cache(user)['status']=='refreshing'
    monkeypatch.setattr(worker.queue,'finish',original)
    assert worker.once() and store.cache(user)['status']=='verified_read_only'


def test_rate_gate_independent_for_other_exchange_postgres_and_sqlite(store):
    a=owner(store);b=owner(store,'bob')
    store.save_connection(a,'spot','alice-api-key','alice-secret',exchange_id='binance')
    store.save_connection(b,'spot','bob-api-key','bob-secret',exchange_id='okx',passphrase='test-phrase')
    q=AccountQueue(store);q.enqueue(a);q.enqueue(b)
    first=q.claim(interval=30);second=q.claim(interval=30)
    assert first and second and first['exchange_id']!=second['exchange_id']
    assert q.claim(interval=30) is None


def test_http_enqueues_without_exchange_io_and_worker_finishes_separately(store):
    from fastapi.testclient import TestClient
    from portal_server import create_app
    class Reader:
        calls=0
        def snapshot(self,c):
            self.calls+=1
            return {'market':'spot','balances':[{'asset':'USDT','free':42}]}
    reader=Reader()
    with TestClient(create_app(store,origin='https://portal.test',secure=True),base_url='https://portal.test') as client:
        r=client.post('/api/login',headers={'X-Portal-Request':'1'},json={'username':'alice','password':'long-test-password'})
        assert r.status_code==200
        headers={'X-Portal-Request':'1','X-CSRF-Token':r.json()['csrf']}
        assert client.put('/api/me/connection',headers=headers,json={'market':'spot','api_key':'alice-api-key','secret':'alice-secret'}).status_code==200
        assert client.post('/api/me/connection/refresh',headers=headers).status_code==202
        assert client.post('/api/me/connection/refresh',headers=headers).json()['already_pending'] is True
        assert reader.calls==0 and client.get('/api/me/connection').json()['account']['status']=='queued'
        assert AccountWorker(store,reader,interval=0).once()
        assert reader.calls==1
        assert client.get('/api/me/connection').json()['account']['snapshot']['balances'][0]['free']==42


def test_deployment_secrets_preserve_master_key_and_reject_overwrite(tmp_path):
    from portal_setup import prepare_secrets
    from urllib.parse import urlsplit
    key=Fernet.generate_key();(tmp_path/'portal.key').write_bytes(key)
    prepare_secrets(tmp_path)
    assert (tmp_path/'portal.key').read_bytes()==key
    url=urlsplit((tmp_path/'portal_database_url').read_text().strip())
    assert url.hostname=='db' and url.password==(tmp_path/'postgres_password').read_text().strip()
    before=(tmp_path/'postgres_password').read_bytes()
    with pytest.raises(ValueError):prepare_secrets(tmp_path)
    assert (tmp_path/'postgres_password').read_bytes()==before


def test_offline_migration_preserves_logins_keys_cache_and_sequence(store,tmp_path):
    key=Fernet.generate_key();source=PortalStore(tmp_path/'source.db',key)
    try:
        user=source.create_user('carol','long-test-password');token,_=source.login('carol','long-test-password')
        source.save_connection(user,'spot','carol-api-key','carol-secret-value')
        rev=source.connection(user)['revision'];source.set_cache(user,rev,{'balances':['carol']},'verified_read_only')
        # Use an empty destination. Existing users in fixture are explicitly removed for this migration test.
        if store.database.postgres:
            target=os.environ['PORTAL_TEST_DATABASE_URL']
            with store.db() as db:db.execute('TRUNCATE account_jobs,service_gate,account_cache,connections,sessions,attempts,audit,users RESTART IDENTITY CASCADE')
        else:target=tmp_path/'target.db'
        counts=migrate_sqlite(source.path,target,key)
        copied=PortalStore(target,key)
        try:
            assert counts['users']==1 and copied.session(token)['id']==user
            assert copied.connection(user,decrypt=True)['secret']=='carol-secret-value'
            assert copied.cache(user)['snapshot']=={'balances':['carol']}
            assert copied.login('carol','long-test-password')
            with pytest.raises(ValueError,match='empty'):migrate_sqlite(source.path,target,key)
        finally:copied.close()
    finally:source.close()


def test_migration_wrong_key_rolls_back_and_source_is_unchanged(tmp_path):
    key=Fernet.generate_key();source=PortalStore(tmp_path/'source.db',key)
    user=source.create_user('alice','long-test-password');source.save_connection(user,'spot','alice-api-key','alice-secret')
    from cryptography.fernet import InvalidToken
    target=tmp_path/'target.db'
    with pytest.raises(InvalidToken):migrate_sqlite(source.path,target,Fernet.generate_key())
    with sqlite3.connect(target) as db:assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
    assert source.connection(user,decrypt=True)['secret']=='alice-secret'
    source.close()
