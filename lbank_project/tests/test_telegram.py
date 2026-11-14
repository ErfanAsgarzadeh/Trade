"""Telegram: one-time linking, signals for subscribers only, account notices, blocked bots and admin control."""
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_telegram
from portal_billing import Billing
from portal_server import create_app
from portal_store import PortalStore
from portal_telegram import Telegram, TelegramError, Worker
from pricing_helpers import enable_test_prices

ORIGIN='https://avina.example';PASSWORD='disposable-test-password'
TOKEN='123456789:'+'A'*35


class FakeBot:
    """Stands in for the Telegram Bot API."""
    def __init__(self):self.updates=[];self.sent=[];self.blocked=set();self.calls=[]
    def __call__(self,token,method,params=None,timeout=15):
        self.calls.append((method,params));assert token==TOKEN
        if method=='getMe':return {'is_bot':True,'username':'AvinaTestBot'}
        if method=='deleteWebhook':return True
        if method=='getUpdates':
            out=[u for u in self.updates if u['update_id']>=int(params['offset'])];return out
        if method=='sendMessage':
            if params['chat_id'] in self.blocked:raise TelegramError('Forbidden: bot was blocked by the user',403)
            self.sent.append((params['chat_id'],params['text']));return {'message_id':len(self.sent)}
        raise AssertionError(method)
    def say(self,chat,text,lang='fa'):
        self.updates.append({'update_id':len(self.updates)+1,'message':{'chat':{'id':chat,'type':'private'},
                             'from':{'id':chat,'username':'u%d'%chat,'language_code':lang},'text':text}})


