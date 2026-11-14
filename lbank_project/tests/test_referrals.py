"""Referral codes and admin-defined programs: discounts, rewards, credit, coupons and abuse limits."""
import pathlib
import tempfile
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import customer_manager
from portal_billing import Billing, BillingConflict
from portal_payments import PaymentConflict, Payments
from portal_referrals import ReferralConflict, Referrals, validate_config
from portal_server import create_app
from portal_store import PortalStore
from pricing_helpers import enable_test_prices
from db_targets import TARGETS, fresh_store

ORIGIN = 'https://avina.example'
PASSWORD = 'disposable-test-password'
KEYS = pathlib.Path(tempfile.mkdtemp())
customer_manager.keygen(KEYS / 'k', KEYS / 'p')


def program(referee=None, referrer=None):
    return dict(referee=referee or dict(type='none'), referrer=referrer or dict(type='none'))


@pytest.fixture(params=TARGETS)
def setup(request, tmp_path):
    store = fresh_store(request.param, tmp_path)
    admin = store.create_user('manager', PASSWORD, 'm@example.com');store.set_admin('manager')
    alice = store.create_user('alice', PASSWORD, 'a@example.com')
    enable_test_prices(store)
    referrals = Referrals(store)
    referrals.save_settings(admin, dict(enabled=True, attach_days=7, credit_max_percent=100))
    yield store, referrals, admin, alice
    store.close()


def join(store, referrals, name, code):
    user = store.create_user(name, PASSWORD, name + '@example.com')
    with store.db() as db:
        store.database.begin_write(db, 'register');referrals.attach(db, user, code)
    return user


def buy(store, user, product='signals', approve=True, cap=10000):
    billing = Billing(store)
    quote = billing.quote(user, cap, 1, product=product)
    oid = billing.order(user, cap, 1, 'subscription', str(uuid.uuid4()), quote['price_cents'], product=product)['id']
    if approve:
        billing.approve(oid, KEYS / 'k', payment_ref='tron:' + uuid.uuid4().hex)
        # Let the next test purchase start as a fresh subscription instead of an upgrade.
        with store.db() as db:db.execute('DELETE FROM capital_licenses WHERE user_id=?', (user,))
    return quote, oid


