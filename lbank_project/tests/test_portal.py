import json
import sqlite3
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from portal_store import PortalStore
from portal_server import create_app
from portal_lbank import LBankAccountReader,FuturesNotValidated
from portal_runtime import robots
from portal_worker import AccountWorker
from test_system import system,cfg,setup_position
import c3_sleeve
import pa_sleeve

ORIGIN='https://portal.test'
PASSWORD='a-strong-test-password'


@pytest.fixture
def store(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    store.create_user('alice',PASSWORD);store.create_user('bob',PASSWORD)
    return store


class Reader:
    def __init__(self):self.calls=[]
    def snapshot(self,connection):
        self.calls.append(connection)
        if connection['market']=='futures':raise FuturesNotValidated()
        if connection['secret']=='bad-secret-value':raise ValueError('secret echoed '+connection['secret'])
        return dict(market='spot',balances=[dict(asset='USDT',free=100 if connection['api_key']=='alice-api-key' else 200,locked=0,total=100)])


def login(client,username):
    r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=username,password=PASSWORD))
    assert r.status_code==200,r.text
    return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}


def test_two_users_private_accounts_and_encryption(store):
    reader=Reader();app=create_app(store,origin=ORIGIN,secure=True)
    with TestClient(app,base_url=ORIGIN) as alice,TestClient(app,base_url=ORIGIN) as bob:
        ah=login(alice,'alice');bh=login(bob,'bob')
        for client,headers,name in ((alice,ah,'alice'),(bob,bh,'bob')):
            r=client.put('/api/me/connection',headers=headers,json=dict(market='spot',api_key=name+'-api-key',secret=name+'-secret-value'))
            assert r.status_code==200
            assert client.post('/api/me/connection/refresh',headers=headers).status_code==202
            assert AccountWorker(store,reader,interval=0).once()
            body=client.get('/api/me/connection').text
            assert name+'-api-key' not in body and name+'-secret-value' not in body
        assert alice.get('/api/me/connection').json()['account']['snapshot']['balances'][0]['free']==100
        assert bob.get('/api/me/connection').json()['account']['snapshot']['balances'][0]['free']==200
        # Neither query parameters nor alternate owner routes can select another tenant.
        assert alice.get('/api/me/connection?user_id=bob').json()['account']['snapshot']['balances'][0]['free']==100
        assert alice.get('/api/users/bob/connection').status_code==404
        assert alice.put('/api/me/connection',headers=ah,json=dict(market='spot',api_key='new-alice-key',secret='new-secret-value',user_id='bob')).status_code==422
        assert alice.delete('/api/me/connection',headers=ah).status_code==200
        assert not alice.get('/api/me/connection').json()['configured']
        assert bob.get('/api/me/connection').json()['configured']
    assert b'alice-secret-value' not in store.path.read_bytes()
    with store.db() as db:
        ciphertext=db.execute('SELECT encrypted FROM connections').fetchone()[0]
        assert b'bob-secret-value' not in ciphertext


def test_auth_csrf_logout_expired_sessions_and_host(store):
    app=create_app(store,origin=ORIGIN,secure=True)
    with TestClient(app,base_url=ORIGIN) as c:
        assert c.get('/api/me/robots').status_code==401
        assert c.post('/api/login',json=dict(username='alice',password=PASSWORD)).status_code==403
        h=login(c,'alice')
        assert 'HttpOnly' in c.post('/api/login',headers=h,json=dict(username='alice',password=PASSWORD)).headers['set-cookie']
        h={'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':c.get('/api/me').json()['csrf']}
        assert c.delete('/api/me/connection').status_code==403
        assert c.delete('/api/me/connection',headers={**h,'Origin':'https://evil.test'}).status_code==403
        assert c.delete('/api/me/connection',headers={**h,'X-CSRF-Token':'wrong'}).status_code==403
        assert c.get('/api/me',headers={'Host':'evil.test'}).status_code==400
        token=c.cookies.get('trade_session')
        assert c.post('/api/logout',headers=h).status_code==200
        c.cookies.set('trade_session',token)
        assert c.get('/api/me').status_code==401
        c.cookies.clear();login(c,'alice')
        with store.db() as db:db.execute('UPDATE sessions SET expires=0')
        assert c.get('/api/me').status_code==401