@pytest.fixture
def setup(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    admin=store.create_user('manager',PASSWORD,'m@example.com');store.set_admin('manager')
    alice=store.create_user('alice',PASSWORD,'a@example.com');bob=store.create_user('bob',PASSWORD,'b@example.com')
    bot=FakeBot();Telegram(store,bot).configure(admin,TOKEN)
    yield store,bot,admin,alice,bob
    store.close()


def code(url):return url.split('start=')[1]


def test_token_is_checked_with_telegram_and_stored_encrypted(setup):
    store,bot,admin,alice,_=setup
    telegram=Telegram(store,bot)
    assert telegram.status()['bot_username']=='AvinaTestBot' and telegram.token()==TOKEN
    with store.db() as db:assert TOKEN not in db.execute("SELECT value FROM site_settings WHERE name='telegram.token'").fetchone()['value']
    with pytest.raises(ValueError):telegram.configure(admin,'not-a-token')
    with pytest.raises(PermissionError):telegram.configure(alice,TOKEN)
    telegram.configure(admin,'');assert not telegram.status()['configured'] and telegram.token()==''


def test_linking_uses_a_one_time_code_and_stop_unlinks(setup):
    store,bot,admin,alice,bob=setup
    telegram=Telegram(store,bot);worker=Worker(store,lambda:{'status':'not_configured'},ORIGIN,bot,0)
    link=telegram.link_code(alice,'fa')
    assert link['url'].startswith('https://t.me/AvinaTestBot?start=')
    bot.say(111,'/start '+code(link['url']));bot.say(222,'/start '+code(link['url']))  # second use of the same code
    bot.say(333,'hello',lang='en');worker.once()
    assert telegram.account(alice)['linked'] and telegram.account(alice)['telegram_username']=='u111'
    texts=dict(bot.sent)
    assert 'alice' in texts[111] and 'منقضی' in texts[222] and 'Connect Telegram' in texts[333] and ORIGIN+'/en/dashboard/' in texts[333]
    bot.say(111,'/stop');worker.once()
    assert not telegram.account(alice)['linked']
    stale=telegram.link_code(bob)
    with store.db() as db:db.execute('UPDATE telegram_link_codes SET expires=?',(time.time()-1,))
    bot.say(444,'/start '+code(stale['url']));worker.once()
    assert not telegram.account(bob)['linked']


def subscribe(store,user):
    enable_test_prices(store);b=Billing(store);q=b.quote(user,10000,1,product='signals')
    oid=b.order(user,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product='signals')['id']
    import customer_manager,tempfile,pathlib
    d=pathlib.Path(tempfile.mkdtemp());customer_manager.keygen(d/'k',d/'p')
    b.approve(oid,d/'k',payment_ref='tron:'+uuid.uuid4().hex)


def test_signals_go_once_to_linked_subscribers_and_notices_follow_preferences(setup):
    store,bot,admin,alice,bob=setup
    telegram=Telegram(store,bot)
    now=time.time()
    feed={'status':'ready','signals':[]}
    worker=Worker(store,lambda:feed,ORIGIN,bot,0)
    for user,chat in ((alice,111),(bob,222)):
        bot.say(chat,'/start '+code(telegram.link_code(user)['url']))
    worker.once();bot.sent.clear()
    subscribe(store,alice)  # bob has no subscription
    worker.once()
    assert any(chat==111 and 'فعال شد' in text for chat,text in bot.sent)  # license notice
    bot.sent.clear()
    signal=dict(bot='main',symbol='BTC/USDT',side='long',entry=100.5,stop=95,target=None,candle_ts=1,timeframe='1h',
                published_at=now+1,expires_at=now+3600)
    old=dict(signal,candle_ts=0,published_at=now-3*3600)
    feed['signals']=[signal,old]
    worker.once();worker.once()
    assert [chat for chat,_ in bot.sent]==[111]
    assert 'BTC/USDT' in bot.sent[0][1] and 'شاهین' in bot.sent[0][1] and '100.5' in bot.sent[0][1]
    telegram.preferences(alice,signals=False,notices=True)
    feed['signals']=[dict(signal,candle_ts=2)];bot.sent.clear();worker.once()
    assert bot.sent==[]


def test_blocked_bot_unlinks_and_broadcast_reaches_linked_users(setup):
    store,bot,admin,alice,bob=setup
    telegram=Telegram(store,bot);worker=Worker(store,lambda:{'status':'not_configured'},ORIGIN,bot,0)
    for user,chat in ((alice,111),(bob,222)):bot.say(chat,'/start '+code(telegram.link_code(user)['url']))
    worker.once();bot.sent.clear();bot.blocked.add(222)
    assert telegram.broadcast(admin,'سلام از آوینا')=={'recipients':2}
    with pytest.raises(PermissionError):telegram.broadcast(alice,'spam')
    worker.once()
    assert bot.sent==[(111,'سلام از آوینا')] and not telegram.account(bob)['linked'] and telegram.account(alice)['linked']


def test_payment_confirmation_notifies_the_linked_customer(setup):
    store,bot,admin,alice,_=setup
    from portal_payments import Payments
    telegram=Telegram(store,bot);worker=Worker(store,lambda:{'status':'not_configured'},ORIGIN,bot,0)
    bot.say(111,'/start '+code(telegram.link_code(alice,'en')['url']));worker.once();bot.sent.clear()
    enable_test_prices(store);b=Billing(store);q=b.quote(alice,10000,1,product='signals')
    oid=b.order(alice,10000,1,'subscription',str(uuid.uuid4()),q['price_cents'],product='signals')['id']
    Payments(store).save_settings(admin,dict(tron_address='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'))
    invoice=Payments(store).create_invoice(alice,oid,'tron','USDT')
    Payments(store).record_transfer('tron','USDT','tron:x','T','TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',invoice['amount_micro'],time.time())
    worker.once()
    assert len(bot.sent)==1 and bot.sent[0][1].startswith('✅ Your payment of '+invoice['amount']+' USDT is confirmed')


def test_telegram_api_for_customers_and_admins(setup,monkeypatch):
    store,bot,admin,alice,_=setup
    monkeypatch.setattr(portal_telegram,'call',bot)
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        def login(name):
            r=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD))
            return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf']}
        h=login('alice')
        assert client.get('/api/me/telegram').json()=={'available':True,'linked':False,'telegram_username':None,'signals':True,'notices':True}
        assert client.post('/api/me/telegram/link',json={}).status_code==403
        link=client.post('/api/me/telegram/link',headers=h,json={'lang':'en'}).json()
        assert link['url'].startswith('https://t.me/AvinaTestBot?start=') and link['app_url'].startswith('tg://resolve?domain=AvinaTestBot')
        assert client.put('/api/me/telegram',headers=h,json={'signals':False,'notices':True}).status_code==409
        assert client.put('/api/admin/telegram',headers=h,json={'token':TOKEN}).status_code==403
        assert client.get('/api/admin/telegram').status_code==403
        a=login('manager')
        assert client.get('/api/admin/telegram').json()['bot_username']=='AvinaTestBot'
        assert client.put('/api/admin/telegram',headers=a,json={'token':'bad'}).status_code==422
        Telegram(store,bot).configure(admin,'')
        assert client.put('/api/admin/telegram',headers=a,json={'token':TOKEN}).json()['bot_username']=='AvinaTestBot'
        assert client.post('/api/admin/telegram/broadcast',headers=a,json={'text':'hi'}).json()=={'recipients':0}
