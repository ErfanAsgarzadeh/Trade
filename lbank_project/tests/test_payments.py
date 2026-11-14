"""Stablecoin payments to the owner's wallet: unique amounts, on-chain matching without a hash, admin settings."""
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from portal_billing import Billing
from portal_payments import Payments, PaymentConflict, Watcher, amount_text, bsc_address, tron_address, TOKENS
from portal_server import create_app
from portal_store import PortalStore
from pricing_helpers import enable_test_prices
from db_targets import TARGETS, fresh_store

ORIGIN='https://avina.example';PASSWORD='disposable-test-password'
TRON='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'          # a valid TRON address (the USDT contract, used only as a test target)
BSC='0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed'


@pytest.fixture(params=TARGETS)
def store(request,tmp_path):
    store=fresh_store(request.param,tmp_path)
    store.create_user('manager',PASSWORD,'m@example.com');store.set_admin('manager')
    store.create_user('alice',PASSWORD,'a@example.com');store.create_user('bob',PASSWORD,'b@example.com')
    enable_test_prices(store)
    yield store
    store.close()


def uid(store,name):
    with store.db() as db:return db.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()['id']


def order(store,name='alice',product='signals'):
    user=uid(store,name);b=Billing(store);q=b.quote(user,10000,1,product=product)
    return user,b.order(user,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product=product)['id'],q['price_cents']


def configure(store,auto=False):
    return Payments(store).save_settings(uid(store,'manager'),dict(tron_address=TRON,bsc_address=BSC,invoice_minutes=60,auto_approve_signals=auto))


def test_addresses_are_checked():
    assert tron_address(TRON)==TRON and bsc_address(BSC)==BSC and bsc_address(BSC.lower())==BSC.lower()
    for bad in ('T'+'1'*33,TRON[:-1]+'u','0x123',BSC[:-1]+'d'.upper() if BSC[-1]!='D' else BSC[:-1]+'e'):
        with pytest.raises(ValueError):
            (tron_address if bad.startswith('T') else bsc_address)(bad)


def test_only_admins_set_receiving_addresses_and_methods_follow_them(store):
    payments=Payments(store)
    assert payments.methods()==[]
    with pytest.raises(PermissionError):payments.save_settings(uid(store,'alice'),dict(tron_address=TRON))
    with pytest.raises(ValueError):payments.save_settings(uid(store,'manager'),dict(tron_address='Tnot-valid'))
    settings=configure(store)
    assert {(m['network'],m['token']) for m in settings['methods']}=={('tron','USDT'),('bsc','USDT'),('bsc','USDC')}
    with store.db() as db:assert db.execute("SELECT 1 FROM admin_events WHERE action='payment_settings_saved'").fetchone()


def test_each_open_invoice_has_a_unique_exact_amount_and_switching_method_replaces_it(store):
    configure(store);payments=Payments(store)
    alice,a,price=order(store,'alice');bob,b,_=order(store,'bob')
    first=payments.create_invoice(alice,a,'bsc','USDT')
    assert first['status']=='open' and first['address']==BSC and price*10_000<first['amount_micro']<price*10_000+1_000_000
    assert first['trust_link'].startswith('https://link.trustwallet.com/send?asset=c20000714_t0x55d398326f99059fF775485246999027B3197955&address='+BSC)
    assert payments.create_invoice(alice,a,'bsc','USDT')['id']==first['id']  # same method: same invoice
    other=payments.create_invoice(bob,b,'bsc','USDT')
    assert other['amount_micro']!=first['amount_micro']
    tron=payments.create_invoice(alice,a,'tron','USDT')
    assert tron['id']!=first['id'] and payments.invoice(alice,a)['network']=='tron'
    with store.db() as db:assert db.execute('SELECT status FROM payment_invoices WHERE id=?',(first['id'],)).fetchone()['status']=='replaced'
    with pytest.raises(PaymentConflict):payments.create_invoice(bob,a,'bsc','USDT')  # not bob's order
    Billing(store).cancel(alice,a)
    with pytest.raises(PaymentConflict):payments.create_invoice(alice,a,'bsc','USDT')