def test_shared_login_throttle_and_disabled_user(store):
    app=create_app(store,origin=ORIGIN,secure=True)
    with TestClient(app,base_url=ORIGIN) as c:
        for _ in range(10):
            r=c.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username='missing',password=PASSWORD))
            assert r.status_code==401
        assert c.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username='alice',password=PASSWORD)).status_code==429
    # Another process/app shares the limiter database.
    with TestClient(create_app(store,origin=ORIGIN,secure=True),base_url=ORIGIN) as c:
        assert c.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username='alice',password=PASSWORD)).status_code==429
    with store.db() as db:db.execute("UPDATE users SET disabled=1 WHERE username='alice'")
    assert store.login('alice',PASSWORD) is None


def test_secret_validation_does_not_echo_input_and_http_protection(store):
    with TestClient(create_app(store,origin=ORIGIN,secure=True),base_url=ORIGIN) as c:
        h=login(c,'alice')
        r=c.put('/api/me/connection',headers=h,json=dict(market='invalid',api_key='private-input-key',secret='private-input-secret'))
        assert r.status_code==422 and 'private-input' not in r.text
        r=c.put('/api/me/connection',headers=h,json=dict(market='spot',api_key='private-input-key',secret='x'*17000))
        assert r.status_code==413 and 'private-input' not in r.text
        assert "script-src 'self'" in c.get('/').headers['Content-Security-Policy']
        assert 'localStorage' not in c.get('/portal.js').text
    with pytest.raises(ValueError):create_app(store,origin='http://external.test',secure=False)
    with pytest.raises(ValueError):create_app(store,origin='http://127.0.0.1:8080',secure=True)
    from portal_server import trusted_proxies
    assert trusted_proxies('')==''
    assert trusted_proxies('127.0.0.1,10.0.0.0/24')=='127.0.0.1/32,10.0.0.0/24'
    with pytest.raises(ValueError):trusted_proxies('*')
    with pytest.raises(ValueError):trusted_proxies('example.com')


def test_futures_not_routed_to_spot_and_sdk_exception_redacted(store):
    reader=Reader()
    with TestClient(create_app(store,origin=ORIGIN,secure=True),base_url=ORIGIN) as c:
        h=login(c,'alice')
        for market,secret,state in [('futures','alice-secret-value','futures_not_validated'),('spot','bad-secret-value','verification_failed')]:
            c.put('/api/me/connection',headers=h,json=dict(market=market,api_key='alice-api-key',secret=secret))
            r=c.post('/api/me/connection/refresh',headers=h)
            assert r.status_code==202
            assert AccountWorker(store,reader,interval=0).once()
            r=c.get('/api/me/connection')
            assert r.json()['account']['status']==state and secret not in r.text
        assert c.post('/api/me/connection/refresh',headers=h).status_code==429
    with pytest.raises(FuturesNotValidated):LBankAccountReader().snapshot(dict(market='futures'))


def test_inflight_old_connection_cannot_resurrect_deleted_or_rotated_account(store):
    alice=store.login('alice',PASSWORD);owner=store.session(alice[0])['id']
    store.save_connection(owner,'spot','alice-api-key','alice-secret-value');old=store.connection(owner)
    store.save_connection(owner,'spot','new-alice-key','new-secret-value')
    store.set_cache(owner,old['revision'],dict(balances=['old']), 'verified_read_only')
    assert store.cache(owner) is None
    current=store.connection(owner);store.disconnect(owner)
    store.set_cache(owner,current['revision'],dict(balances=['old']), 'verified_read_only')
    assert store.cache(owner) is None


def test_vault_ciphertext_is_bound_to_owner(store):
    a=store.session(store.login('alice',PASSWORD)[0])['id'];b=store.session(store.login('bob',PASSWORD)[0])['id']
    store.save_connection(a,'spot','alice-api-key','alice-secret-value')
    store.save_connection(b,'spot','bob-api-key','bob-secret-value')
    with store.db() as db:
        blob=db.execute('SELECT encrypted FROM connections WHERE user_id=?',(a,)).fetchone()[0]
        db.execute('UPDATE connections SET encrypted=? WHERE user_id=?',(blob,b))
    with pytest.raises(ValueError,match='owner'):store.connection(b,decrypt=True)


