from copy import deepcopy
import json
import sqlite3
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from portal_exchanges import PROFILES,MultiExchangeReader,UnsupportedAccount,catalog,profile,normalize_balance,normalize_positions
from portal_store import PortalStore
from portal_database import SCHEMA_V1,SCHEMA_V2
from portal_server import create_app
from portal_jobs import AccountQueue
from portal_worker import AccountWorker
from portal_migrate import migrate_sqlite


class FakeClient:
    has={'fetchBalance':True,'fetchPositions':True}
    def __init__(self,name,params):self.name=name;self.params=params;self.calls=[];self.closed=False
    def fetch_balance(self,params):
        self.calls.append(('balance',params))
        return dict(total={'USDT':100,'BTC':0},free={'USDT':None,'BTC':0},used={'USDT':20,'BTC':0},
                    info={'secret':'must-not-escape','api_key':self.params['apiKey']})
    def fetch_positions(self,symbols,params):
        self.calls.append(('positions',symbols,params))
        return [dict(symbol='BTC/USDT:USDT',side='long',contracts=2,contractSize=.001,entryPrice=100,markPrice=105,
                     unrealizedPnl=10,leverage=3,marginMode='isolated',info={'apiKey':self.params['apiKey']}),
                dict(symbol='ETH/USDT:USDT',contracts=0)]
    def close(self):self.closed=True


@pytest.mark.parametrize('exchange_id,market',[(i,m) for i,p in PROFILES.items() for m in ('spot','futures') if m in p and i!='lbank'])
def test_each_enabled_route_uses_its_own_client_and_strips_raw_info(exchange_id,market):
    clients=[]
    def factory(name,params):
        c=FakeClient(name,params);clients.append(c);return c
    connection=dict(exchange_id=exchange_id,market=market,api_key='user-owned-api-key',secret='user-owned-secret',passphrase='user-passphrase')
    snapshot=MultiExchangeReader(factory).snapshot(connection)
    client=clients[0];r=profile(exchange_id,market)
    assert client.name==r['client'] and client.closed
    assert client.params['apiKey']==connection['api_key']
    assert client.calls[0]==('balance',r['balance_params'])
    assert snapshot['exchange_id']==exchange_id and snapshot['market']==market
    assert snapshot['balances']==[dict(asset='USDT',total=100.,free=None,locked=20.)]
    assert 'user-owned-api-key' not in str(snapshot) and 'must-not-escape' not in str(snapshot)
    if market=='futures':
        expected_clients={'binance':'binanceusdm','bybit':'bybit','okx':'okx','bitget':'bitget','gate':'gate','kucoin':'kucoinfutures','kraken':'krakenfutures'}
        assert client.name==expected_clients[exchange_id]
        assert client.calls[1]==('positions',None,r['position_params'])
        if exchange_id=='binance':assert client.calls[0][1]['type']=='future'
        if exchange_id=='bybit':assert client.calls[1][2]['settleCoin']=='USDT'
        if exchange_id=='okx':assert client.calls[1][2]=={'instType':'SWAP'}
        if exchange_id=='bitget':assert client.calls[1][2]['productType']=='USDT-FUTURES'
        if exchange_id=='gate':assert client.calls[1][2]['settle']=='usdt'
        assert snapshot['positions'][0]['contracts']==2 and snapshot['positions'][0]['contract_size']==.001
        assert len(snapshot['positions'])==1 and not snapshot['positions_complete']
    else:assert snapshot['positions']==[] and len(client.calls)==1


def test_catalog_matches_installed_capabilities_and_no_urls():
    entries=catalog();assert len(entries)==9
    assert sum('futures' in e['markets'] for e in entries)==7
    lbank=next(e for e in entries if e['id']=='lbank')
    assert lbank['markets']==['spot'] and lbank['pending_markets']==['futures']
    assert all(not e['live_execution_supported'] for e in entries)
    assert next(e for e in entries if e['id']=='okx')['required_fields']['futures']==['apiKey','secret','password']
    with pytest.raises(UnsupportedAccount):profile('http://evil.test','spot')
    with pytest.raises(UnsupportedAccount):profile('coinbaseexchange','futures')


def test_invalid_numbers_and_missing_contracts_are_not_shown_as_zero():
    with pytest.raises(ValueError):normalize_balance({'total':{'USDT':'NaN'}})
    with pytest.raises(ValueError):normalize_balance({'info':{'some':1}})
    with pytest.raises(ValueError):normalize_positions([{'symbol':'BTC/USDT','contracts':None}])
    with pytest.raises(ValueError):normalize_positions([{'symbol':'BTC/USDT','contracts':'Infinity'}])