def test_an_exact_transfer_pays_the_order_once_and_others_stay_unmatched(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice')
    invoice=payments.create_invoice(alice,a,'tron','USDT');now=time.time()
    assert payments.record_transfer('tron','USDT','tron:wrong',  'Tsender',TRON,invoice['amount_micro']+1000,now) is None
    assert payments.record_transfer('bsc','USDT','bsc:0xabc:0', '0xsender',BSC,invoice['amount_micro'],now) is None  # other network
    paid=payments.record_transfer('tron','USDT','tron:good','Tsender',TRON,invoice['amount_micro'],now)
    assert paid['status']=='paid' and payments.invoice(alice,a)['tx_ref']=='tron:good'
    assert payments.invoice(alice,a)['explorer_url']=='https://tronscan.org/#/transaction/good'
    assert payments.record_transfer('tron','USDT','tron:good','Tsender',TRON,invoice['amount_micro'],now) is None  # replay
    statuses={t['tx_ref']:t['status'] for t in payments.transfers()}
    assert statuses=={'tron:wrong':'unmatched','bsc:0xabc:0':'unmatched','tron:good':'matched'}
    with pytest.raises(PaymentConflict):payments.create_invoice(alice,a,'bsc','USDT')


def test_late_payments_match_within_a_day_but_not_for_cancelled_orders(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice');bob,b,_=order(store,'bob')
    start=time.time()-3*3600
    late=payments.create_invoice(alice,a,'bsc','USDC',now=start)
    gone=payments.create_invoice(bob,b,'bsc','USDC',now=start)
    payments.expire()
    assert payments.invoice(alice,a)['status']=='expired'
    Billing(store).cancel(bob,b);payments.expire()
    assert payments.record_transfer('bsc','USDC','bsc:0x1:0','0xs',BSC,late['amount_micro'],time.time())['status']=='paid'
    assert payments.record_transfer('bsc','USDC','bsc:0x2:0','0xs',BSC,gone['amount_micro'],time.time()) is None
    # A payment more than a day after the invoice expired is left for the admin to resolve by hand.
    carol=store.create_user('carol',PASSWORD,'c@example.com')
    q=Billing(store).quote(carol,10000,1,product='signals')
    c=Billing(store).order(carol,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product='signals')['id']
    old=payments.create_invoice(carol,c,'bsc','USDT',now=start-3*86400)
    assert payments.record_transfer('bsc','USDT','bsc:0x4:0','0xs',BSC,old['amount_micro'],time.time()) is None


def test_paid_signals_order_is_queued_for_signing_when_auto_approval_is_on(store):
    configure(store,auto=True);payments=Payments(store)
    alice,a,_=order(store,'alice','signals');bob,b,_=order(store,'bob','autotrade')
    signals=payments.create_invoice(alice,a,'tron','USDT');auto=payments.create_invoice(bob,b,'tron','USDT')
    payments.record_transfer('tron','USDT','tron:s','T',TRON,signals['amount_micro'],time.time())
    payments.record_transfer('tron','USDT','tron:a','T',TRON,auto['amount_micro'],time.time())
    with store.db() as db:
        jobs={r['order_id']:r for r in db.execute('SELECT order_id,payment_ref,state,requested_by FROM license_approvals').fetchall()}
    assert jobs[a]['payment_ref']=='tron:s' and jobs[a]['state']=='queued' and jobs[a]['requested_by']==uid(store,'manager')
    assert b not in jobs  # automated trading still needs the admin to verify the exchange account


class FakeChain:
    def __init__(self):self.calls=[];self.block=1000;self.logs=[];self.trc20=[]
    def __call__(self,url,payload=None,headers=None):
        self.calls.append((url,payload))
        if payload is None:return {'data':self.trc20}
        if payload['method']=='eth_blockNumber':return {'result':hex(self.block)}
        params=payload['params'][0]
        start,end=int(params['fromBlock'],16),int(params['toBlock'],16)
        assert params['topics'][2]=='0x'+'0'*24+BSC.lower()[2:]
        return {'result':[l for l in self.logs if start<=l['block']<=end and l['address'].lower()==params['address'].lower()]}


def log(block,amount_wei,tx,contract=TOKENS[('bsc','USDT')]['contract']):
    return dict(block=block,address=contract,data=hex(amount_wei),transactionHash=tx,logIndex='0x1',
                topics=['0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef','0x'+'0'*24+'1'*40,'0x'+'0'*24+BSC.lower()[2:]])


def test_watcher_reads_confirmed_bsc_logs_and_trc20_transfers(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice');bob,b,_=order(store,'bob')
    bsc=payments.create_invoice(alice,a,'bsc','USDT');tron=payments.create_invoice(bob,b,'tron','USDT')
    chain=FakeChain();watcher=Watcher(store,chain)
    watcher.once()  # scans up to block 985 (tip 1000 minus 15 confirmations)
    chain.logs=[log(990,bsc['amount_micro']*10**12,'0xaaa'),log(995,bsc['amount_micro']*10**12+1,'0xbbb')]
    chain.block=1004;watcher.once()   # confirmed tip 989: the transfer in block 990 is not final yet
    assert payments.invoice(alice,a)['status']=='open'
    chain.block=1020;watcher.once()
    assert payments.invoice(alice,a)['status']=='paid' and payments.invoice(alice,a)['tx_ref']=='bsc:0xaaa:1'
    assert {t['tx_ref']:t['status'] for t in payments.transfers()}['bsc:0xbbb:1']=='unmatched'  # not an exact amount
    chain.trc20=[dict(transaction_id='t1',block_timestamp=int(time.time()*1000),to=TRON,**{'from':'Tsender'},value=str(tron['amount_micro']),
                      token_info=dict(address=TOKENS[('tron','USDT')]['contract'],decimals=6)),
                 dict(transaction_id='t2',block_timestamp=int(time.time()*1000),to='Tsomeoneelse',**{'from':'Tsender'},value='1',
                      token_info=dict(address=TOKENS[('tron','USDT')]['contract'],decimals=6))]
    watcher.once()
    assert payments.invoice(bob,b)['status']=='paid' and payments.invoice(bob,b)['tx_ref']=='tron:t1'
    assert any('only_confirmed=true' in url and 'only_to=true' in url for url,payload in chain.calls if payload is None)
    seen=Payments(store).admin_settings()
    assert seen['checked']['tron'] and seen['checked']['bsc'] and seen['watcher_seen']


def test_payment_api_for_customers_and_admins(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        def login(name):
            r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD))
            return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}
        alice,a,_=order(store,'alice')
        h=login('alice')
        assert client.get('/api/me/payment-methods').json()['methods']==[]
        assert client.post(f'/api/me/license/orders/{a}/invoice',headers=h,json=dict(network='tron',token='USDT')).status_code==409
        assert client.put('/api/admin/payments',headers=h,json=dict(tron_address=TRON)).status_code==403
        admin=login('manager')
        assert client.put('/api/admin/payments',headers=admin,json=dict(tron_address='nope')).status_code==422
        saved=client.put('/api/admin/payments',headers=admin,json=dict(tron_address=TRON,bsc_address=BSC))
        assert saved.status_code==200 and len(saved.json()['methods'])==3
        h=login('alice')
        assert client.post(f'/api/me/license/orders/{a}/invoice',json=dict(network='tron',token='USDT')).status_code==403  # CSRF
        assert client.post(f'/api/me/license/orders/{a}/invoice',headers=h,json=dict(network='tron',token='USDC')).status_code==422
        made=client.post(f'/api/me/license/orders/{a}/invoice',headers=h,json=dict(network='tron',token='USDT'))
        assert made.status_code==200 and made.json()['address']==TRON
        assert client.get(f'/api/me/license/orders/{a}/invoice').json()['id']==made.json()['id']
        h=login('bob')
        assert client.get(f'/api/me/license/orders/{a}/invoice').status_code==404
        admin=login('manager')
        orders=client.get('/api/admin/orders').json()['items']
        assert next(o for o in orders if o['id']==a)['payment']['amount']==made.json()['amount']
        assert client.get('/api/admin/payments').json()['settings']['tron_address']==TRON
