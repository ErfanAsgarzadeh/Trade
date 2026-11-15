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
from totp_helpers import AUTH, enable_totp, extra, signup_token

ORIGIN = 'https://avina.example'
PASSWORD = 'disposable-test-password'
KEYS = pathlib.Path(tempfile.mkdtemp())
customer_manager.keygen(KEYS / 'k', KEYS / 'p')


def program(referee=None, referrer=None):
    return dict(referee=referee or dict(type='none'), referrer=referrer or dict(type='none'))


@pytest.fixture(params=TARGETS)
def setup(request, tmp_path):
    store = fresh_store(request.param, tmp_path)
    admin = store.create_user('manager', PASSWORD, 'm@example.com');store.set_admin('manager');enable_totp(store, 'manager')
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
            r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username=name, password=PASSWORD, **extra(name)))
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
        signup = dict(username='bob', password=PASSWORD, password_confirmation=PASSWORD, email='bob@example.com', form_token=signup_token(store))
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
        assert client.post('/api/admin/referrals/rewards', headers=b, json=dict(username='bob', kind='credit', value=5, totp='123456')).status_code == 403
        a = login('manager')
        overview = client.get('/api/admin/referrals').json()
        assert overview['totals']['referrals'] == 1 and overview['codes'][0]['code'] == 'INFLUENCER' and overview['codes'][0]['owner'] == 'alice'
        assert client.post('/api/admin/referrals/rewards', headers=a, json=dict(username='nobody', kind='credit', value=5, totp=AUTH['manager'].code())).status_code == 422
        assert client.post('/api/admin/referrals/rewards', headers=a, json=dict(username='bob', kind='coupon', value=30, totp=AUTH['manager'].code())).status_code == 201
        assert client.put('/api/admin/referrals/settings', headers=a, json=dict(enabled=False, attach_days=3, credit_max_percent=50)).json()['credit_max_percent'] == 50


# ---- Reserved codes, taking a code back, self-invite review and the discount ceiling ----------------------------------

def test_customers_cannot_claim_reserved_codes_but_admin_campaign_codes_may_use_them(setup):
    store, referrals, admin, alice = setup
    for name in ('avina', 'ARTAX', 'Admin', 'support', 'OFFICIAL', 'staff', 'TEAM', 'help', 'VIP', 'free', 'BONUS', 'gift', 'nowruz', 'YALDA',
                 'AVINA-VIP', 'avina2026', 'ARTAX-FANS', 'artaxx'):
        with pytest.raises(ValueError, match='reserved'):referrals.set_code(alice, name)
    assert referrals.set_code(alice, 'my-own-code') == dict(code='MY-OWN-CODE')
    assert referrals.set_code(alice, 'avatar') == dict(code='AVATAR')  # similar, not reserved
    assert referrals.save_code(admin, 'AVINA', None, None, 'official campaign') == dict(code='AVINA')
    assert referrals.save_code(admin, 'NOWRUZ', None, None, 'holiday') == dict(code='NOWRUZ')
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        h = {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='alice', password=PASSWORD)).json()['csrf']}
        assert client.put('/api/me/referral/code', headers=h, json=dict(code='STAFF')).status_code == 422


def test_an_admin_can_take_back_a_personal_code_and_the_owner_gets_a_new_random_one(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Main', program(dict(type='percent', value=10)), True, True)
    old = referrals.account(alice)['code']
    referrals.set_code(alice, 'ALICE-VIP-X')
    custom = referrals.account(alice)['code']
    assert custom == 'ALICE-VIP-X' and referrals.lookup(custom)['valid']
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='manager', password=PASSWORD, **extra('manager')))
        a = {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}
        taken = client.put('/api/admin/referrals/codes/' + custom, headers=a, json=dict(code=custom, active=False, label='abuse'))
        assert taken.status_code == 200
        assert client.put('/api/admin/referrals/codes/NOPE-CODE', headers=a, json=dict(code='NOPE-CODE', active=False)).status_code == 404
    assert referrals.lookup(custom) == dict(valid=False)
    fresh = referrals.account(alice)['code']
    assert fresh not in (custom, old) or fresh == old  # an earlier active personal code may be reused, never the one taken back
    assert fresh != custom and referrals.lookup(fresh)['valid']
    with store.db() as db:
        referrals.save_code(admin, old, None, None, '', 0, False, False)
        referrals.save_code(admin, fresh, None, None, '', 0, False, False)
        assert db.execute("SELECT COUNT(*) AS n FROM referral_codes WHERE user_id=? AND personal=1 AND active=1", (alice,)).fetchone()['n'] == 0
    third = referrals.account(alice)['code']
    assert len(third) == 8 and third not in (custom, old, fresh) and referrals.lookup(third)['valid']