def test_two_users_choose_different_exchanges_and_switch_cancels_old_work(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    password='long-user-password';a=store.create_user('alice',password);b=store.create_user('bob',password)
    app=create_app(store,origin='https://portal.test',secure=True)
    with TestClient(app,base_url='https://portal.test') as alice,TestClient(app,base_url='https://portal.test') as bob:
        assert alice.get('/api/exchanges').status_code==401
        headers=[]
        for client,name in ((alice,'alice'),(bob,'bob')):
            r=client.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username=name,password=password))
            assert r.status_code==200
            headers.append({'X-Portal-Request':'1','X-CSRF-Token':r.json()['csrf']})
        ah,bh=headers
        assert len(alice.get('/api/exchanges').json()['exchanges'])==9
        payload=dict(exchange_id='okx',market='futures',api_key='alice-api-key',secret='alice-secret')
        assert alice.put('/api/me/connection',headers=ah,json=payload).status_code==422
        payload['passphrase']='private-passphrase'
        assert alice.put('/api/me/connection',headers=ah,json=payload).status_code==200
        assert bob.put('/api/me/connection',headers=bh,json=dict(exchange_id='binance',market='futures',api_key='bob-api-key',secret='bob-secret')).status_code==200
        assert alice.get('/api/me/connection').json()['exchange_id']=='okx'
        assert bob.get('/api/me/connection').json()['exchange_id']=='binance'
        assert 'private-passphrase' not in alice.get('/api/me/connection').text
        assert store.connection(a,decrypt=True)['passphrase']=='private-passphrase'
        assert alice.post('/api/me/connection/refresh',headers=ah).status_code==202
        queue=AccountQueue(store);old=queue.claim(interval=0)
        assert old['user_id']==a
        assert alice.put('/api/me/connection',headers=ah,json={**payload,'exchange_id':'bybit','passphrase':None}).status_code==200
        assert not queue.finish(old,{'balances':['old-okx']},'verified_read_only')
        assert alice.get('/api/me/connection').json()['account'] is None
        assert bob.get('/api/me/connection').json()['exchange_id']=='binance'
        assert alice.put('/api/me/connection',headers=ah,json={**payload,'urls':{'api':'http://evil.test'}}).status_code==422
        assert alice.put('/api/me/connection',headers=ah,json={**payload,'exchange_id':'unknown'}).status_code==422
    store.close()


def test_provider_and_market_tamper_rejected_before_credentials_can_be_sent(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key());a=store.create_user('alice','long-user-password')
    store.save_connection(a,'spot','alice-api-key','alice-secret',exchange_id='binance')
    for field,value in [('exchange_id','bybit'),('market','futures')]:
        with store.db() as db:db.execute('UPDATE connections SET '+field+'=? WHERE user_id=?',(value,a))
        with pytest.raises(ValueError,match='mismatch'):store.connection(a,decrypt=True)
        with store.db() as db:db.execute("UPDATE connections SET exchange_id='binance',market='spot' WHERE user_id=?",(a,))
    store.close()


def test_rate_gates_are_shared_per_exchange_but_other_exchange_can_proceed(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key());ids=[]
    for name,venue in [('alice','binance'),('bob','binance'),('carol','okx')]:
        user=store.create_user(name,'long-user-password');ids.append(user)
        store.save_connection(user,'spot','test-api-key','test-secret',exchange_id=venue,passphrase='phrase')
        AccountQueue(store).enqueue(user)
    q=AccountQueue(store)
    first=q.claim(interval=30);second=q.claim(interval=30)
    assert first and second and first['exchange_id']!=second['exchange_id']
    assert q.claim(interval=30) is None
    with store.db() as db:assert db.execute('SELECT COUNT(*) AS count FROM service_gate').fetchone()['count']==2
    store.close()


def test_upgrade_from_v2_preserves_old_lbank_credentials_and_offline_migration(tmp_path):
    import hashlib
    key=Fernet.generate_key();source=tmp_path/'old.db'
    with sqlite3.connect(source) as db:
        db.executescript(SCHEMA_V1+SCHEMA_V2+'CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES(1); INSERT INTO schema_migrations VALUES(2);')
        db.execute('INSERT INTO users VALUES(?,?,?,0,NULL)',('alice-id','alice','unused-password-hash'))
        blob=Fernet(key).encrypt(json.dumps(dict(owner='alice-id',api_key='old-lbank-api-key',secret='old-lbank-secret')).encode())
        db.execute('INSERT INTO connections VALUES(?,?,?,?,?)',('alice-id',blob,'spot','old-revision',time.time()))
        db.execute("INSERT INTO service_gate VALUES('lbank-read',?)",(time.time()+30,))
    # Offline copy of an untouched v2 source must also synthesize the LBank provider column.
    target=tmp_path/'copied.db';migrate_sqlite(source,target,key)
    copied=PortalStore(target,key);assert copied.connection('alice-id',decrypt=True)['exchange_id']=='lbank'
    with copied.db() as db:
        assert db.execute("SELECT next_at FROM service_gate WHERE name='account-read:lbank'").fetchone()
        assert not db.execute("SELECT next_at FROM service_gate WHERE name='lbank-read'").fetchone()
    copied.close()
    store=PortalStore(source,key)
    assert store.connection('alice-id',decrypt=True)['secret']=='old-lbank-secret'
    with store.db() as db:
        assert {r['version'] for r in db.execute('SELECT version FROM schema_migrations')}=={1,2,3}
        assert db.execute("SELECT next_at FROM service_gate WHERE name='account-read:lbank'").fetchone()
        db.execute("UPDATE connections SET exchange_id='bybit' WHERE user_id='alice-id'")
    with pytest.raises(ValueError,match='Legacy'):store.connection('alice-id',decrypt=True)
    store.close()
