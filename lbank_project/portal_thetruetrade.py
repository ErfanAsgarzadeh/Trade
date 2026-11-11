"""Customer-scoped TheTrueTrade reads. Fixed host, GET allowlist, no redirects."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from exchanges import TheTrueTrade, ExchangeError

OFFICIAL_BASE = 'https://apiv2.thetruetrade.io'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class CustomerReader(TheTrueTrade):
    def __init__(self,key,secret,opener=None):
        if not isinstance(key,str) or not key.strip() or not isinstance(secret,str) or not secret.strip():
            raise ValueError('Exchange credentials required')
        super().__init__(key=key,secret=secret,base=OFFICIAL_BASE,timeout=10)
        self.opener=opener or urllib.request.build_opener(NoRedirect())

    def request(self,method,path,query=None,body=None,auth=True):
        if (method!='GET' or body is not None or auth is not True
            or path not in ('/futures/assets','/futures/positions')
            or (path=='/futures/assets' and query)
            or (path=='/futures/positions' and query!={'active':'true'})):
            raise ExchangeError('Customer account reader only permits approved GET routes')
        uri=path+('?' + urllib.parse.urlencode(query) if query else '')
        timestamp=str(int(time.time()*1000))
        request=urllib.request.Request(OFFICIAL_BASE+uri,method='GET',headers={
            'Accept':'application/json','User-Agent':'Trade-customer-reader/1',
            'X-API-Key':self.key,'X-Timestamp':timestamp,
            'X-Signature':self.sign(self.secret,timestamp,'GET',uri)})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('Response too large')
            return json.loads(raw)
        except Exception:
            # Never forward credential-bearing URLs, upstream error bodies or IDs.
            raise ExchangeError('TheTrueTrade account read failed') from None


def snapshot(connection,factory=None):
    reader=(factory or CustomerReader)(connection['api_key'],connection['secret'])
    equity=reader.equity()
    available=reader.available_balance()
    positions=reader.positions()
    return dict(exchange_id='thetruetrade',market='futures',
                balances=[dict(asset='USDT',free=available,locked=None,total=equity)],
                positions=[dict(symbol=p.symbol,side=p.side,contracts=p.qty,contract_size=None,
                                entry_price=p.entry,mark_price=None,unrealized_pnl=None,
                                leverage=None,margin_mode=None) for p in positions.values()],
                positions_complete=False,
                balance_scope='TheTrueTrade futures equity (includes floating PnL); free = available margin; locked not reported')