def pay_and_buy(store, referrals, admin, user, sender, product='signals'):
    """Buy through a real invoice paid on-chain from `sender`, then approve the order."""
    payments = Payments(store)
    if not payments.methods():payments.save_settings(admin, dict(tron_address='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'))
    billing = Billing(store)
    quote = billing.quote(user, 10000, 1, product=product)
    oid = billing.order(user, 10000, 1, 'subscription', str(uuid.uuid4()), quote['price_cents'], product=product)['id']
    invoice = payments.create_invoice(user, oid, 'tron', 'USDT')
    ref = 'tron:' + uuid.uuid4().hex
    assert payments.record_transfer('tron', 'USDT', ref, sender, 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', invoice['amount_micro'], time.time())
    billing.approve(oid, KEYS / 'k', payment_ref=ref)
    with store.db() as db:db.execute('DELETE FROM capital_licenses WHERE user_id=?', (user,))
    return oid


def test_a_reward_for_a_purchase_paid_from_the_inviters_own_wallet_waits_for_review(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Credit', program(referrer=dict(type='credit', value=20, trigger='every')), True, True)
    code = referrals.account(alice)['code']
    bob, carol = join(store, referrals, 'bob', code), join(store, referrals, 'carol', code)
    pay_and_buy(store, referrals, admin, alice, 'TAliceWallet')  # the inviter has paid from this wallet
    pay_and_buy(store, referrals, admin, carol, 'TCarolOwnWallet')  # a genuine friend, another wallet: usable at once
    assert referrals.account(alice)['balance_cents'] == 2000
    oid = pay_and_buy(store, referrals, admin, bob, 'taliceWALLET')  # same wallet, other letter case
    account = referrals.account(alice)
    assert account['balance_cents'] == 2000 and account['pending_cents'] == 0 and account['stats']['earned_cents'] == 2000
    assert sorted(r['state'] for r in account['rewards']) == ['available', 'review']
    review = next(r for r in account['rewards'] if r['state'] == 'review')
    with store.db() as db:
        assert db.execute('SELECT held,status FROM referral_rewards WHERE id=?', (review['id'],)).fetchone()['held'] == 1
        assert db.execute("SELECT COUNT(*) AS n FROM telegram_outbox").fetchone()['n'] == 0
    overview = referrals.admin_overview()
    assert next(r for r in overview['rewards'] if r['id'] == review['id'])['state'] == 'review' and overview['totals']['credit_cents'] == 2000
    assert overview['totals']['outstanding_cents'] == 2000
    quote = Billing(store).quote(alice, 10000, 1, product='signals')
    assert quote['discounts'] == [dict(kind='credit', cents=2000, percent=None)]  # the held reward is not spendable
    with pytest.raises(PermissionError):referrals.release_held(alice, review['id'])
    with pytest.raises(LookupError):referrals.release_held(admin, 'no-such-reward')
    referrals.release_held(admin, review['id'])
    assert referrals.account(alice)['balance_cents'] == 4000 and next(r for r in referrals.account(alice)['rewards'] if r['id'] == review['id'])['state'] == 'available'
    with pytest.raises(LookupError):referrals.release_held(admin, review['id'])  # already released
    with store.db() as db:
        assert db.execute("SELECT 1 FROM admin_events WHERE action='referral_reward_released' AND target=?", (review['id'],)).fetchone()
        assert db.execute("SELECT COUNT(*) AS n FROM telegram_outbox").fetchone()['n'] == 0  # no Telegram linked in this test
    # Voiding also works on a held reward.
    dave = join(store, referrals, 'dave', code)
    pay_and_buy(store, referrals, admin, dave, 'TAliceWallet')
    held = next(r for r in referrals.account(alice)['rewards'] if r['state'] == 'review')
    referrals.void(admin, held['id'])
    assert next(r for r in referrals.account(alice)['rewards'] if r['id'] == held['id'])['state'] == 'void' and referrals.account(alice)['balance_cents'] == 4000


def test_review_and_release_routes(setup):
    store, referrals, admin, alice = setup
    referrals.save_program(admin, None, 'Credit', program(referrer=dict(type='credit', value=20, trigger='every')), True, True)
    bob = join(store, referrals, 'bob', referrals.account(alice)['code'])
    pay_and_buy(store, referrals, admin, alice, 'TSame');pay_and_buy(store, referrals, admin, bob, 'TSame')
    rid = next(r['id'] for r in referrals.account(alice)['rewards'] if r['state'] == 'review')
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        def login(name):
            r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username=name, password=PASSWORD, **extra(name)))
            return {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}
        assert client.post(f'/api/admin/referrals/rewards/{rid}/release', headers=login('alice')).status_code == 403
        a = login('manager')
        assert [r['state'] for r in client.get('/api/admin/referrals').json()['rewards'] if r['id'] == rid] == ['review']
        assert client.post('/api/admin/referrals/rewards/nope/release', headers=a).status_code == 404
        assert client.post(f'/api/admin/referrals/rewards/{rid}/release', headers=a).json() == {'status': 'released'}
        assert client.post(f'/api/admin/referrals/rewards/{rid}/release', headers=a).status_code == 404


