"""Stablecoin payments to the owner's wallet: unique amounts, on-chain matching without a hash, admin settings."""
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from portal_billing import Billing, BillingConflict
from portal_payments import Payments, PaymentConflict, Watcher, amount_text, bsc_address, tron_address, TOKENS
from portal_server import create_app
from portal_store import PortalStore
from pricing_helpers import enable_test_prices
from db_targets import TARGETS, fresh_store
from totp_helpers import AUTH, enable_totp, extra

ORIGIN='https://avina.example';PASSWORD='disposable-test-password'
TRON='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'          # a valid TRON address (the USDT contract, used only as a test target)
BSC='0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed'


@pytest.fixture(params=TARGETS)
def store(request,tmp_path):
    store=fresh_store(request.param,tmp_path)
    store.create_user('manager',PASSWORD,'m@example.com');store.set_admin('manager');enable_totp(store,'manager')
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
    """Primary chain data plus an independent second source. By default the second source mirrors the primary one."""
    def __init__(self):
        self.calls=[];self.block=1000;self.logs=[];self.trc20=[];self.stamp=lambda number:int(time.time())
        self.second_down=False;self.second_unaware=set();self.receipts={}
    def receipt(self,tx):
        if self.second_down:raise OSError('second source unreachable')
        if tx in self.second_unaware:return {'result':None}
        if tx in self.receipts:return {'result':self.receipts[tx]}
        mine=[l for l in self.logs if l['transactionHash']==tx]
        if not mine:return {'result':None}
        return {'result':dict(status='0x1',transactionHash=tx,blockNumber=mine[0]['blockNumber'],
                              logs=[dict(address=l['address'],topics=l['topics'],data=l['data'],logIndex=l['logIndex'],blockNumber=l['blockNumber']) for l in mine])}
    def tron_info(self,url):
        if self.second_down:raise OSError('second source unreachable')
        txid=url.split('hash=')[1]
        if txid in self.second_unaware:return {}
        item=next((t for t in self.trc20 if t['transaction_id']==txid),None)
        if not item:return {}
        return dict(confirmed=True,contractRet='SUCCESS',trc20TransferInfo=[dict(contract_address=item['token_info']['address'],to_address=item['to'],amount_str=item['value'])])
    def __call__(self,url,payload=None,headers=None):
        self.calls.append((url,payload))
        if url.startswith('https://bsc-dataseed.bnbchain.org'):
            assert payload['method']=='eth_getTransactionReceipt';return self.receipt(payload['params'][0])
        if url.startswith('https://apilist.tronscanapi.com/api/transaction-info'):return self.tron_info(url)
        if payload is None:return {'data':self.trc20}
        if payload['method']=='eth_blockNumber':return {'result':hex(self.block)}
        if payload['method']=='eth_getBlockByNumber':return {'result':dict(number=payload['params'][0],timestamp=hex(self.stamp(int(payload['params'][0],16))))}
        params=payload['params'][0]
        start,end=int(params['fromBlock'],16),int(params['toBlock'],16)
        assert params['topics'][2]=='0x'+'0'*24+BSC.lower()[2:]
        return {'result':[l for l in self.logs if start<=l['block']<=end and l['address'].lower()==params['address'].lower()]}


def log(block,amount_wei,tx,contract=TOKENS[('bsc','USDT')]['contract']):
    return dict(block=block,blockNumber=hex(block),address=contract,data=hex(amount_wei),transactionHash=tx,logIndex='0x1',
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
            r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD,**extra(name)))
            return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}
        alice,a,_=order(store,'alice')
        h=login('alice')
        assert client.get('/api/me/payment-methods').json()['methods']==[]
        assert client.post(f'/api/me/license/orders/{a}/invoice',headers=h,json=dict(network='tron',token='USDT')).status_code==409
        assert client.put('/api/admin/payments',headers=h,json=dict(tron_address=TRON,totp='123456')).status_code==403
        admin=login('manager')
        assert client.put('/api/admin/payments',headers=admin,json=dict(tron_address='nope',totp=AUTH['manager'].code())).status_code==422
        saved=client.put('/api/admin/payments',headers=admin,json=dict(tron_address=TRON,bsc_address=BSC,totp=AUTH['manager'].code()))
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