def test_two_sided_program_discounts_the_friend_and_credits_the_inviter(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Two-sided', program(dict(type='percent', value=10, purchases=1),
                                                             dict(type='credit', value=20)), True, True)
    code = referrals.account(alice)['code']
    assert len(code) == 8 and referrals.lookup(code.lower()) == dict(valid=True, code=code, offer=validate_config(
        program(dict(type='percent', value=10, purchases=1)))['referee'])
    bob = join(store, referrals, 'bob', code)
    quote, oid = buy(store, bob)
    assert quote['discounts'] == [dict(kind='referee', cents=quote['list_price_cents'] // 10, percent=10.0)]
    assert quote['price_cents'] == quote['list_price_cents'] - quote['list_price_cents'] // 10
    with store.db() as db:assert db.execute('SELECT price_cents FROM license_orders WHERE id=?', (oid,)).fetchone()['price_cents'] == quote['price_cents']
    account = referrals.account(alice)
    assert account['balance_cents'] == 2000 and account['stats'] == dict(signups=1, paying=1, earned_cents=2000)
    assert account['rewards'][0]['referee'] == 'bo***' and account['rewards'][0]['state'] == 'available'
    # Only the first purchase is discounted and, with the "first" trigger, rewarded.
    second, _ = buy(store, bob)
    assert second['discounts'] == [] and referrals.account(alice)['balance_cents'] == 2000
    # Alice's own purchase uses her credit; cancelling gives it back, approval consumes it.
    billing = Billing(store)
    quote = billing.quote(alice, 10000, 1, product='signals')
    assert quote['discounts'] == [dict(kind='credit', cents=2000, percent=None)]
    oid = billing.order(alice, 10000, 1, 'subscription', 'k1', quote['price_cents'], product='signals')['id']
    assert referrals.account(alice)['balance_cents'] == 0
    billing.cancel(alice, oid)
    assert referrals.account(alice)['balance_cents'] == 2000
    buy(store, alice)
    assert referrals.account(alice)['balance_cents'] == 0 and referrals.account(alice)['rewards'][0]['state'] == 'used'


def test_commission_tiers_hold_period_cap_and_every_purchase(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Partners', program(referrer=dict(
        type='commission', value=10, trigger='every', max_per_referee=2, hold_days=7, expiry_days=30, max_total_usd=0,
        tiers=[dict(referrals=2, value=20)])), True, True)
    code = referrals.account(alice)['code']
    bob, carol = join(store, referrals, 'bob', code), join(store, referrals, 'carol', code)
    q1, _ = buy(store, bob)
    q2, _ = buy(store, carol)  # second paying friend unlocks the 20% tier
    buy(store, bob)
    buy(store, bob)  # third purchase by bob is past max_per_referee
    account = referrals.account(alice)
    values = sorted(r['value'] for r in account['rewards'])
    assert values == sorted([q1['price_cents'] // 10, q2['price_cents'] // 5, q1['price_cents'] // 5])
    assert account['balance_cents'] == 0 and account['pending_cents'] == sum(values)
    later = time.time() + 8 * 86400
    assert referrals.account(alice, later)['balance_cents'] == sum(values)
    assert referrals.account(alice, time.time() + 31 * 86400 + 8 * 86400)['balance_cents'] == 0  # expired


def test_coupon_reward_cap_and_minimum_order(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Coupons', program(referrer=dict(type='coupon', value=25, trigger='every', min_order_usd=1)), True, True)
    code = referrals.account(alice)['code']
    bob = join(store, referrals, 'bob', code)
    buy(store, bob);buy(store, bob)
    assert [c['percent'] for c in referrals.account(alice)['coupons']] == [25.0, 25.0]
    quote = Billing(store).quote(alice, 10000, 1, product='signals')
    assert quote['discounts'] == [dict(kind='coupon', cents=quote['list_price_cents'] // 4, percent=25.0)]  # one coupon per order
    buy(store, alice)
    assert len(referrals.account(alice)['coupons']) == 1
    referrals.save_program(admin, None, 'Capped', program(referrer=dict(type='credit', value=30, trigger='every', max_total_usd=50)), True, True)
    dave = join(store, referrals, 'dave', code)
    buy(store, dave);buy(store, dave);buy(store, dave)
    assert sorted(r['value'] for r in referrals.account(alice)['rewards'] if r['kind'] == 'credit') == [2000, 3000]


def test_campaign_codes_limits_and_abuse_rules(setup):
    store, referrals, admin, alice = setup
    nowruz = referrals.save_program(admin, None, 'Nowruz', program(dict(type='fixed', value=5, purchases=0)), True, False)
    referrals.save_code(admin, 'nowruz-1405', None, nowruz['id'], 'Nowruz campaign', 1)
    bob = join(store, referrals, 'bob', 'NOWRUZ-1405')
    quote, _ = buy(store, bob)
    again, _ = buy(store, bob)
    assert quote['discounts'][0]['cents'] == 500 and again['discounts'][0]['cents'] == 500  # purchases=0 means every purchase
    with pytest.raises(ReferralConflict):join(store, referrals, 'carol', 'NOWRUZ-1405')  # max uses reached
    referrals.save_program(admin, nowruz['id'], 'Nowruz', program(dict(type='fixed', value=5)), False, False)
    assert referrals.lookup('NOWRUZ-1405') == dict(valid=False)
    with pytest.raises(ValueError):join(store, referrals, 'erin', 'MISSING')
    # Own code, a code of someone you invited, a second code and late attachment are refused.
    code = referrals.account(alice)['code']
    with pytest.raises(ReferralConflict):referrals.attach_later(alice, code)
    frank = join(store, referrals, 'frank', code)
    frank_code = referrals.account(frank)['code']
    with pytest.raises(ReferralConflict):referrals.attach_later(alice, frank_code)
    with pytest.raises(ReferralConflict):referrals.attach_later(frank, frank_code)
    grace = store.create_user('grace', PASSWORD, 'g@example.com')
    with store.db() as db:db.execute("INSERT INTO audit(user_id,event,at) VALUES(?,'registered',?)", (grace, time.time() - 8 * 86400))
    with pytest.raises(ReferralConflict):referrals.attach_later(grace, code)
    assert referrals.set_code(alice, 'alice-vip') == dict(code='ALICE-VIP')
    with pytest.raises(ReferralConflict):referrals.set_code(bob, 'ALICE-VIP')
    assert referrals.account(alice)['code'] == 'ALICE-VIP' and referrals.lookup(code)['valid']  # old links keep working
    with pytest.raises(ReferralConflict):referrals.delete_program(admin, nowruz['id'])
    with pytest.raises(PermissionError):referrals.save_program(alice, None, 'Mine', program(), True, True)
    with pytest.raises(ValueError):validate_config(program(dict(type='percent', value=150)))


def test_full_credit_signal_order_needs_no_payment_and_is_queued(setup):
    store, referrals, admin, alice = setup
    Payments(store).save_settings(admin, dict(tron_address='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', auto_approve_signals=True))
    referrals.grant(admin, 'alice', 'credit', 100000, 'Launch gift')
    quote, oid = buy(store, alice, approve=False)
    assert quote['price_cents'] == 0
    with pytest.raises(PaymentConflict):Payments(store).create_invoice(alice, oid, 'tron', 'USDT')
    with store.db() as db:
        assert db.execute('SELECT state,payment_ref FROM license_approvals WHERE order_id=?', (oid,)).fetchone()['payment_ref'] == 'credit-' + oid
    rid = referrals.account(alice)['rewards'][0]['id']
    referrals.void(admin, rid)
    assert referrals.account(alice)['rewards'][0]['state'] == 'void'


def test_disabled_referrals_change_nothing(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Half off', program(dict(type='percent', value=50)), True, True)
    code = referrals.account(alice)['code']
    bob = join(store, referrals, 'bob', code)
    referrals.save_settings(admin, dict(enabled=False, attach_days=7, credit_max_percent=100))
    assert Billing(store).quote(bob, 10000, 1, product='signals')['discounts'] == []
    assert referrals.account(bob) == dict(enabled=False) and referrals.lookup(code) == dict(valid=False)


def test_referral_api_for_visitors_customers_and_admins(setup):
    store, referrals, admin, alice = setup
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        def login(name):
            r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username=name, password=PASSWORD))
            return {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}
        a = login('manager')
        config = program(dict(type='percent', value=15), dict(type='credit', value=10))
        made = client.post('/api/admin/referrals/programs', headers=a, json=dict(name='Main', config=config, is_default=True))
        assert made.status_code == 201
        assert client.post('/api/admin/referrals/programs', headers=a, json=dict(name='Bad', config=program(dict(type='percent', value=0)))).status_code == 422
        assert client.post('/api/admin/referrals/codes', headers=a, json=dict(code='INFLUENCER', owner='alice', max_uses=100)).status_code == 201
        assert client.post('/api/admin/referrals/codes', headers=a, json=dict(code='INFLUENCER')).status_code == 409
        assert client.put('/api/admin/referrals/codes/INFLUENCER', headers=a, json=dict(code='INFLUENCER', label='YouTube', max_uses=5)).status_code == 200
        assert client.get('/api/referral/influencer').json()['offer']['value'] == 15
        assert client.get('/api/referral/nope').json() == {'valid': False}
        signup = dict(username='bob', password=PASSWORD, password_confirmation=PASSWORD, email='bob@example.com')
        headers = {'X-Portal-Request': '1', 'Origin': ORIGIN}
        assert client.post('/api/register', headers=headers, json=dict(signup, referral_code='WRONG')).status_code == 422
        assert client.post('/api/register', headers=headers, json=dict(signup, referral_code='influencer')).status_code == 201
        me = client.get('/api/me/referral').json()
        assert me['referred']['code'] == 'INFLUENCER' and me['referred']['offer']['value'] == 15 and not me['can_attach']
        b = {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': client.post('/api/login', headers=headers, json=dict(username='bob', password=PASSWORD)).json()['csrf']}
        assert client.put('/api/me/referral/code', headers=b, json=dict(code='INFLUENCER')).status_code == 409
        assert client.put('/api/me/referral/code', headers=b, json=dict(code='BOB-2026')).json() == {'code': 'BOB-2026'}
        quote = client.post('/api/me/license/quote', headers=b, json=dict(cap_usd=10000, months=1, product='signals')).json()
        assert quote['discounts'][0]['kind'] == 'referee' and quote['price_cents'] < quote['list_price_cents']
        assert client.get('/api/admin/referrals').status_code == 403
        assert client.post('/api/admin/referrals/rewards', headers=b, json=dict(username='bob', kind='credit', value=5)).status_code == 403
        a = login('manager')
        overview = client.get('/api/admin/referrals').json()
        assert overview['totals']['referrals'] == 1 and overview['codes'][0]['code'] == 'INFLUENCER' and overview['codes'][0]['owner'] == 'alice'
        assert client.post('/api/admin/referrals/rewards', headers=a, json=dict(username='nobody', kind='credit', value=5)).status_code == 422
        assert client.post('/api/admin/referrals/rewards', headers=a, json=dict(username='bob', kind='coupon', value=30)).status_code == 201
        assert client.put('/api/admin/referrals/settings', headers=a, json=dict(enabled=False, attach_days=3, credit_max_percent=50)).json()['credit_max_percent'] == 50