def test_all_discounts_together_stay_within_the_global_ceiling(setup):
    store, referrals, admin, alice = setup
    with store.db() as db:assert referrals.settings(db)['max_discount_percent'] == 100  # default: no extra limit
    referrals.save_program(admin, None, 'Big', program(dict(type='percent', value=40, purchases=0), dict(type='credit', value=100, trigger='every')), True, True)
    code = referrals.account(alice)['code'];bob = join(store, referrals, 'bob', code)
    list_price = Billing(store).quote(bob, 10000, 1, product='signals')['list_price_cents']
    assert Billing(store).quote(bob, 10000, 1, product='signals')['discounts'] == [dict(kind='referee', cents=list_price * 40 // 100, percent=40.0)]
    for bad in (-1, 101, True, 'x'):
        with pytest.raises(ValueError):referrals.save_settings(admin, dict(enabled=True, attach_days=7, credit_max_percent=100, max_discount_percent=bad))
    assert referrals.save_settings(admin, dict(enabled=True, attach_days=7, credit_max_percent=100, max_discount_percent=25))['max_discount_percent'] == 25
    quote = Billing(store).quote(bob, 10000, 1, product='signals')
    assert [d['cents'] for d in quote['discounts']] == [list_price * 25 // 100] and quote['price_cents'] == list_price - list_price * 25 // 100
    # Referee discount, coupon and credit combined: 25% of the list price at most, the order of application unchanged.
    referrals.grant(admin, 'bob', 'coupon', 10);referrals.grant(admin, 'bob', 'credit', 1000)
    for ceiling, expected in ((100, [list_price * 40 // 100, (list_price - list_price * 40 // 100) // 10]), (30, [list_price * 30 // 100]), (0, [])):
        referrals.save_settings(admin, dict(enabled=True, attach_days=7, credit_max_percent=100, max_discount_percent=ceiling))
        quote = Billing(store).quote(bob, 10000, 1, product='signals')
        spent = sum(d['cents'] for d in quote['discounts'])
        assert spent <= list_price * ceiling // 100 and quote['price_cents'] == list_price - spent
        if ceiling != 100:assert [d['cents'] for d in quote['discounts']] == expected
        else:assert [d['cents'] for d in quote['discounts']][:2] == expected
    # An order placed under the ceiling reserves only what it uses; the rest stays available.
    referrals.save_settings(admin, dict(enabled=True, attach_days=7, credit_max_percent=100, max_discount_percent=30))
    Billing(store).order(bob, 10000, 1, 'subscription', 'k-ceiling', Billing(store).quote(bob, 10000, 1, product='signals')['price_cents'], product='signals')
    with store.db() as db:
        assert db.execute("SELECT COALESCE(SUM(remaining),0) AS n FROM referral_rewards WHERE user_id=? AND kind='credit'", (uid(store, 'bob'),)).fetchone()['n'] == 100000
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username='manager', password=PASSWORD, **extra('manager')))
        a = {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}
        assert client.put('/api/admin/referrals/settings', headers=a, json=dict(enabled=True, attach_days=3, credit_max_percent=50, max_discount_percent=40)).json()['max_discount_percent'] == 40
        assert client.put('/api/admin/referrals/settings', headers=a, json=dict(enabled=True, attach_days=3, credit_max_percent=50, max_discount_percent=101)).status_code == 422
        assert client.put('/api/admin/referrals/settings', headers=a, json=dict(enabled=True, attach_days=3, credit_max_percent=50)).json()['max_discount_percent'] == 100


def uid(store, name):
    with store.db() as db:return db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()['id']


def test_every_referral_code_write_takes_the_shared_lock_last_and_collisions_retry(setup, monkeypatch):
    store, referrals, admin, alice = setup
    events = []
    real_begin, real_also = store.database.begin_write, store.database.also_lock
    monkeypatch.setattr(store.database, 'begin_write', lambda db, scope: (events.append(('begin', scope)), real_begin(db, scope))[1])
    monkeypatch.setattr(store.database, 'also_lock', lambda db, scope: (events.append(('also', scope)), real_also(db, scope))[1])
    # A personal code that collides with an existing one is drawn again instead of failing.
    import portal_referrals
    with store.db() as db:db.execute("INSERT INTO referral_codes(code,personal,created) VALUES('AAAAAAAA',0,1)")
    draws = iter('A' * 8 + 'B' * 8)
    monkeypatch.setattr(portal_referrals.secrets, 'choice', lambda alphabet: next(draws))
    assert referrals.account(alice)['code'] == 'BBBBBBBB'
    assert events[0] == ('begin', 'billing:' + alice) and events[-1] == ('also', 'referral-codes')
    monkeypatch.undo()
    events.clear()
    monkeypatch.setattr(store.database, 'begin_write', lambda db, scope: (events.append(('begin', scope)), real_begin(db, scope))[1])
    monkeypatch.setattr(store.database, 'also_lock', lambda db, scope: (events.append(('also', scope)), real_also(db, scope))[1])
    referrals.save_code(admin, 'SPRING', None, None, 'x', 1, True, True)
    assert events == [('begin', 'admin-authority'), ('also', 'referral-codes')]
    events.clear()
    bob = store.create_user('bobby', PASSWORD, 'bobby@example.com')
    referrals.attach_later(bob, 'SPRING')
    assert events[:2] == [('begin', 'billing:' + bob), ('also', 'referral-codes')]
    events.clear()
    carol = store.create_user('carol', PASSWORD, 'carol@example.com')
    with pytest.raises(ReferralConflict):referrals.attach_later(carol, 'SPRING')   # max_uses=1 was consumed above
    with store.db() as db:assert db.execute("SELECT uses FROM referral_codes WHERE code='SPRING'").fetchone()['uses'] == 1
    events.clear()
    referrals.set_code(alice, 'mycode')
    assert events == [('begin', 'referral-codes')]
    with pytest.raises(ReferralConflict):referrals.set_code(bob, 'mycode')
    with pytest.raises(ReferralConflict):referrals.save_code(admin, 'MYCODE', None, None, '', 0, True, True)


def test_concurrent_attaches_never_exceed_max_uses(setup):
    store, referrals, admin, alice = setup
    if not store.database.postgres:pytest.skip('Threads over one SQLite file only prove the same thing more slowly')
    import threading
    referrals.save_code(admin, 'LIMITED', None, None, '', 2, True, True)
    users = [store.create_user('racer%d' % i, PASSWORD, 'racer%d@example.com' % i) for i in range(6)]
    results = []

    def go(user):
        try:referrals.attach_later(user, 'LIMITED');results.append('ok')
        except ReferralConflict:results.append('limit')
    threads = [threading.Thread(target=go, args=(u,)) for u in users]
    [t.start() for t in threads];[t.join() for t in threads]
    assert results.count('ok') == 2
    with store.db() as db:assert db.execute("SELECT uses FROM referral_codes WHERE code='LIMITED'").fetchone()['uses'] == 2
