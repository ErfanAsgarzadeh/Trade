"""Pricing, owner isolation, signed capital gates and operator settlement workflow."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import json
import sqlite3
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import capital_plans as plans
import customer_manager as customers
import license_access as access
from portal_billing import Billing, BillingConflict
from portal_migrate import migrate_sqlite
from portal_server import create_app
from portal_store import PortalStore
from test_system import system, cfg, setup_position
import c3_sleeve as C
import pa_sleeve as P
import pandas as pd


@pytest.fixture
def setup(tmp_path):
    key=Fernet.generate_key();store=PortalStore(tmp_path/'portal.db',key)
    alice=store.create_user('alice','test-password-strong');bob=store.create_user('bob','test-password-strong')
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem'
    customers.keygen(private,public)
    yield store,Billing(store),alice,bob,private,public,key
    store.close()


def order(billing,user,cap=10000,months=1,kind='subscription',now=None,key=None):
    q=billing.quote(user,cap,months,kind,now)
    return billing.order(user,cap,months,kind,key or str(uuid.uuid4()),q['price_cents'],now)


def activate(setup,cap=10000,months=1,equity='10000',now=None):
    store,b,a,_,private,_,_=setup
    oid=order(b,a,cap,months,now=now)['id']
    return b.approve(oid,private,'binance:alice123',equity,'payment:'+oid,now)


def use_license(monkeypatch,tmp_path,setup,document,seed=10000):
    public=setup[5];path=tmp_path/'license.json';path.write_text(document)
    for k,v in dict(BOT_LICENSE_REQUIRED='1',BOT_LICENSE_FILE=str(path),BOT_LICENSE_PUBLIC_KEY_FILE=str(public),
                    BOT_CUSTOMER_ID='alice',BOT_LICENSE_ACCOUNT_ID='binance:alice123',PAPER_EQUITY=str(seed)).items():monkeypatch.setenv(k,v)
    monkeypatch.delenv('BOT_LICENSE_ACCOUNT_ID_FILE',raising=False)
    return path


@pytest.mark.parametrize('cap,prices',list(plans.PRICES.items()))
def test_all_agreed_prices(cap,prices):
    assert [plans.price_cents(cap,m) for m in (1,3,6)]==[p*100 for p in prices]


@pytest.mark.parametrize('value',['NaN','Infinity','-1',True,'0.001'])
def test_invalid_capital(value):
    with pytest.raises(ValueError):plans.money(value,positive=True)


def test_calendar_months_not_thirty_days():
    jan=datetime(2024,1,31,9,30,tzinfo=timezone.utc).timestamp()
    assert plans.iso(plans.add_months(jan,1))=='2024-02-29T09:30:00+00:00'
    assert plans.iso(plans.add_months(jan,3))=='2024-04-30T09:30:00+00:00'
    with pytest.raises(ValueError):plans.price_cents(10000,2)
    with pytest.raises(ValueError):plans.price_cents(True,1)


def test_order_price_is_server_owned_idempotent_and_concurrent(setup):
    _,b,a,_,_,_,_=setup
    with pytest.raises(BillingConflict):b.order(a,10000,1,'subscription',str(uuid.uuid4()),1)
    request_key=str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows=list(pool.map(lambda _:b.order(a,10000,1,'subscription',request_key,4900),range(6)))
    assert len({r['id'] for r in rows})==1
    assert sum(not r['already_exists'] for r in rows)==1
    with pytest.raises(BillingConflict):b.order(a,5000,1,'subscription',request_key,2900)
    with pytest.raises(BillingConflict):order(b,a,3000)
    assert b.snapshot(a)['license']['state']=='none'


def test_settlement_validation_no_client_activation_and_unique_payment(setup):
    store,b,a,bob,private,_,_=setup
    oid=order(b,a)['id']
    with pytest.raises(BillingConflict):b.approve(oid,private,'binance:alice123','10001','pay:1234')
    assert b.snapshot(a)['orders'][0]['status']=='pending'
    p=b.approve(oid,private,'binance:alice123','10000','pay:1234')
    assert p['state']=='active' and p['entries_allowed']
    with pytest.raises(BillingConflict):b.approve(oid,private,'binance:alice123','10000','pay:1234')
    boid=order(b,bob)['id']
    with pytest.raises(sqlite3.IntegrityError):b.approve(boid,private,'binance:bob123','10000','pay:1234')
    assert b.snapshot(bob)['license']['state']=='none'
    with pytest.raises(sqlite3.IntegrityError):b.approve(boid,private,'binance:alice123','10000','pay:bob123')
    assert b.snapshot(bob)['license']['state']=='none'
    assert b.snapshot(a)['orders'][0]['status']=='approved'


def test_signed_license_account_customer_seed_and_tamper(setup,monkeypatch,tmp_path):
    _,b,a,_,_,_,_=setup
    p=activate(setup);document=b.document(a);path=use_license(monkeypatch,tmp_path,setup,document)
    assert access.status()['state']=='active'
    assert access.entries_allowed(initial_capital=10000)
    assert not access.entries_allowed(initial_capital=10001)
    monkeypatch.setenv('BOT_LICENSE_ACCOUNT_ID','binance:other123');assert not access.entries_allowed()
    monkeypatch.setenv('BOT_LICENSE_ACCOUNT_ID','binance:alice123')
    monkeypatch.setenv('BOT_CUSTOMER_ID','bob');assert not access.entries_allowed()
    monkeypatch.setenv('BOT_CUSTOMER_ID','alice')
    tampered=json.loads(document);tampered['payload']['cap_usd']=100000;path.write_text(json.dumps(tampered))
    assert access.status()['state']=='invalid' and not access.entries_allowed()
    path.write_text(document)
    assert access.status(access.timestamp(p['expires_at']))['state']=='expired'
    assert not access.entries_allowed(initial_capital=float('nan'))


def test_cashflows_grace_idempotency_and_no_profit_based_upgrade(setup,monkeypatch,tmp_path):
    _,b,a,_,private,_,_=setup
    now=time.time();activate(setup,now=now)
    # Market profits never enter funded_capital. No comparison with live/marked equity.
    assert b.snapshot(a,now)['license']['funded_capital_usd']=='10000.00'
    p=b.cashflow('alice',private,'deposit:1','500',now+1)
    assert p['state']=='grace' and p['funded_capital_usd']=='10500.00'
    deadline=p['grace_ends_at']
    p=b.cashflow('alice',private,'deposit:1','500',now+2);assert p['funded_capital_usd']=='10500.00'
    with pytest.raises(BillingConflict):b.cashflow('alice',private,'deposit:1','600',now+3)
    p=b.cashflow('alice',private,'deposit:2','500',now+10);assert p['grace_ends_at']==deadline
    use_license(monkeypatch,tmp_path,setup,b.document(a))
    end=access.timestamp(deadline)
    assert access.status(end-1)['state']=='grace' and access.entries_allowed(end-1)
    assert access.status(end)['state']=='capital_exceeded' and not access.entries_allowed(end)
    p=b.cashflow('alice',private,'withdraw:1','-1000',now+20)
    assert p['state']=='active' and p['grace_ends_at'] is None


def test_prorated_upgrade_preserves_expiry_profit_exemption_and_renewal_revalues(setup):
    _,b,a,_,private,_,_=setup
    now=time.time();first=activate(setup,now=now)
    halfway=(access.timestamp(first['not_before'])+access.timestamp(first['expires_at']))/2
    q=b.quote(a,25000,1,'upgrade',halfway)
    assert q['price_cents']==2500 and q['expires_at']==first['expires_at']
    oid=order(b,a,25000,1,'upgrade',halfway)['id']
    # Even 40k of marked equity from profits does not force another tier mid-period.
    upgraded=b.approve(oid,private,'binance:alice123','40000','payment:upgrade',halfway)
    assert upgraded['expires_at']==first['expires_at'] and upgraded['funded_capital_usd']=='10000.00'
    with pytest.raises(BillingConflict):b.quote(a,25000,1,'subscription',halfway)
    end=access.timestamp(first['expires_at'])
    renewal=order(b,a,25000,3,now=end)['id']
    with pytest.raises(BillingConflict):b.approve(renewal,private,'binance:alice123','40000','payment:renew',end)
    b.cancel(a,renewal)
    renewal=order(b,a,50000,3,now=end)['id']
    renewed=b.approve(renewal,private,'binance:alice123','40000','payment:renew',end)
    assert renewed['funded_capital_usd']=='40000.00' and renewed['cap_usd']==50000


def test_wrong_issuer_cashflow_rolls_back(setup,tmp_path):
    _,b,a,_,_,_,_=setup
    activate(setup);before=b.document(a)
    private,public=tmp_path/'wrong.private.pem',tmp_path/'wrong.public.pem';customers.keygen(private,public)
    with pytest.raises(InvalidSignature):b.cashflow('alice',private,'deposit:wrong','500')
    assert b.document(a)==before


def test_install_license_keeps_positions_and_prevents_account_switch(setup,tmp_path,monkeypatch):
    _,b,a,_,private,public,_=setup
    root=tmp_path/'customers';directory=customers.create(root,'alice',private,public,8101,10000.)
    position=directory/'runtime/position-proof';position.write_text('existing-position')
    config=(directory/'runtime/config.json').read_bytes()
    activate(setup);source=tmp_path/'download.json';source.write_text(b.document(a))
    customers.install_license(root,'alice',source)
    assert (directory/'license/account_id').read_text().strip()=='binance:alice123'
    assert position.read_text()=='existing-position' and (directory/'runtime/config.json').read_bytes()==config
    with pytest.raises(ValueError,match='portal billing'):customers.renew(root,'alice',private)
    (directory/'license/account_id').write_text('binance:other123')
    with pytest.raises(ValueError,match='another exchange'):customers.install_license(root,'alice',source)


def test_http_ownership_csrf_price_validation_and_download(setup):
    store,b,a,bob,_,_,_=setup;origin='https://portal.test'
    with TestClient(create_app(store,origin=origin),base_url=origin) as client:
        assert client.get('/api/plans').status_code==200
        assert client.get('/api/me/license').status_code==401
        assert client.get('/manifest.webmanifest').json()['display']=='standalone'
        assert client.get('/portal-assets/icon-192.png').status_code==200
        r=client.post('/api/login',headers={'X-Portal-Request':'1'},json=dict(username='alice',password='test-password-strong'))
        h={'X-Portal-Request':'1','X-CSRF-Token':r.json()['csrf']}
        payload=dict(cap_usd=10000,months=3,kind='subscription')
        assert client.post('/api/me/license/quote',json=payload).status_code==403
        assert client.post('/api/me/license/quote',headers=h,json={**payload,'months':2}).status_code==422
        assert client.post('/api/me/license/quote',headers=h,json={**payload,'cap_usd':10000.0}).status_code==422
        assert client.post('/api/me/license/quote',headers=h,json=payload).json()['price_cents']==12900
        body={**payload,'expected_price_cents':12900,'request_key':str(uuid.uuid4())}
        assert client.post('/api/me/license/orders',headers=h,json={**body,'user_id':bob}).status_code==422
        oid=client.post('/api/me/license/orders',headers=h,json=body).json()['id']
        assert client.get('/api/me/license?user_id='+bob).json()['orders'][0]['id']==oid
        boboid=order(b,bob)['id']
        assert client.post('/api/me/license/orders/'+boboid+'/cancel',headers=h).status_code==404
        assert client.post('/api/me/license/approve',headers=h,json={}).status_code==404
        b.approve(oid,setup[4],'binance:alice123','10000','payment:http')
        download=client.get('/api/me/license/download')
        assert download.status_code==200 and 'attachment' in download.headers['content-disposition']
        assert download.headers['cache-control']=='no-store'
        assert access.verify_document(download.text,setup[5].read_bytes())['customer_id']=='alice'
        assert b.snapshot(bob)['license']['state']=='none'


def test_migration_preserves_billing_history_and_signed_document(setup,tmp_path):
    store,b,a,_,private,_,key=setup
    activate(setup);b.cashflow('alice',private,'deposit:migration','500')
    target=tmp_path/'migrated.db';counts=migrate_sqlite(store.path,target,key)
    assert counts['capital_licenses']==1 and counts['license_cashflows']==1 and counts['license_orders']==1
    copy=PortalStore(target,key)
    try:assert Billing(copy).document(a)==b.document(a)
    finally:copy.close()


def test_capital_block_still_allows_three_bot_exits(setup,tmp_path,monkeypatch,system):
    _,b,a,_,private,_,_=setup;now=time.time()
    activate(setup,now=now);b.cashflow('alice',private,'deposit:exits','1000',now+1)
    use_license(monkeypatch,tmp_path,setup,b.document(a))
    blocked=now+2+plans.GRACE_SECONDS
    assert not access.entries_allowed(blocked)
    p=setup_position(system,state='STATE_INITIAL')
    assert not system._activate(p,100.,blocked)
    assert not system._pyramid_add(p,'long',pd.Series(dtype=float),system.config.read(),blocked)
    # _insert uses wall clock; verify a seed breach also blocks the final insertion guard.
    old_seed=system.paper_seed;system.paper_seed=10001
    with pytest.raises(PermissionError):system._insert({})
    system.paper_seed=old_seed
    cs=C.Store(tmp_path/'c3.db');sl=C.Sleeve(C.load(C.Path(C.__file__).with_name('c3_config.json')),cs,system.data)
    ps=P.Store(tmp_path/'pa.db');pa=P.Sleeve(P.load(P.Path(P.__file__).with_name('pa_config.json')),ps,system.data)
    assert sl.open('AAVE/USDT:USDT','long',pd.Series(dict(atr=1,close=100,timestamp=0)),blocked) is None
    assert pa.open('LINK/USDT:USDT',{},blocked) is None
    for store,symbol in [(cs,'AAVE/USDT:USDT'),(ps,'LINK/USDT:USDT')]:
        with store.db() as db:db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,'long',100.,2.,95.,100.,1.,0,0,10.))
    system.data.prices[p['symbol']]=80.;system.data.prices['AAVE/USDT:USDT']=90.;system.data.prices['LINK/USDT:USDT']=90.
    system.watchdog(blocked);sl.watchdog(blocked);pa.watchdog(blocked)
    assert not system.db.positions() and not cs.positions() and not ps.positions()
