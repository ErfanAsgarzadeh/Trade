"""One control panel for both strategies: C3 settings, status, manual close and emergency stop through the dashboard API."""
import json,time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import c3_sleeve as C
from dashboard_server import create_app
from test_system import system, cfg

H={'X-Bot-Pin':'test'}

@pytest.fixture
def panel(system,tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_PIN','test');monkeypatch.setenv('C3_CONFIG',str(tmp_path/'c3_config.json'));monkeypatch.setenv('C3_DB',str(tmp_path/'c3.db'))
    store=C.Store(tmp_path/'c3.db')
    with store.db() as db:
        sym=system.config.read()['symbols'][0]
        db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(sym,'long',100.,2.,95.,100.,time.time(),0,0,10.))
    with TestClient(create_app(system)) as client:yield client,store,sym,tmp_path

def test_requires_pin(panel):
    client,*_=panel
    for path in ('/api/c3/status','/api/c3/config'):assert client.get(path).status_code==401

def test_status_shows_positions_and_shared_equity(panel,system):
    client,store,sym,_=panel;s=client.get('/api/c3/status',headers=H).json()
    assert s['notional_usd']==pytest.approx(200.) and s['open_positions_count']==1 and s['positions'][0]['symbol']==sym and s['coins']==10 and s['in_bot'] is True
    px=system.data.price(sym,cached=True);assert s['unrealized_pnl_usd']==pytest.approx((px-100.)*2.)
    assert s['equity_usd']==pytest.approx(system.paper_equity()+s['unrealized_pnl_usd'],rel=1e-3)

def test_config_edit_validation_and_etag(panel):
    client,store,sym,tmp=panel;r=client.get('/api/c3/config',headers=H);c=r.json();assert c['risk_per_trade_pct']==.002
    c.update(enabled=False,risk_per_trade_pct=.003,confirm_bars=0)
    ok=client.put('/api/c3/config',headers={**H,'If-Match':r.headers['ETag']},json=c);assert ok.status_code==200
    assert json.loads((tmp/'c3_config.json').read_text())['risk_per_trade_pct']==.003 and C.load(tmp/'c3_config.json')['enabled'] is False
    assert client.put('/api/c3/config',headers={**H,'If-Match':r.headers['ETag']},json=c).status_code==409          # stale revision
    live={**c,'dry_run_mode':False};assert client.put('/api/c3/config',headers=H,json=live).status_code==422       # paper-only
    assert client.put('/api/c3/config',headers=H,json={**c,'risk_per_trade_pct':.5}).status_code==422             # out of range
    assert json.loads((tmp/'c3_config.json').read_text())['dry_run_mode'] is True

def test_manual_close_and_emergency_stop(panel,system):
    client,store,sym,tmp=panel
    assert client.post('/api/c3/close',headers=H,json={'symbol':'NOPE'}).status_code==404
    assert client.post('/api/c3/close',headers=H,json={'symbol':sym}).status_code==200 and not store.positions()
    with store.db() as db:assert db.execute('SELECT reason FROM trades').fetchone()[0]=='manual'
    with store.db() as db:db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(sym,'short',100.,1.,105.,100.,time.time(),0,0,5.))
    res=client.post('/api/positions/close-all',headers=H,json={'disable_auto_trade':True}).json()
    assert not store.positions() and res['c3'][0]['result']=='closed' and res['errors']==[]
    assert C.load(tmp/'c3_config.json')['enabled'] is False                                                          # entries stopped too

def test_loop_applies_dashboard_edits_without_restart(tmp_path):
    cfgp=tmp_path/'c.json';cfgp.write_text(json.dumps(C.validate({**json.loads((Path(__file__).parents[1]/'c3_config.json').read_text())})))
    sl=C.Sleeve(C.load(cfgp),C.Store(tmp_path/'d.db'),None);sl.scan=lambda now:True;sl.watchdog=lambda now=None:None
    C.write_config(cfgp,{**sl.c,'risk_per_trade_pct':.004});C.loop(sl,cfgp,once=True);assert sl.c['risk_per_trade_pct']==.004
    cfgp.write_text('{broken');C.loop(sl,cfgp,once=True);assert sl.c['risk_per_trade_pct']==.004                      # bad file keeps old settings

def test_page_has_split_views_and_one_position_table():
    from dashboard_server import HTML
    for v in ('all','bot','c3'):assert f'data-view="{v}"' in HTML
    assert HTML.count('id="positions"')==1 and 'id="c3_rows"' not in HTML and "/api/c3/close" in HTML
