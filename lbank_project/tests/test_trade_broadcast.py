"""Read-only broadcasting: scope, caching, authorization and consistent close snapshots."""
import sqlite3
import time
from fastapi.testclient import TestClient
import pytest
import trade_publication as pub
from dashboard_server import create_app
from test_system import cfg, system, setup_position


def data():
    rows=[]
    for bot,kind,n in [('main','open',1),('c3','open',2),('pa','closed',3)]:
        rows.append(pub.record(bot,kind,dict(id=n,symbol='BTC/USDT:USDT',side='long',entry=100,entry_price=100,
            exit=110,exit_price=110,pnl=10,pnl_usd=10,closed=10,closed_at=10)))
    return dict(records=rows,account={'equity_usd':10010,'return_pct':.1,'pnl_usd':10},warnings=[],notice='',
        data_mode='csv-lbank',publishable=True,generated_at=time.time())


@pytest.fixture
def feed(monkeypatch):
    calls=[];clock=[0.]
    def read(engine):calls.append(1);return data()
    monkeypatch.setattr(pub,'paper_snapshot',read)
    monkeypatch.setattr(pub,'candles_for',lambda engine,r:([[1000,1,2,1,2,1]],'Source candles'))
    return pub.BroadcastFeed(lambda:object(),clock=lambda:clock[0]),calls,clock


def test_scope_selection_cache_and_copy(feed):
    f,calls,clock=feed;r=f.get();assert len(r['records'])==2 and r['trade']['status']=='open'
    assert r['poll_after_seconds']>=5 and r['source_ok'];started=r['source_started_at']
    r['records'][0]['symbol']='client mutation'
    r=f.get(trade_id='pa:closed:3',scope='all')
    assert r['trade']['id']=='pa:closed:3' and len(r['records'])==3
    assert r['records'][0]['symbol']=='BTC/USDT:USDT' and r['source_started_at']==started
    assert calls==[1] and f.get(bot_filter='pa')['trade'] is None
    assert f.get(bot_filter='pa',scope='closed')['trade']['bot']=='pa'
    clock[0]=6;f.get();assert calls==[1,1]


def test_failure_discards_prior_values(feed,monkeypatch):
    f,_,clock=feed;assert f.get()['account']['pnl_usd']==10
    def broken(engine):raise RuntimeError('SECRET upstream response')
    monkeypatch.setattr(pub,'paper_snapshot',broken);clock[0]=6;r=f.get()
    assert r['records']==[] and r['trade'] is None and not r['source_ok']
    assert r['account']['pnl_usd'] is None and 'SECRET' not in str(r)


def test_bounded_candle_cache_and_demo_label(feed):
    f,_,_=feed
    for i in range(50):
        s=data();s['records'][0]['id']=f'main:open:{i}';f._snapshots['paper']=(100,s);f.get()
    assert len(f._candles)==32
    s=data();s.update(publishable=False,data_mode='demo');f._snapshots['paper']=(100,s)
    assert not f.get()['source_ok']


def test_auth_validation_and_get_only(system,monkeypatch):
    monkeypatch.setenv('BOT_PIN','test');monkeypatch.setattr(pub,'paper_snapshot',lambda engine:data())
    monkeypatch.setattr(pub,'candles_for',lambda engine,r:([],'Not available'))
    with TestClient(create_app(system)) as client:
        assert client.get('/broadcast').status_code==200
        assert client.get('/api/publication/broadcast').status_code==401
        h={'X-Bot-Pin':'test'}
        for query in ['mode=demo','bot=unknown','scope=profits']:
            assert client.get('/api/publication/broadcast?'+query,headers=h).status_code==422
        r=client.get('/api/publication/broadcast?scope=closed&bot=pa',headers=h)
        assert r.json()['trade']['bot']=='pa' and r.headers['cache-control']=='no-store'
        assert client.post('/api/publication/broadcast',headers=h).status_code==405


