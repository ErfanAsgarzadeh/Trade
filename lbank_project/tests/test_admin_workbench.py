"""RBAC, price publication, operator audit and fenced asynchronous signing."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid
import sqlite3

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from portal_store import PortalStore
from portal_server import create_app
from portal_admin_store import AdminStore
from portal_billing import Billing,BillingConflict
from portal_issuer import Issuer
from portal_migrate import migrate_sqlite
import product_pricing
import customer_manager
from capital_plans import PRICES,TERMS
from pricing_helpers import enable_test_prices

ORIGIN='https://portal.test';PASSWORD='disposable-test-password'

@pytest.fixture
def setup(tmp_path):
    key=Fernet.generate_key();store=PortalStore(tmp_path/'portal.db',key)
    admin=store.create_user('manager',PASSWORD);store.set_admin('manager')
    alice=store.create_user('alice',PASSWORD);bob=store.create_user('bob',PASSWORD)
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem';customer_manager.keygen(private,public)
    yield store,admin,alice,bob,private,public,key
    store.close()


def login(client,name='manager'):
    response=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD))
    assert response.status_code==200,response.text
    return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':response.json()['csrf']}


def order(setup,user=None,product='signals'):
    store,admin,alice,_,_,_,_=setup
    if not product_pricing.catalog(store)['products'][0]['sales_enabled']:enable_test_prices(store)
    user=user or alice;b=Billing(store)
    q=b.quote(user,10000,1,product=product)
    return b.order(user,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product=product)['id']


def test_admin_role_never_granted_by_signup_and_all_admin_routes_require_it(setup):
    store,admin,alice,_,_,_,_=setup
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        for url in ('overview','users','orders','pricing','audit'):assert client.get('/api/admin/'+url).status_code==401
        headers=login(client,'alice');assert client.get('/api/me').json()['role']=='customer'
        for url in ('overview','users','orders','pricing','audit'):assert client.get('/api/admin/'+url).status_code==403
        assert client.patch('/api/admin/users/'+alice,headers=headers,json={'disabled':True}).status_code==403
        assert client.post('/api/admin/orders/fake/approve',headers=headers,json={}).status_code==403
        assert client.put('/api/admin/pricing/signals',headers=headers,json={}).status_code==403
        assert client.post('/api/register',headers=headers,json=dict(username='evil-user',password=PASSWORD,password_confirmation=PASSWORD,role='admin')).status_code==422
        assert client.patch('/api/me',headers=headers,json={'role':'admin'}).status_code==405


def test_admin_can_read_bounded_lists_without_customer_secrets(setup):
    store,_,alice,_,_,_,_=setup
    store.save_connection(alice,'spot','secret-customer-api-key','private-customer-secret')
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        login(client)
        response=client.get('/api/admin/users')
        assert response.status_code==200 and response.json()['total']==3
        assert 'password' not in response.text and 'encrypted' not in response.text and 'runtime/' not in response.text
        assert 'secret-customer' not in response.text and 'private-customer' not in response.text
        assert client.get('/api/admin/users?search=alice').json()['total']==1
        assert client.get('/api/admin/users?limit=101').status_code==422
        assert client.get('/api/admin/users?offset=-1').status_code==422
        assert client.get('/api/admin/overview').json()['counts']['users']==3
        assert not any(p['sales_enabled'] for p in client.get('/api/admin/pricing').json()['products'])


def test_admin_mutations_require_csrf_and_cannot_modify_admin_accounts(setup):
    store,admin,alice,_,_,_,_=setup
    token,_=store.login('alice',PASSWORD)
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        h=login(client)
        assert client.patch('/api/admin/users/'+alice,json={'disabled':True}).status_code==403
        assert client.patch('/api/admin/users/'+alice,headers={**h,'Origin':'https://evil.test'},json={'disabled':True}).status_code==403
        assert client.patch('/api/admin/users/'+admin,headers=h,json={'disabled':True}).status_code==409
        assert client.patch('/api/admin/users/'+alice,headers=h,json={'disabled':True,'role':'admin'}).status_code==422
        assert client.patch('/api/admin/users/'+alice,headers=h,json={'disabled':True}).status_code==200
        assert store.session(token) is None and store.login('alice',PASSWORD) is None
        assert client.patch('/api/admin/users/'+alice,headers=h,json={'disabled':False}).status_code==200
        assert store.login('alice',PASSWORD)
        actions=[e['action'] for e in client.get('/api/admin/audit').json()['items']]
        assert 'user_disabled' in actions and 'user_enabled' in actions


def test_role_revocation_invalidates_existing_session(setup):
    store,_,_,_,_,_,_=setup
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        login(client);assert client.get('/api/admin/overview').status_code==200
        store.set_admin('manager',False)
        assert client.get('/api/admin/overview').status_code==401
        login(client);assert client.get('/api/admin/overview').status_code==403


def test_price_draft_requires_separate_confirmed_publication_and_versions(setup):
    store,_,_,_,_,_,_=setup
    prices={str(cap):{str(m):str(PRICES[cap][i]) for i,m in enumerate(TERMS)} for cap in PRICES}
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        h=login(client);payload=dict(expected_version='unconfigured',prices=prices)
        assert client.put('/api/admin/pricing/signals',headers=h,json=payload).status_code==200
        saved=next(p for p in client.get('/api/plans').json()['products'] if p['product']=='signals')
        assert not saved['sales_enabled']
        assert client.put('/api/admin/pricing/signals',headers=h,json=payload).status_code==409
        assert client.post('/api/admin/pricing/signals/open',headers=h,json={'expected_version':saved['version']}).status_code==422
        assert client.post('/api/admin/pricing/signals/open',headers=h,json={'expected_version':saved['version'],'confirmation':'FINAL_PRICES_CONFIRMED'}).status_code==200
        opened=next(p for p in client.get('/api/plans').json()['products'] if p['product']=='signals')
        assert opened['sales_enabled']
        assert client.post('/api/admin/pricing/signals/close',headers=h,json={'expected_version':saved['version']}).status_code==409
        assert client.post('/api/admin/pricing/signals/close',headers=h,json={'expected_version':opened['version']}).status_code==200
        assert not next(p for p in client.get('/api/plans').json()['products'] if p['product']=='signals')['sales_enabled']


def test_ui_approval_queues_without_private_key_and_worker_completes(setup,monkeypatch):
    store,_,alice,_,private,_,_=setup;oid=order(setup)
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        h=login(client)
        body=dict(payment_ref='payment:admin123',confirmation='PAYMENT_AND_ACCOUNT_VERIFIED')
        assert client.post('/api/admin/orders/'+oid+'/approve',headers=h,json={}).status_code==422
        queued=client.post('/api/admin/orders/'+oid+'/approve',headers=h,json=body)
        assert queued.status_code==202 and queued.json()['status']=='queued'
        assert Billing(store).snapshot(alice)['license']['state']=='none'
        assert client.post('/api/admin/orders/'+oid+'/approve',headers=h,json=body).json()['already_pending']
        assert Issuer(store,private).once()
        assert Billing(store).snapshot(alice)['license']['state']=='active'
        assert not Issuer(store,private).once()
        assert client.get('/api/admin/orders?status=approved').json()['items'][0]['approval_state']=='completed'
        assert 'license_issued' in [e['action'] for e in client.get('/api/admin/audit').json()['items']]


def test_rejection_and_reused_payment_are_fenced(setup):
    store,admin,alice,bob,private,_,_=setup;oid=order(setup);other=order(setup,bob)
    workbench=AdminStore(store)
    workbench.request_approval(admin,oid,'receipt:shared')
    with pytest.raises(BillingConflict):workbench.request_approval(admin,other,'receipt:shared')
    workbench.reject(admin,oid,'پرداخت بررسی و تأیید نشد')
    assert not Issuer(store,private).once()
    assert Billing(store).snapshot(alice)['license']['state']=='none'
    assert Billing(store).snapshot(alice)['orders'][0]['status']=='rejected'


def test_stale_signing_lease_and_demoted_requester_cannot_issue(setup):
    store,admin,alice,_,private,_,_=setup;oid=order(setup);AdminStore(store).request_approval(admin,oid,'receipt:lease')
    worker=Issuer(store,private);old=worker.claim()
    with store.db() as db:db.execute('UPDATE license_approvals SET lease_until=0 WHERE id=?',(old['id'],))
    new=worker.claim()
    with pytest.raises(BillingConflict):Billing(store).approve(oid,private,payment_ref='receipt:lease',approval_job=old)
    store.set_admin('manager',False)
    with pytest.raises(PermissionError):Billing(store).approve(oid,private,payment_ref='receipt:lease',approval_job=new)
    assert Billing(store).snapshot(alice)['license']['state']=='none'


def test_disabling_customer_before_signing_prevents_activation(setup):
    store,admin,alice,_,private,_,_=setup;oid=order(setup);AdminStore(store).request_approval(admin,oid,'receipt:disabled')
    AdminStore(store).set_disabled(admin,alice,True)
    assert not Issuer(store,private).once()
    assert Billing(store).snapshot(alice)['license']['state']=='none'


def test_failed_issuance_records_generic_error_and_can_be_retried(setup,monkeypatch):
    store,admin,alice,_,private,_,_=setup;oid=order(setup);admin_store=AdminStore(store)
    admin_store.request_approval(admin,oid,'receipt:retry')
    original=Billing.approve
    def fail(*args,**kwargs):raise ValueError('must-not-leak-private-key-path-or-secret')
    monkeypatch.setattr(Billing,'approve',fail);assert Issuer(store,private).once()
    data=admin_store.orders();assert data['items'][0]['error_code']=='issuance_failed'
    assert 'must-not-leak' not in json.dumps(data)
    monkeypatch.setattr(Billing,'approve',original)
    admin_store.request_approval(admin,oid,'receipt:retry');assert Issuer(store,private).once()
    assert Billing(store).snapshot(alice)['license']['state']=='active'


def test_approvals_claimed_once_under_concurrency(setup):
    store,admin,_,_,private,_,_=setup;oid=order(setup);AdminStore(store).request_approval(admin,oid,'receipt:concurrent')
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:Issuer(store,private).claim(),range(4)))
    assert sum(r is not None for r in results)==1


def test_offline_migration_preserves_roles_audit_and_resets_signing_leases(setup,tmp_path):
    store,admin,_,_,private,_,key=setup;oid=order(setup);AdminStore(store).request_approval(admin,oid,'receipt:migration');Issuer(store,private).claim()
    target=tmp_path/'new.db';migrate_sqlite(store.path,target,key)
    copy=PortalStore(target,key)
    try:
        with copy.db() as db:
            assert db.execute("SELECT role FROM users WHERE username='manager'").fetchone()['role']=='admin'
            job=db.execute('SELECT state,lease_token,attempts FROM license_approvals').fetchone()
            assert job['state']=='queued' and job['lease_token'] is None and job['attempts']==0
        assert AdminStore(copy).events()['total']>=2
    finally:copy.close()
