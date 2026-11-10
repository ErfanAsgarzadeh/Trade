import json
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from exchanges import ExchangeError
from portal_thetruetrade import CustomerReader,NoRedirect
from portal_exchanges import MultiExchangeReader,profile,UnsupportedAccount
from portal_store import PortalStore
from portal_server import create_app
from portal_worker import AccountWorker
from portal_execution import readiness


class Response:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return json.dumps(self.data).encode()


class Opener:
    def __init__(self):self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        assert request.method=='GET'
        assert request.full_url.startswith('https://apiv2.thetruetrade.io/')
        if request.full_url.endswith('/assets'):
            return Response({'summary':{'totalAssets':'10500','availableBalance':'9000'}})
        return Response({'items':[dict(id='private-position-id',symbol='BTCUSDT',side='LONG',size='0.1',status='OPEN',entryPrice='60000')], 'meta':{'total':1}})


def test_customer_reader_fixed_host_signed_gets_and_no_raw_data(monkeypatch):
    monkeypatch.setenv('TTT_BASE_URL','https://evil.test')
    monkeypatch.setenv('TTT_API_KEY','wrong-operator-key')
    opener=Opener()
    result=MultiExchangeReader(ttt_factory=lambda key,secret:CustomerReader(key,secret,opener)).snapshot(
        dict(exchange_id='thetruetrade',market='futures',api_key='customer-key',secret='customer-secret'))
    assert result['balances']==[dict(asset='USDT',free=9000.,locked=None,total=10500.)]
    assert result['positions'][0]['contracts']==.1 and result['positions'][0]['entry_price']==60000
    assert result['positions'][0]['mark_price'] is None
    assert not result['positions_complete']
    assert 'private-position-id' not in str(result) and 'customer-key' not in str(result)
    for req in opener.requests:
        assert req.get_header('X-api-key')=='customer-key'
        uri=req.full_url.removeprefix('https://apiv2.thetruetrade.io')
        assert req.get_header('X-signature')==CustomerReader.sign('customer-secret',req.get_header('X-timestamp'),'GET',uri)
    assert NoRedirect().redirect_request(None,None,None,None,None,None) is None


@pytest.mark.parametrize('method,path,query,body',[
    ('POST','/futures/orders',None,{}),('DELETE','/futures/positions',None,None),
    ('GET','https://evil.test',None,None),('GET','/futures/assets',{'url':'evil'},None),
    ('GET','/futures/positions',None,None)])
def test_customer_reader_forbids_writes_and_unknown_paths(method,path,query,body):
    opener=Opener();reader=CustomerReader('key','secret',opener)
    with pytest.raises(ExchangeError):reader.request(method,path,query,body)
    assert not opener.requests


def test_ttt_account_queue_is_owner_scoped_and_never_enables_trading(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    alice=store.create_user('alice','disposable-test-password')
    bob=store.create_user('bob','disposable-test-password')
    origin='https://portal.test'
    opener=Opener()
    try:
        with TestClient(create_app(store,origin=origin),base_url=origin) as client:
            assert client.get('/api/me/execution-readiness').status_code==401
            auth=client.post('/api/login',headers={'X-Portal-Request':'1'},json={'username':'alice','password':'disposable-test-password'}).json()
            headers={'X-Portal-Request':'1','X-CSRF-Token':auth['csrf']}
            assert client.put('/api/me/connection',headers=headers,json={'exchange_id':'thetruetrade','market':'futures','api_key':'alice-key','secret':'alice-secret'}).status_code==200
            assert client.post('/api/me/connection/refresh',headers=headers).status_code==202
            assert AccountWorker(store,MultiExchangeReader(ttt_factory=lambda k,s:CustomerReader(k,s,opener))).once()
            account=client.get('/api/me/connection').json()
            assert account['account']['status']=='verified_read_only'
            state=client.get('/api/me/execution-readiness').json()
            assert state['checks']['account_read_verified']
            assert not state['trading_enabled'] and state['status']=='license_required'
            assert not store.public_connection(bob)['configured']
            assert all('alice-secret' not in str(value) for value in (account,state))
            assert client.delete('/api/me/connection',headers=headers).status_code==200
            assert not client.get('/api/me/execution-readiness').json()['checks']['account_read_verified']
    finally:store.close()


@pytest.mark.parametrize('age,expected',[(0,True),(299,True),(301,False),(-1,False),(float('nan'),False)])
def test_even_licensed_verified_accounts_cannot_bypass_missing_executor(age,expected):
    connection=dict(configured=True,exchange_id='thetruetrade',market='futures',account=dict(
        status='verified_read_only',checked_at=1000-age,snapshot=dict(exchange_id='thetruetrade',market='futures')))
    state=readiness(connection,dict(product='autotrade',entries_allowed=True),now=1000)
    assert state['checks']['account_read_verified'] is expected
    assert not state['trading_enabled'] and not state['live_execution_supported']
    assert 'PROTECTED_LIVE_EXECUTION_NOT_VALIDATED' in state['blockers']
    assert readiness(connection,dict(product='signals',entries_allowed=False),now=1000)['status']=='signals_only'
    with pytest.raises(UnsupportedAccount):profile('thetruetrade','spot')
