"""Measured order-book slippage: logged for every paper fill, never affects PnL or risk management."""
import json
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import lbank_bot as lb
from dashboard_server import create_app
from test_system import system,cfg
from test_pyramiding import setup
from test_profit_floor import open_position

def book(mid=100.,spread_bps=2.,vwap_edge=0.,fraction=1.):
 """Fake MarketData.book_fill: buys fill `vwap_edge` bps above mid, sells that many below."""
 def fn(symbol,buy,contracts):
  return dict(mid=mid,vwap=mid*(1+(1 if buy else -1)*vwap_edge/1e4),filled_fraction=fraction,spread_bps=spread_bps)
 return fn

def rows(system):
 with system.db.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM fill_quality ORDER BY id')]

def test_entry_and_exit_signs_long_and_short(system):
 system.data.book_fill=book(vwap_edge=5.)
 for side,entry_buy in (('long',True),('short',False)):
  with system.db.connect() as db:db.execute('DELETE FROM positions');db.execute('DELETE FROM fill_quality')
  p=open_position(system,side);system._close(system.db.position(p['symbol']),100.,system.db.position(p['symbol'])['qty'],'stop',1_800_000_100)
  entry,exit_=rows(system)
  assert (entry['kind'],entry['side']) == ('entry','buy' if entry_buy else 'sell') and (exit_['kind'],exit_['side'])==('exit','sell' if entry_buy else 'buy')
  # Every direction pays ~5bps vs mid; reference is the paper price (100) and mid is 100, so both views agree.
  assert entry['slip_ref_bps']==pytest.approx(5.,abs=1e-6) and exit_['slip_ref_bps']==pytest.approx(5.,abs=1e-6) and entry['slip_mid_bps']==pytest.approx(5.,abs=1e-6)

def test_price_improvement_is_negative_slippage(system):
 system.data.book_fill=book(vwap_edge=-3.)   # buys fill 3bps BELOW mid: better than the paper price
 open_position(system);assert rows(system)[0]['slip_ref_bps']==pytest.approx(-3.,abs=1e-6)

def test_measurement_failure_never_blocks_trading_and_is_reported(system):
 def broken(*a):raise RuntimeError('order book unavailable')
 system.data.book_fill=broken;p=open_position(system)
 assert system.db.position(p['symbol'])['state'] in (lb.TRAILING,lb.INITIAL) and rows(system)==[]
 assert 'order book unavailable' in system.db.fill_quality_summary()['last_error']
 system.data.book_fill=book();system._close(system.db.position(p['symbol']),101.,system.db.position(p['symbol'])['qty'],'stop',1_800_000_100)
 assert system.db.fill_quality_summary()['last_error'] is None and len(rows(system))==1

def test_panic_close_makes_no_network_call_and_env_switch_disables(system,monkeypatch):
 calls=[]
 def counting(*a):calls.append(a);return book()(*a)
 system.data.book_fill=counting;open_position(system);before=len(calls);system.close_all()
 assert len(calls)==before and [r['kind'] for r in rows(system)]==['entry']
 monkeypatch.setenv('FILL_QUALITY','off');open_position(system);assert len(calls)==before

def test_pyramid_add_is_measured(system):
 system.data.book_fill=book(vwap_edge=4.);c,p=setup(system)
 bar=pd.Series(dict(close=110.,timestamp=(1_800_014_400-14400)*1000));assert system._pyramid_add(p,'long',bar,c,1_800_014_403)
 assert [r['kind'] for r in rows(system)][-1]=='add' and rows(system)[-1]['side']=='buy'

def test_summary_status_and_demo_mode(system):
 system.data.book_fill=book(vwap_edge=6.,fraction=.5)
 p=open_position(system);q=system.db.position(p['symbol']);system._close(q,100.,q['qty'],'stop',1_800_000_100)
 s=system.db.fill_quality_summary();assert s['total']==2 and s['assumed_bps_per_fill']==2.0
 assert s['entry']['median_bps']==pytest.approx(6.,abs=1e-6) and s['exit']['n']==1 and s['entry']['thin_book_fills']==1
 with TestClient(create_app(system)) as client:
  body=client.get('/api/status',headers={'x-bot-pin':'1234'}).json();assert body['fill_quality']['total']==2
 demo=lb.MarketData();assert demo.mode=='demo' and demo.book_fill('BTC/USDT:USDT',True,1.) is None

class FakeExchange:
 def __init__(self,bids,asks):self.book=dict(bids=bids,asks=asks)
 def fetch_order_book(self,symbol,limit=None):return self.book

def live_data(monkeypatch,bids,asks):
 monkeypatch.setenv('PAPER_DATA_MODE','csv-lbank');data=lb.MarketData();data.market=lambda s:{};data.exchange=FakeExchange(bids,asks);return data

def test_book_walk_vwap_partial_fill_and_bad_books(monkeypatch):
 d=live_data(monkeypatch,[[99.9,5],[99.8,5]],[[100.1,1],[100.2,2],[100.4,10]])
 r=d.book_fill('X',True,3);assert r['mid']==pytest.approx(100.) and r['vwap']==pytest.approx((100.1+2*100.2)/3) and r['filled_fraction']==1.
 assert r['spread_bps']==pytest.approx(20.,abs=.01)
 thin=live_data(monkeypatch,[[99.9,1]],[[100.1,1]]).book_fill('X',False,4);assert thin['filled_fraction']==pytest.approx(.25) and thin['vwap']==pytest.approx(99.9)
 for bids,asks in (([],[[100,1]]),([[101,1]],[[100,1]]),([[float('nan'),1]],[[100,1]]),([[99,0]],[[100,1]])):
  assert live_data(monkeypatch,bids,asks).book_fill('X',True,1) is None