def test_watcher_judges_a_late_payment_by_the_block_time_not_when_it_was_seen(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice')
    start=time.time()-30*3600
    invoice=payments.create_invoice(alice,a,'bsc','USDT',now=start)  # expired about 29 hours ago, past the 24 hour late window
    payments.expire()
    chain=FakeChain();chain.stamp=lambda number:int(start+600);chain.block=1000
    watcher=Watcher(store,chain);watcher.once()  # first pass sets the cursor
    chain.logs=[log(990,invoice['amount_micro']*10**12,'0xlate'),log(991,invoice['amount_micro']*10**12,'0xlate2')]
    chain.block=1020;watcher.once()
    assert payments.invoice(alice,a)['status']=='paid' and payments.invoice(alice,a)['tx_ref']=='bsc:0xlate:1'
    assert sum(1 for url,p in chain.calls if p and p['method']=='eth_getBlockByNumber')==2  # one lookup per block
    with store.db() as db:assert db.execute('SELECT block_time FROM payment_transfers WHERE tx_ref=?',('bsc:0xlate:1',)).fetchone()['block_time']==int(start+600)


def test_a_paid_order_cannot_be_cancelled_by_the_customer(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice')
    invoice=payments.create_invoice(alice,a,'tron','USDT')
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username='alice',password=PASSWORD))
        h={'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}
        assert next(o for o in client.get('/api/me/license').json()['orders'] if o['id']==a)['paid'] is False
        payments.record_transfer('tron','USDT','tron:paid','T',TRON,invoice['amount_micro'],time.time())
        assert next(o for o in client.get('/api/me/license').json()['orders'] if o['id']==a)['paid'] is True
        refused=client.post(f'/api/me/license/orders/{a}/cancel',headers=h)
        assert refused.status_code==409 and 'paid' in refused.json()['detail']
        assert client.post('/api/me/license/orders/nope/cancel',headers=h).status_code==404
    with pytest.raises(BillingConflict):Billing(store).cancel(alice,a)
    with store.db() as db:assert db.execute('SELECT status FROM license_orders WHERE id=?',(a,)).fetchone()['status']=='pending'


def test_admin_attaches_an_unmatched_transfer_to_an_order(store):
    configure(store,auto=True);payments=Payments(store);manager=uid(store,'manager')
    alice,a,_=order(store,'alice','signals');bob,b,_=order(store,'bob','signals')
    invoice=payments.create_invoice(alice,a,'bsc','USDT')
    short=invoice['amount_micro']-1_000_000  # the exchange deducted its withdrawal fee
    assert payments.record_transfer('bsc','USDT','bsc:0xfee:1','0xs',BSC,short,time.time()) is None
    assert payments.record_transfer('bsc','USDC','bsc:0xusdc:1','0xs',BSC,short,time.time()) is None
    with pytest.raises(PermissionError):payments.attach_transfer(alice,'bsc:0xfee:1',a)
    with pytest.raises(LookupError):payments.attach_transfer(manager,'bsc:0xnone:1',a)
    with pytest.raises(PaymentConflict):payments.attach_transfer(manager,'bsc:0xusdc:1',a)  # no USDC invoice on this order
    with pytest.raises(PaymentConflict):payments.attach_transfer(manager,'bsc:0xfee:1',b)    # bob has no invoice at all
    result=payments.attach_transfer(manager,'bsc:0xfee:1',a[:8])
    assert result['order_id']==a and payments.invoice(alice,a)['status']=='paid' and payments.invoice(alice,a)['tx_ref']=='bsc:0xfee:1'
    with store.db() as db:
        assert db.execute("SELECT status,invoice_id FROM payment_transfers WHERE tx_ref='bsc:0xfee:1'").fetchone()['invoice_id']==invoice['id']
        assert db.execute("SELECT 1 FROM admin_events WHERE action='payment_attached' AND target=?",(a,)).fetchone()
        assert db.execute("SELECT payment_ref FROM license_approvals WHERE order_id=?",(a,)).fetchone()['payment_ref']=='bsc:0xfee:1'
    with pytest.raises(PaymentConflict):payments.attach_transfer(manager,'bsc:0xfee:1',a)  # already matched
    assert payments.record_transfer('bsc','USDT','bsc:0xfee:2','0xs',BSC,short,time.time()) is None
    with pytest.raises(PaymentConflict):payments.attach_transfer(manager,'bsc:0xfee:2',a)  # order already paid
    Billing(store).cancel(bob,b)
    with pytest.raises(PaymentConflict):payments.attach_transfer(manager,'bsc:0xfee:2',b)  # not pending


def test_attach_route_is_admin_only_and_strict(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice');invoice=payments.create_invoice(alice,a,'tron','USDT')
    payments.record_transfer('tron','USDT','tron:short','T',TRON,invoice['amount_micro']-500_000,time.time())
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        def login(name):
            r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD,**extra(name)))
            return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}
        url='/api/admin/payments/transfers/attach';body=dict(tx_ref='tron:short',order_id=a)
        assert client.post(url,headers=login('alice'),json=body).status_code==403
        h=login('manager')
        assert client.post(url,headers=h,json=dict(body,extra=1)).status_code==422
        assert client.post(url,headers=h,json=dict(body,order_id='zz')).status_code==422
        assert client.post(url,headers=h,json=dict(body,tx_ref='tron:none')).status_code==404
        assert client.post(url,headers=h,json=body).status_code==200
        assert client.post(url,headers=h,json=body).status_code==409


