"""Explicit read-only routes. Adding a venue requires a reviewed profile, not a user URL."""
from copy import deepcopy
from functools import lru_cache
import math

import ccxt
from portal_lbank import LBankAccountReader,FuturesNotValidated


class UnsupportedAccount(Exception):pass


def route(client,params,position_params=None,scope='spot wallet'):
    return dict(client=client,balance_params=params,position_params=position_params,
                balance_scope=scope,positions_complete=False)


PROFILES={
 'lbank':dict(name='LBank',spot=route('lbank',{}),pending=['futures']),
 'binance':dict(name='Binance',spot=route('binance',{'type':'spot'}),
    futures=route('binanceusdm',{'type':'future','subType':'linear'},{'subType':'linear'},'USD-M futures wallet')),
 'bybit':dict(name='Bybit',spot=route('bybit',{'type':'spot'},scope='unified or classic account'),
    futures=route('bybit',{'type':'swap','subType':'linear'},{'type':'swap','subType':'linear','settleCoin':'USDT','paginate':True,'paginationCalls':3},'unified or classic account; USDT linear positions')),
 'okx':dict(name='OKX',spot=route('okx',{'type':'spot'},scope='unified trading account'),
    futures=route('okx',{'type':'swap'},{'instType':'SWAP'},'unified trading account; perpetual positions')),
 'bitget':dict(name='Bitget',spot=route('bitget',{'type':'spot','uta':False}),
    futures=route('bitget',{'type':'swap','productType':'USDT-FUTURES','uta':False},
                  {'productType':'USDT-FUTURES','marginCoin':'USDT','uta':False},'classic USDT futures account')),
 'gate':dict(name='Gate',spot=route('gate',{'type':'spot'}),
    futures=route('gate',{'type':'swap','settle':'usdt'},{'type':'swap','settle':'usdt'},'USDT perpetual wallet')),
 'kucoin':dict(name='KuCoin',spot=route('kucoin',{'type':'spot','uta':False}),
    futures=route('kucoinfutures',{'type':'swap','uta':False},{'type':'swap','uta':False},'classic futures account')),
 'kraken':dict(name='Kraken',spot=route('kraken',{}),
    futures=route('krakenfutures',{}, {},'Kraken Futures collateral accounts')),
 'coinbaseexchange':dict(name='Coinbase Exchange',spot=route('coinbaseexchange',{})),
}


@lru_cache(maxsize=32)
def required_fields(client_id):
    exchange=getattr(ccxt,client_id)()
    fields=[name for name,needed in exchange.requiredCredentials.items() if needed]
    if set(fields)-{'apiKey','secret','password','uid'}:
        raise UnsupportedAccount('Credential scheme not supported by this portal')
    return tuple(fields)


def profile(exchange_id,market,allow_pending=False):
    entry=PROFILES.get(exchange_id)
    if not entry:raise UnsupportedAccount('Exchange not enabled')
    if market not in ('spot','futures'):raise UnsupportedAccount('Market not enabled')
    if market not in entry:
        if allow_pending and market in entry.get('pending',[]):return None
        raise UnsupportedAccount('Market not enabled for this exchange')
    result=deepcopy(entry[market]);client=getattr(ccxt,result['client'])()
    if client.has.get('fetchBalance') is not True:raise UnsupportedAccount('Private balance adapter not available')
    if market=='spot' and client.has.get('spot') is not True:raise UnsupportedAccount('Spot adapter not available')
    if market=='futures' and (client.has.get('swap') is not True or client.has.get('fetchPositions') is not True):
        raise UnsupportedAccount('Private perpetual position adapter not available')
    required_fields(result['client'])
    return result


def validate_connection(exchange_id,market,api_key,secret,passphrase='',uid=''):
    result=profile(exchange_id,market,allow_pending=True)
    fields=required_fields(result['client'] if result else exchange_id)
    credentials=dict(apiKey=api_key,secret=secret,password=passphrase,uid=uid)
    if any(not credentials.get(field) for field in fields):
        raise UnsupportedAccount('Required exchange credential missing')


