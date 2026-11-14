"""Public registration, closed sales and signed product permissions."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import time
import uuid
import sqlite3

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
import pandas as pd

from portal_store import PortalStore
from portal_server import create_app
from portal_billing import Billing,BillingConflict
from portal_migrate import migrate_sqlite
import product_pricing
import license_access
import customer_manager
import signal_feed
from pricing_helpers import enable_test_prices
from test_system import system,cfg,setup_position,bars_for
import lbank_bot as bot
import c3_sleeve as C
import pa_sleeve as P

ORIGIN='https://portal.test'
PASSWORD='a-disposable-strong-password'

@pytest.fixture
def store(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    yield store
    store.close()

@pytest.fixture
def issuer(tmp_path):
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem'
    customer_manager.keygen(private,public)
    return private,public


def signup(client,name='new-trader'):
    response=client.post('/api/register',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD,password_confirmation=PASSWORD,email=name+'@example.com'))
    assert response.status_code==201,response.text
    return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':response.json()['csrf']}


def activate(store,issuer,name='alice',product='signals',now=None,cap=10000):
    user=store.create_user(name,PASSWORD);b=Billing(store);enable_test_prices(store)
    q=b.quote(user,cap,1,now=now,product=product)
    order=b.order(user,cap,1,'subscription',str(uuid.uuid4()),q['price_cents'],now,product)
    b.approve(order['id'],issuer[0],None if product=='signals' else 'binance:'+name+'123',None if product=='signals' else str(cap),'payment:'+order['id'],now)
    return user,b


def test_registration_starts_isolated_session_without_a_license(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        payload=dict(username='new-trader',password=PASSWORD,password_confirmation=PASSWORD,email='new-trader@example.com')
        assert client.post('/api/register',json=payload).status_code==403
        assert client.post('/api/register',headers={'X-Portal-Request':'1'},json={**payload,'password_confirmation':'different-password'}).status_code==422
        assert client.post('/api/register',headers={'X-Portal-Request':'1'},json={**payload,'role':'admin'}).status_code==422
        h=signup(client)
        assert client.get('/api/me').json()['username']=='new-trader'
        assert client.get('/api/me/license').json()['license']['state']=='none'
        assert client.get('/api/me/signals').status_code==403
        assert client.get('/api/me').json()['live_execution_supported'] is False
        assert client.get('/api/me/license/download').status_code==404
        assert PASSWORD not in client.get('/api/me').text
        assert client.post('/api/logout',headers=h).status_code==200
        assert client.get('/api/me').status_code==401
        duplicate=client.post('/api/register',headers={'X-Portal-Request':'1'},json=payload)
        assert duplicate.status_code==409 and PASSWORD not in duplicate.text
    with store.db() as db:
        row=db.execute('SELECT password,runtime FROM users').fetchone()
        assert row['password']!=PASSWORD and row['runtime'] is None


def test_registration_rate_limit_shared_between_processes(store):
    for _ in range(10):assert store.attempt('signup:testclient')
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        response=client.post('/api/register',headers={'X-Portal-Request':'1'},json=dict(username='new-user',password=PASSWORD,password_confirmation=PASSWORD,email='new-user@example.com'))
        assert response.status_code==429


def test_duplicate_registration_is_atomic(store):
    def register(_):
        try:store.register('same-user',PASSWORD,'same@example.com');return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=4) as pool:assert sum(pool.map(register,range(4)))==1
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']==1
        assert db.execute('SELECT COUNT(*) AS n FROM sessions').fetchone()['n']==1


def test_sales_default_closed_and_cannot_be_bypassed_by_client(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        h=signup(client)
        products=client.get('/api/plans').json()['products']
        assert {p['product'] for p in products}=={'signals','autotrade'}
        assert all(not p['sales_enabled'] for p in products)
        assert all(v is None for p in products for tier in p['tiers'] for v in tier['prices_cents'].values())
        for product in ('signals','autotrade'):
            body=dict(cap_usd=10000,months=1,kind='subscription',product=product)
            assert client.post('/api/me/license/quote',headers=h,json=body).status_code==409
            assert client.post('/api/me/license/orders',headers=h,json={**body,'request_key':str(uuid.uuid4()),'expected_price_cents':1}).status_code==409
        assert client.post('/api/me/license/quote',headers=h,json={**body,'product':'admin'}).status_code==422
        assert client.get('/api/admin/pricing',headers=h).status_code==403
        assert not client.get('/api/me/license').json()['orders']


def test_distinct_prices_and_sales_close_also_blocks_approval(store,issuer):
    user,b=activate(store,issuer)
    signal_price=b.snapshot(user)['orders'][0]['price_cents']
    other=store.create_user('bob',PASSWORD)
    assert b.quote(other,10000,1,product='autotrade')['price_cents']==signal_price*2
    q=b.quote(other,10000,1,product='signals')
    order=b.order(other,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product='signals')
    product_pricing.close_sales(store,'signals')
    with pytest.raises(BillingConflict):b.approve(order['id'],issuer[0],payment_ref='payment:closed')
    assert b.snapshot(other)['license']['state']=='none'
    assert b.snapshot(user)['license']['state']=='active'  # Closing sales does not revoke paid access.


def test_price_changes_invalidate_pending_order_and_product_cannot_be_substituted(store,issuer):
    enable_test_prices(store);user=store.create_user('alice',PASSWORD);b=Billing(store)
    q=b.quote(user,10000,1,product='signals');key=str(uuid.uuid4())
    order=b.order(user,10000,1,'subscription',key,q['price_cents'],product='signals')
    with pytest.raises(BillingConflict):b.order(user,10000,1,'subscription',key,q['price_cents'],product='autotrade')
    enable_test_prices(store) # New tariff version, even if the same disposable numbers.
    with pytest.raises(BillingConflict):b.approve(order['id'],issuer[0],payment_ref='payment:oldprice')
    assert b.snapshot(user)['license']['state']=='none'


def test_signal_license_cannot_open_any_bot_but_keeps_open_position_exits(store,issuer,tmp_path,monkeypatch,system):
    p=setup_position(system,state='STATE_INITIAL')
    user,b=activate(store,issuer)
    path=tmp_path/'signal-license.json';path.write_text(b.document(user))
    for k,v in dict(BOT_LICENSE_REQUIRED='1',BOT_LICENSE_FILE=str(path),BOT_LICENSE_PUBLIC_KEY_FILE=str(issuer[1]),BOT_CUSTOMER_ID='alice',BOT_LICENSE_ACCOUNT_ID='signals:alice').items():monkeypatch.setenv(k,v)
    monkeypatch.delenv('BOT_LICENSE_ACCOUNT_ID_FILE',raising=False)
    status=license_access.status();assert status['state']=='active' and status['signals_allowed'] and not status['entries_allowed']
    assert not system._activate(p,100.,time.time())
    assert not system._pyramid_add(p,'long',pd.Series(dtype=float),system.config.read(),time.time())
    with pytest.raises(PermissionError):system._insert({})
    cs=C.Store(tmp_path/'c3-test.db');sl=C.Sleeve(C.load(C.Path(C.__file__).with_name('c3_config.json')),cs,system.data)
    ps=P.Store(tmp_path/'pa-test.db');pa=P.Sleeve(P.load(P.Path(P.__file__).with_name('pa_config.json')),ps,system.data)
    assert sl.open('AAVE/USDT:USDT','long',pd.Series(dict(atr=1.,close=100.,timestamp=0)),time.time()) is None
    assert pa.open('LINK/USDT:USDT',{},time.time()) is None
    for target,symbol in [(cs,'AAVE/USDT:USDT'),(ps,'LINK/USDT:USDT')]:
        with target.db() as db:db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,'long',100.,2.,95.,100.,1.,0,0,10.))
    system.data.prices[p['symbol']]=80.;system.data.prices['AAVE/USDT:USDT']=90.;system.data.prices['LINK/USDT:USDT']=90.
    system.watchdog();sl.watchdog();pa.watchdog()
    assert not system.db.positions() and not cs.positions() and not ps.positions()
    modified=json.loads(path.read_text());modified['payload']['product']='autotrade';path.write_text(json.dumps(modified))
    assert not license_access.entries_allowed()


def test_upgrade_signals_to_autotrade_requires_verified_account(store,issuer):
    now=time.time();user,b=activate(store,issuer,now=now)
    before=b.snapshot(user)['license'];middle=(license_access.timestamp(before['not_before'])+license_access.timestamp(before['expires_at']))/2
    q=b.quote(user,10000,1,'upgrade',middle,product='autotrade')
    assert 1224<=q['price_cents']<=1226
    order=b.order(user,10000,1,'upgrade',str(uuid.uuid4()),q['price_cents'],middle,product='autotrade')
    with pytest.raises(ValueError):b.approve(order['id'],issuer[0],payment_ref='payment:upgrade',now=middle)
    after=b.approve(order['id'],issuer[0],'binance:alice123','10000','payment:upgrade',middle)
    assert after['product']=='autotrade' and after['entries_allowed'] and after['expires_at']==before['expires_at']
    with pytest.raises(BillingConflict):b.quote(user,10000,1,'upgrade',middle,product='signals')


def test_feed_is_only_for_active_subscribers_and_uses_setup_outbox(store,issuer,tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','1');monkeypatch.setenv('BOT_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    monkeypatch.setenv('PORTAL_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    now=time.time();stamp=(int(now)//3600-1)*3600000
    assert signal_feed.publish('main','BTC/USDT:USDT','long',100,95,stamp,'1h',now+3600,now,110,source_mode='csv-lbank')
    assert not signal_feed.publish('main','BTC/USDT:USDT','long',100,95,stamp,'1h',now+3600,now,110,source_mode='csv-lbank')
    user,b=activate(store,issuer)
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        assert client.get('/api/me/signals').status_code==401
        h=signup(client,'unpaid-user');assert client.get('/api/me/signals').status_code==403
        client.post('/api/logout',headers=h)
        r=client.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username='alice',password=PASSWORD));assert r.status_code==200
        response=client.get('/api/me/signals?user_id=unpaid-user')
        assert response.status_code==200 and response.json()['signals'][0]['execution']=='not_executed'
        assert len(response.json()['signals'])==1
        with store.db() as db:
            document=json.loads(b.document(user));document['payload']['expires_at']='2020-01-01T00:00:00+00:00'
            db.execute('UPDATE capital_licenses SET document=? WHERE user_id=?',(json.dumps(document),user))
        assert client.get('/api/me/signals').status_code==403


def test_publisher_does_not_publish_open_candles_or_invalid_stops(tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','1');monkeypatch.setenv('BOT_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    now=time.time();stamp=int(now)*1000
    assert not signal_feed.publish('c3','SOL/USDT','long',100,90,stamp,'4h',now+3600,now,source_mode='csv-lbank')
    with pytest.raises(ValueError):signal_feed.publish('c3','SOL/USDT','long',100,110,stamp-14400000,'4h',now+3600,now,source_mode='csv-lbank')
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','0')
    assert not signal_feed.publish('c3','SOL/USDT','long',100,90,stamp-14400000,'4h',now+3600,now,source_mode='csv-lbank')
    assert not (tmp_path/'feed.db').exists()


def test_demo_candles_never_enter_the_customer_signal_feed(tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','1');monkeypatch.setenv('BOT_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    now=time.time()
    assert not signal_feed.publish('main','BTC/USDT','long',100,95,int((now-7200)*1000),'1h',now+3600,now,source_mode='demo')
    assert not (tmp_path/'feed.db').exists()


def test_main_scanner_can_publish_without_creating_a_position(system,tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','1');monkeypatch.setenv('BOT_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    conf=system.config.read();conf['bot_control']['auto_trade_enabled']=False;conf['symbols']=['BTC/USDT:USDT'];system.config.write(conf)
    system.data.mode='csv-lbank';now=time.time()
    for tf in ('1h','4h','15m','1d'):system.data.bars[('BTC/USDT:USDT',tf)]=bars_for(now,tf)
    def frame(rows,c,tf,stamp):
        return pd.DataFrame([dict(timestamp=(int(stamp)//bot.TIMEFRAMES[tf]-1)*bot.TIMEFRAMES[tf]*1000,open=100.,close=100.,high=102.,low=98.,kijun=99.,atr=1.,rsi=60.)])
    monkeypatch.setattr(bot,'indicators',frame);monkeypatch.setattr(bot,'regime',lambda *_:'long');monkeypatch.setattr(bot,'entry_signal',lambda *_:True)
    assert system.scan(now)
    feed=signal_feed.read_feed(tmp_path/'feed.db')
    assert feed['status']=='ready' and feed['signals'][0]['bot']=='main'
    assert feed['signals'][0]['source_mode']=='csv-lbank'
    assert feed['signals'][0]['expires_at']<=now+86400
    assert not system.db.positions()
    assert system.scan(now) and len(signal_feed.read_feed(tmp_path/'feed.db')['signals'])==1


def test_c3_and_pa_publish_setups_with_entries_disabled(tmp_path,monkeypatch):
    from test_c3_sleeve import cfg as c3_config,FakeData,find_signal_end,uptrend_with_dip
    monkeypatch.setenv('BOT_SIGNAL_FEED_ENABLED','1');monkeypatch.setenv('BOT_SIGNAL_FEED_DB',str(tmp_path/'feed.db'))
    conf=c3_config(enabled=False,skip_weekend=False,confirm_bars=0,profit_lock_arm_r=0.,partial_target_r=0.)
    rows,now,side,df=find_signal_end(uptrend_with_dip(),conf);assert side=='long'
    data=FakeData(rows,float(df.iloc[-1].close));data.mode='csv-lbank'
    store=C.Store(tmp_path/'c3.db');sl=C.Sleeve(conf,store,data);sl.c['symbols']=['AVAX/USDT:USDT']
    assert sl.scan(now) and not store.positions()
    assert signal_feed.read_feed(tmp_path/'feed.db',now=now)['signals'][0]['bot']=='c3'
    pc=P.load(P.Path(P.__file__).with_name('pa_config.json'));pc.update(enabled=False,symbols=['LINK/USDT:USDT'])
    ps=P.Store(tmp_path/'pa.db');pa=P.Sleeve(pc,ps,data)
    stamp=(int(now)//14400-1)*14400000
    monkeypatch.setattr(P,'features',lambda *_:pd.DataFrame([dict(timestamp=stamp,atr=1.,close=100.)]))
    monkeypatch.setattr(P,'tradable_signal',lambda *_:(None,dict(side='long',level=101.,stop=96.)))
    assert pa.scan(now) and not ps.positions() and not ps.orders()
    assert {s['bot'] for s in signal_feed.read_feed(tmp_path/'feed.db',now=now)['signals']}=={'c3','pa'}


def test_schema_v4_orders_migrate_as_autotrade_with_sales_closed(tmp_path):
    from portal_database import SCHEMA_V1,SCHEMA_V2,SCHEMA_V3,SCHEMA_V4
    source=tmp_path/'v4.db'
    with sqlite3.connect(source) as db:
        db.executescript(SCHEMA_V1+SCHEMA_V2+SCHEMA_V3+SCHEMA_V4)
        db.execute('INSERT INTO users(id,username,password) VALUES(?,?,?)',('alice-id','alice','hashed'))
        db.execute('INSERT INTO license_orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('legacy-order','alice-id',10000,1,'subscription',4900,'old-version','pending',1,1,'old-request',None))
    key=Fernet.generate_key();target=tmp_path/'new.db';migrate_sqlite(source,target,key)
    copied=PortalStore(target,key)
    try:
        assert Billing(copied).snapshot('alice-id')['orders'][0]['product']=='autotrade'
        assert not any(p['sales_enabled'] for p in product_pricing.catalog(copied)['products'])
    finally:copied.close()


def test_capital_breach_blocks_entries_but_not_paid_signal_access(store,issuer):
    now=time.time();user,b=activate(store,issuer,product='autotrade',now=now)
    b.cashflow('alice',issuer[0],'deposit:breach','1000',now+1)
    status=b.snapshot(user,now+72*3600+2)['license']
    assert status['state']=='capital_exceeded' and not status['entries_allowed'] and status['signals_allowed']


def test_registration_requires_a_unique_valid_email_that_users_can_change(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        base=dict(password=PASSWORD,password_confirmation=PASSWORD)
        h={'X-Portal-Request':'1'}
        assert client.post('/api/register',headers=h,json=dict(base,username='no-email')).status_code==422
        assert client.post('/api/register',headers=h,json=dict(base,username='bad-email',email='not an email')).status_code==422
        first=signup(client,'first-user')
        assert client.get('/api/me').json()['email']=='first-user@example.com'
        client.post('/api/logout',headers=first)
        taken=client.post('/api/register',headers=h,json=dict(base,username='second-user',email='First-User@Example.com '))
        assert taken.status_code==409 and taken.json()['detail']=='Email unavailable'
        second=signup(client,'second-user')
        assert client.put('/api/me/email',json={'email':'x@example.com'}).status_code==403  # CSRF required
        assert client.put('/api/me/email',headers=second,json={'email':'first-user@example.com'}).status_code==409
        assert client.put('/api/me/email',headers=second,json={'email':'nope'}).status_code==422
        assert client.put('/api/me/email',headers=second,json={'email':' New@Example.COM'}).json()['email']=='new@example.com'
        assert client.get('/api/me').json()['email']=='new@example.com'