# ---- Second-source confirmation ---------------------------------------------------------------------------------

def bsc_setup(store):
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice');invoice=payments.create_invoice(alice,a,'bsc','USDT')
    chain=FakeChain();watcher=Watcher(store,chain);watcher.once()  # first pass sets the cursor
    return payments,alice,a,invoice,chain,watcher


def test_second_source_confirms_a_bsc_transfer_before_it_is_recorded(store):
    payments,alice,a,invoice,chain,watcher=bsc_setup(store)
    chain.logs=[log(990,invoice['amount_micro']*10**12,'0xaaa')];chain.block=1020;watcher.once()
    assert payments.invoice(alice,a)['status']=='paid'
    assert any(url.startswith('https://bsc-dataseed.bnbchain.org') and p['method']=='eth_getTransactionReceipt' and p['params']==['0xaaa'] for url,p in chain.calls)
    assert payments.admin_settings()['verify_ok'] is True


def test_a_transfer_the_second_source_does_not_confirm_is_retried_until_it_does(store):
    payments,alice,a,invoice,chain,watcher=bsc_setup(store)
    chain.logs=[log(990,invoice['amount_micro']*10**12,'0xaaa')];chain.block=1020
    for refusal in ('unaware','down'):
        chain.second_unaware={'0xaaa'} if refusal=='unaware' else set();chain.second_down=refusal=='down'
        watcher.once()
        assert payments.invoice(alice,a)['status']=='open' and payments.transfers()==[]
    seen=payments.admin_settings()
    assert seen['verify_ok'] is False and seen['verify_failures']==2 and seen['verify_failed_at']
    chain.second_unaware=set();chain.second_down=False
    watcher.once()  # the cursor stayed before the transfer, so it is read again and now confirmed
    assert payments.invoice(alice,a)['status']=='paid' and payments.invoice(alice,a)['tx_ref']=='bsc:0xaaa:1'
    assert payments.admin_settings()['verify_ok'] is True


def test_a_forged_primary_log_is_never_recorded(store):
    payments,alice,a,invoice,chain,watcher=bsc_setup(store)
    good=log(990,invoice['amount_micro']*10**12,'0xforged')
    chain.logs=[good];chain.block=1020
    other='0x'+'0'*24+'2'*40
    forgeries={'reverted':dict(status='0x0'),'other block':dict(blockNumber=hex(991)),'other receiver':dict(topic2=other),
               'smaller amount':dict(data=hex(1)),'other token':dict(address=TOKENS[('bsc','USDC')]['contract']),'no logs':dict(logs=[])}
    for name,change in forgeries.items():
        entry=dict(address=good['address'],topics=list(good['topics']),data=good['data'],logIndex=good['logIndex'],blockNumber=good['blockNumber'])
        if 'topic2' in change:entry['topics'][2]=change['topic2']
        entry.update({k:v for k,v in change.items() if k in entry})
        chain.receipts['0xforged']=dict(status=change.get('status','0x1'),transactionHash='0xforged',blockNumber=change.get('blockNumber',good['blockNumber']),
                                        logs=change.get('logs',[entry]))
        watcher.once()
        assert payments.invoice(alice,a)['status']=='open' and payments.transfers()==[],name
    assert payments.admin_settings()['verify_failures']==len(forgeries)
    # A receipt without a log index, or malformed, is not verification either.
    chain.receipts['0xforged']=dict(status='0x1',blockNumber=good['blockNumber'],logs=[dict(address=good['address'])])
    watcher.once();assert payments.transfers()==[]