@lru_cache(maxsize=1)
def _catalog():
    rows=[]
    for exchange_id,entry in PROFILES.items():
        markets=[];fields={}
        for market in ('spot','futures'):
            try:r=profile(exchange_id,market)
            except UnsupportedAccount:continue
            markets.append(market);fields[market]=list(required_fields(r['client']))
        rows.append(dict(id=exchange_id,name=entry['name'],markets=markets,pending_markets=entry.get('pending',[]),
                         required_fields=fields,live_execution_supported=False,validation='adapter_only_not_live_verified'))
    return rows


def catalog():return deepcopy(_catalog())


def number(value):
    if value is None:return None
    result=float(value)
    if not math.isfinite(result):raise ValueError('Non-finite exchange value')
    return result


def normalize_balance(balance):
    if not isinstance(balance,dict):raise ValueError('Invalid balance response')
    rows=[]
    assets=set()
    for key in ('total','free','used'):
        if isinstance(balance.get(key),dict):assets.update(balance[key])
    for asset in sorted(assets):
        values={key:number(balance.get(key,{}).get(asset)) for key in ('total','free','used')}
        if any(v is not None and v!=0 for v in values.values()):
            rows.append(dict(asset=str(asset),total=values['total'],free=values['free'],locked=values['used']))
    if not any(isinstance(balance.get(k),dict) for k in ('total','free','used')):
        raise ValueError('Balance fields absent')
    return rows


def normalize_positions(positions):
    if not isinstance(positions,list):raise ValueError('Invalid positions response')
    rows=[]
    for position in positions:
        contracts=number(position.get('contracts'))
        if contracts is None:raise ValueError('Position size unavailable')
        if contracts==0:continue
        if not position.get('symbol'):raise ValueError('Position symbol unavailable')
        rows.append(dict(symbol=position['symbol'],side=position.get('side'),contracts=contracts,
                         contract_size=number(position.get('contractSize')),entry_price=number(position.get('entryPrice')),
                         mark_price=number(position.get('markPrice')),unrealized_pnl=number(position.get('unrealizedPnl')),
                         leverage=number(position.get('leverage')),margin_mode=position.get('marginMode')))
    return rows


class MultiExchangeReader:
    def __init__(self,factory=None):self.factory=factory

    def snapshot(self,connection):
        exchange_id=connection.get('exchange_id','lbank');market=connection['market']
        if exchange_id=='lbank':
            snapshot=LBankAccountReader().snapshot(connection)
            return dict(snapshot,exchange_id='lbank',positions=[],balance_scope='spot wallet',positions_complete=True)
        r=profile(exchange_id,market)
        validate_connection(exchange_id,market,connection['api_key'],connection['secret'],connection.get('passphrase',''),connection.get('uid',''))
        params=dict(apiKey=connection['api_key'],secret=connection['secret'],
                    password=connection.get('passphrase',''),uid=connection.get('uid',''),timeout=10000,enableRateLimit=True,
                    options=dict(defaultType='spot' if market=='spot' else 'swap',defaultSubType='linear'))
        factory=self.factory or (lambda name,p:getattr(ccxt,name)(p))
        exchange=factory(r['client'],params)
        try:
            if exchange.has.get('fetchBalance') is not True:raise UnsupportedAccount('Balance capability changed')
            if market=='futures' and exchange.has.get('fetchPositions') is not True:
                raise UnsupportedAccount('Position capability changed')
            balance=normalize_balance(exchange.fetch_balance(deepcopy(r['balance_params'])))
            positions=[] if market=='spot' else normalize_positions(exchange.fetch_positions(None,deepcopy(r['position_params'])))
            return dict(exchange_id=exchange_id,market=market,balances=balance,positions=positions,
                        balance_scope=r['balance_scope'],positions_complete=(market=='spot'))
        finally:
            close=getattr(exchange,'close',None)
            if close:close()
