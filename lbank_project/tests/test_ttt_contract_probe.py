import json
import urllib.error
import pytest
from tools import ttt_contract_probe as probe


class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return json.dumps(self.value).encode()


class Opener:
    def __init__(self):self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        assert request.method=='GET' and request.full_url.startswith(probe.BASE+'/')
        if '/assets' in request.full_url:return Response({'summary':{'totalAssets':'PRIVATE_VALUE','availableBalance':10}})
        if '/markets' in request.full_url:return Response([{'symbol':'BTCUSDT','stepSize':.001,'minOrderSize':None}])
        return Response({'items':[dict(id='PRIVATE_ID',symbol='PRIVATE_SYMBOL',status='OPEN',stopLoss=500,slOrderId='PRIVATE_REFERENCE')], 'meta':{'hasNextPage':True}})


def test_probe_only_gets_reports_no_identifiers_and_never_authorizes():
    opener=Opener();result=probe.probe('PRIVATE_KEY','PRIVATE_SECRET',opener)
    assert len(opener.calls)==4
    assert 'PRIVATE' not in json.dumps(result)
    assert not result['live_trading_authorized'] and not result['orders_sent']
    markets=result['checks']['markets']['summary']
    assert markets['BTCUSDT']['stepSize'] and not markets['BTCUSDT']['minOrderSize']
    assert result['checks']['full_positions']['summary']['another_page_reported']
    assert not result['checks']['full_positions']['summary']['stop_execution_verified']
    assert not opener.calls[1].get_header('X-api-key')
    with pytest.raises(ValueError):probe.get('k','s','/futures/orders',None,opener)
    assert probe.NoRedirect().redirect_request(None,None,None,None,None,None) is None


def test_probe_never_echoes_upstream_error_bodies():
    class Broken:
        def open(self,*args,**kwargs):raise ValueError('PRIVATE_ERROR')
    result=probe.probe('k','s',Broken())
    assert 'PRIVATE_ERROR' not in json.dumps(result)
    assert all(v['status']=='failed' for v in result['checks'].values())