def test_same_transaction_prevents_double_count_during_close(system,monkeypatch):
    setup_position(system,state='INITIAL');path=system.db.path;connect=sqlite3.connect;changed=[]
    class Connection:
        def __init__(self,c):object.__setattr__(self,'connection',c)
        def __setattr__(self,k,v):setattr(self.connection,k,v)
        def execute(self,sql,*args):
            cursor=self.connection.execute(sql,*args)
            if sql=='SELECT * FROM positions' and not changed:
                with connect(path) as db:
                    db.execute('DELETE FROM positions')
                    db.execute('INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason) VALUES(?,?,?,?,?,?,?,?)',('BTC/USDT:USDT','long',10,1000,2,100,110,'close'))
                changed.append(1)
            return cursor
        def close(self):self.connection.close()
    monkeypatch.setattr(pub.sqlite3,'connect',lambda *a,**kw:Connection(connect(*a,**kw)))
    positions,trades=pub.read_paper_tables(path,'trade_history');assert len(positions)==1 and trades==[]
    positions,trades=pub.read_paper_tables(path,'trade_history');assert positions==[] and len(trades)==1


def test_leverage_uses_matching_open_position_record(tmp_path):
    path = tmp_path / 'sleeve.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE positions(symbol TEXT, opened REAL);
            CREATE TABLE position_margin(symbol TEXT, opened REAL, isolated_leverage INTEGER);
            CREATE TABLE trades(id INTEGER);
            INSERT INTO positions VALUES ('BTC', 20), ('ETH', 21);
            INSERT INTO position_margin VALUES ('BTC', 20, 3), ('ETH', 19, 5);
            INSERT INTO trades VALUES (1);
        """)
    positions, exits = pub.read_paper_tables(path, 'trades')
    assert {p['symbol']: p['isolated_leverage'] for p in positions} == {'BTC': 3, 'ETH': None}
    assert 'isolated_leverage' not in exits[0]
    assert pub.recorded_leverage(0) is None
    assert pub.recorded_leverage('4') == 4


def test_initial_stop_is_distinct_from_current_and_uses_recorded_risk():
    long_trade = dict(symbol='BTC', side='long', entry=100, qty=2, risk_usd=20, stop=102)
    row = pub.record('c3', 'open', long_trade)
    assert (row['initial_stop'], row['stop']) == (90, 102)

    partial = pub.record('c3', 'open', dict(long_trade, qty=1, risk_usd=10))
    assert partial['initial_stop'] == 90
    row = pub.record('pa', 'open', dict(long_trade, side='short', stop=98))
    assert (row['initial_stop'], row['stop']) == (110, 98)
    main = pub.record('main', 'open', dict(long_trade, entry_price=100, initial_sl=91, active_sl=101))
    assert (main['initial_stop'], main['stop']) == (91, 101)
    assert pub.record('c3', 'closed', dict(long_trade, id=1))['initial_stop'] is None
    assert pub.record('c3', 'open', dict(long_trade, risk_usd=None))['initial_stop'] is None


def test_shared_logo_preserves_exact_bytes_and_requires_pin(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from fastapi import HTTPException, Request

    monkeypatch.setenv('BOT_PIN', 'test')
    monkeypatch.setenv('RISK_DIR', str(tmp_path))
    logo = (Path(__file__).parents[1] / 'frontend/public/portal-assets/avina-mark.png').read_bytes()
    app = create_app()
    download = next(route for route in app.routes if route.path == '/publication/brand-image')
    upload = next(route for route in app.routes if route.path == '/api/publication/brand-image')
    auth = upload.dependant.dependencies[0].call

    def request(body):
        async def receive():
            return {'type': 'http.request', 'body': body}
        return Request({'type': 'http', 'headers': [(b'content-type', b'image/png')]}, receive=receive)

    with pytest.raises(HTTPException) as exc:
        download.endpoint()
    assert exc.value.status_code == 404

    async def verify():
        with pytest.raises(HTTPException) as exc:
            await auth(request(logo), '')
        assert exc.value.status_code == 401
        await auth(request(logo), 'test')
        assert await upload.endpoint(request(logo)) == {'updated': True}
        assert download.endpoint().body == logo
        assert download.endpoint().media_type == 'image/png'

        with pytest.raises(HTTPException) as exc:
            await upload.endpoint(request(b'<svg/>'))
        assert exc.value.status_code == 415
        assert download.endpoint().body == logo

    asyncio.run(verify())