def test_tron_transfers_need_a_confirmed_matching_transaction_on_the_second_source(store):
    from portal_payments import tron_info_confirms
    configure(store);payments=Payments(store)
    alice,a,_=order(store,'alice');invoice=payments.create_invoice(alice,a,'tron','USDT')
    chain=FakeChain();watcher=Watcher(store,chain)
    chain.trc20=[dict(transaction_id='t1',block_timestamp=int(time.time()*1000),to=TRON,**{'from':'Tsender'},value=str(invoice['amount_micro']),
                      token_info=dict(address=TOKENS[('tron','USDT')]['contract'],decimals=6))]
    chain.second_unaware={'t1'};watcher.once()
    assert payments.invoice(alice,a)['status']=='open' and payments.transfers()==[] and payments.admin_settings()['verify_ok'] is False
    chain.second_unaware=set();watcher.once()
    assert payments.invoice(alice,a)['status']=='paid' and payments.admin_settings()['verify_ok'] is True
    assert any('/api/transaction-info?hash=t1' in url for url,p in chain.calls)
    contract=TOKENS[('tron','USDT')]['contract']
    good=dict(confirmed=True,contractRet='SUCCESS',trc20TransferInfo=[dict(contract_address=contract,to_address=TRON,amount_str='5000')])
    assert tron_info_confirms(good,contract,TRON,5000)
    bad=[dict(good,confirmed=False),dict(good,contractRet='REVERT'),{k:v for k,v in good.items() if k!='trc20TransferInfo'},
         dict(good,trc20TransferInfo='x'),dict(good,trc20TransferInfo=[]),None,[],{},
         dict(good,trc20TransferInfo=[dict(contract_address='Tother',to_address=TRON,amount_str='5000')]),
         dict(good,trc20TransferInfo=[dict(contract_address=contract,to_address='Tother',amount_str='5000')]),
         dict(good,trc20TransferInfo=[dict(contract_address=contract,to_address=TRON,amount_str='4999')]),
         dict(good,trc20TransferInfo=[dict(contract_address=contract,to_address=TRON,amount_str='five')]),
         dict(good,trc20TransferInfo=[dict(contract_address=contract,to_address=TRON)])]
    for info in bad:assert not tron_info_confirms(info,contract,TRON,5000),info


def test_auto_approval_only_up_to_the_ceiling_and_new_settings_are_validated(store):
    manager=uid(store,'manager');payments=Payments(store)
    saved=payments.save_settings(manager,dict(tron_address=TRON,auto_approve_signals=True))
    assert saved['auto_approve_max_usd']==500 and saved['bsc_rpc_verify']=='https://bsc-dataseed.bnbchain.org' and saved['tron_verify_url']=='https://apilist.tronscanapi.com'
    for bad in (dict(bsc_rpc_verify='http://insecure.example'),dict(tron_verify_url='ftp://x'),dict(auto_approve_max_usd=-1),dict(auto_approve_max_usd='abc'),dict(auto_approve_max_usd=True)):
        with pytest.raises(ValueError):payments.save_settings(manager,dict(tron_address=TRON,**bad))
    alice,a,price=order(store,'alice','signals');dollars=-(-price//100)  # smallest ceiling that covers the order
    payments.save_settings(manager,dict(tron_address=TRON,auto_approve_signals=True,auto_approve_max_usd=dollars-1))  # one dollar under the price
    invoice=payments.create_invoice(alice,a,'tron','USDT')
    payments.record_transfer('tron','USDT','tron:big','T',TRON,invoice['amount_micro'],time.time())
    with store.db() as db:assert db.execute('SELECT COUNT(*) AS n FROM license_approvals').fetchone()['n']==0  # waits for a person
    bob,b,_=order(store,'bob','signals')
    payments.save_settings(manager,dict(tron_address=TRON,auto_approve_signals=True,auto_approve_max_usd=dollars))
    invoice=payments.create_invoice(bob,b,'tron','USDT')
    payments.record_transfer('tron','USDT','tron:ok','T',TRON,invoice['amount_micro'],time.time())
    with store.db() as db:assert db.execute('SELECT order_id FROM license_approvals').fetchone()['order_id']==b


def test_changing_a_receiving_wallet_alerts_every_linked_admin(store):
    from portal_telegram import short
    manager=uid(store,'manager');second=store.create_user('second-admin',PASSWORD,'s@example.com');store.set_admin('second-admin')
    unlinked=store.create_user('third-admin',PASSWORD,'t@example.com');store.set_admin('third-admin')
    with store.db() as db:
        for user,chat in ((manager,901),(second,902),(uid(store,'alice'),903)):
            db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,0,?)',(user,chat,'u','en',time.time()))
    payments=Payments(store)
    payments.save_settings(manager,dict(tron_address=TRON,bsc_address=BSC))
    with store.db() as db:db.execute('DELETE FROM telegram_outbox')
    payments.save_settings(manager,dict(tron_address=TRON,bsc_address=BSC,invoice_minutes=30))  # no wallet change: no alert
    with store.db() as db:assert db.execute('SELECT COUNT(*) AS n FROM telegram_outbox').fetchone()['n']==0
    new='0x'+'ab'*20
    payments.save_settings(manager,dict(tron_address=TRON,bsc_address=new))
    with store.db() as db:rows=db.execute('SELECT chat_id,text FROM telegram_outbox').fetchall()
    assert sorted(r['chat_id'] for r in rows)==[901,902]  # both admins even with notices off; neither the customer nor the unlinked admin
    assert all(short(BSC) in r['text'] and short(new) in r['text'] for r in rows) and short(BSC)==BSC[:6]+'…'+BSC[-4:]