def test_runtime_bound_only_by_admin_and_unique_per_owner(store,system,tmp_path):
    runtime=tmp_path/'runtime';runtime.mkdir()
    (runtime/'customer_identity.json').write_text(json.dumps(dict(customer_id='alice')))
    config=system.config.read();(runtime/'config.json').write_text(json.dumps(config))
    setup_position(system)
    system.db.runtime_set('watchdog_at',time.time())
    import shutil
    # SQLite backup, including committed WAL records, then open portal in read-only mode.
    with system.db.connect() as source,sqlite3.connect(runtime/'lbank_ichimoku_bot.db') as dest:source.backup(dest)
    for module,cfgname,dbname in [(c3_sleeve,'c3_config.json','c3_sleeve.db'),(pa_sleeve,'pa_config.json','pa_sleeve.db')]:
        from pathlib import Path
        shutil.copyfile(Path(module.__file__).with_name(cfgname),runtime/cfgname)
        module.Store(runtime/dbname)
    a=store.session(store.login('alice',PASSWORD)[0])['id'];b=store.session(store.login('bob',PASSWORD)[0])['id']
    store.bind_runtime(a,runtime)
    with pytest.raises(ValueError,match='identity'):store.bind_runtime(b,runtime)
    with TestClient(create_app(store,origin=ORIGIN,secure=True),base_url=ORIGIN) as alice,TestClient(create_app(store,origin=ORIGIN,secure=True),base_url=ORIGIN) as bob:
        login(alice,'alice');login(bob,'bob')
        aa=alice.get('/api/me/robots').json()['robots'];bb=bob.get('/api/me/robots').json()['robots']
        assert aa[0]['state']=='running' and len(aa[0]['positions'])==1
        assert aa[1]['state']=='health_unknown' and aa[2]['state']=='health_unknown'
        assert all(r['state']=='not_provisioned' and not r['positions'] for r in bb)
        assert str(runtime) not in alice.get('/api/me/robots').text
        (runtime/'customer_identity.json').write_text(json.dumps(dict(customer_id='bob')))
        assert all(r['state']=='unavailable' and not r['positions'] for r in alice.get('/api/me/robots').json()['robots'])
        with pytest.raises(sqlite3.IntegrityError):store.bind_runtime(b,runtime)


def test_spot_reader_normalizes_only_balances(monkeypatch):
    import portal_lbank
    class FakeExchange:
        def __init__(self,params):assert params['apiKey']=='alice-api-key'
        def spotPrivatePostSupplementUserInfoAccount(self,params):
            return dict(result=True,data=dict(balances=[dict(asset='usdt',free='42',locked='3')],secret='must-not-leak'))
    monkeypatch.setattr(portal_lbank.ccxt,'lbank',FakeExchange)
    snapshot=LBankAccountReader().snapshot(dict(market='spot',api_key='alice-api-key',secret='secret'))
    assert snapshot==dict(market='spot',balances=[dict(asset='USDT',free=42.,locked=3.,total=45.)])


def test_portal_process_starts_with_file_key_and_owns_persistent_sessions(tmp_path):
    import os,socket,subprocess,sys,httpx
    from pathlib import Path
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    key=Fernet.generate_key();keyfile=tmp_path/'portal.key';keyfile.write_bytes(key)
    path=tmp_path/'portal.db';store=PortalStore(path,key);store.create_user('alice',PASSWORD)
    env={**os.environ,'PORTAL_DB':str(path),'PORTAL_KEY_FILE':str(keyfile),
         'PORTAL_ORIGIN':origin,'PORTAL_PORT':str(port),'PORTAL_ALLOW_LOCAL_HTTP':'1'}
    with (tmp_path/'portal.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-u','portal_server.py'],cwd=Path(__file__).parents[1],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=origin,trust_env=False,timeout=2) as client:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    assert process.poll() is None
                    try:
                        if client.get('/healthz').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:pytest.fail('Portal did not become ready')
                assert 'پنل اختصاصی' in client.get('/').text
                assert client.get('/portal.css').status_code==200
                assert client.get('/api/me').status_code==401
                r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':origin},json=dict(username='alice',password=PASSWORD))
                assert r.status_code==200 and 'HttpOnly' in r.headers['set-cookie']
                assert client.get('/api/me').json()['username']=='alice'
                assert all(r['state']=='not_provisioned' for r in client.get('/api/me/robots').json()['robots'])
                assert store.session(client.cookies.get('trade_session'))['username']=='alice'
                with store.db() as db:db.execute("UPDATE users SET disabled=1 WHERE username='alice'")
                assert client.get('/api/me').status_code==401
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
