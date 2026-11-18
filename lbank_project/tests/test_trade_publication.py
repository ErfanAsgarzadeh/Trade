"""Publication must preserve provenance, losses and unknowns without trading or mutating stores."""
import csv
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import c3_sleeve
import pa_sleeve
import trade_publication as pub
from dashboard_server import create_app
from test_system import system, cfg, setup_position


@pytest.fixture
def publication(system, tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_PIN', 'test')
    config = system.config.read()
    config['portfolio_risk']['shared_c3_account'] = True
    system.config.write(config)
    for key, mod in [('c3', c3_sleeve), ('pa', pa_sleeve)]:
        config = json.loads((Path(mod.__file__).parent / (key+'_config.json')).read_text())
        Path(os.environ[key.upper()+'_CONFIG']).write_text(json.dumps(config))
        mod.Store(Path(os.environ[key.upper()+'_DB']))
    with system.db.connect() as db:
        for entry, exit_, pnl in [(100,110,19), (100,90,-21)]:
            db.execute('INSERT INTO trade_history(symbol,side,pnl_usd,closed_at,qty,entry_price,exit_price,reason,dry_run) VALUES(?,?,?,?,?,?,?,?,?)',
                       ('BTC/USDT:USDT','long',pnl,time.time()-50000,2,entry,exit_,'partial',1))
    with TestClient(create_app(system)) as client:
        yield client, system


def test_auth_and_mode_validation(publication):
    client, _ = publication
    assert client.get('/api/publication/trades').status_code == 401
    assert client.get('/api/publication/trade?trade_id=main:closed:1').status_code == 401
    assert client.get('/api/publication/trades?mode=invalid', headers={'X-Bot-Pin':'test'}).status_code == 422
    assert client.get('/publication/assets/.env').status_code == 404
    assert client.get('/publication').status_code == 200
    assert client.get('/publication/assets/avina-mark.png').status_code == 200


def test_all_exits_including_losses_and_correct_percent(publication):
    client, engine = publication
    before = read_db_bytes(engine)
    r = client.get('/api/publication/trades',headers={'X-Bot-Pin':'test'}).json()
    assert len(r['records']) == 2
    assert {round(x['price_move_pct']) for x in r['records']} == {10,-10}
    assert r['account']['pnl_usd'] == -2
    assert r['account']['return_pct'] == pytest.approx(-.02)
    assert r['publishable'] is False  # fixture and demo data never become promotional evidence
    assert all(x['opened_at'] is None for x in r['records'])
    d = client.get('/api/publication/trade?trade_id=main:closed:1',headers={'X-Bot-Pin':'test'}).json()
    assert d['candles'] == [] and d['trade']['pnl_usd'] == 19
    assert read_db_bytes(engine) == before


def read_db_bytes(engine):
    return [(p, p.read_bytes()) for p in [engine.db.path, Path(os.environ['C3_DB']), Path(os.environ['PA_DB'])]]


def test_missing_sleeve_withholds_account_without_creating_db(publication):
    _, engine = publication
    path=Path(os.environ['PA_DB']);path.unlink()
    r=pub.paper_snapshot(engine)
    assert not path.exists()
    assert r['account']['equity_usd'] is None
    assert len(r['records']) == 2 and r['warnings']


def test_open_price_failure_and_pending_do_not_fabricate_profit(publication):
    _, engine=publication
    pos=setup_position(engine, state='INITIAL')
    engine.data.fail.add(pos['symbol'])
    r=pub.paper_snapshot(engine)
    assert r['account']['equity_usd'] is None
    opened=[x for x in r['records'] if x['status']=='open']
    assert len(opened)==1 and opened[0]['price_move_pct'] is None
    with engine.db.connect() as db:
        db.execute("UPDATE positions SET state='PENDING_BREAKOUT'")
    from lbank_bot import PENDING
    with engine.db.connect() as db: db.execute('UPDATE positions SET state=?',(PENDING,))
    assert not [x for x in pub.paper_snapshot(engine)['records'] if x['status']=='open']


def test_only_closed_valid_candles_and_explicit_stale_label(publication,tmp_path):
    _, engine=publication
    engine.data.mode='csv-lbank';engine.data.ohlcv_dir=tmp_path
    end=2000000000
    r=pub.record('c3','closed',dict(id=1,symbol='BTC/USDT:USDT',side='long',entry=100,exit=110,closed=end,pnl=9))
    rows=[[int((end-50000)*1000),100,111,90,110,20], [end*1000,100,111,90,110,20]]
    with (tmp_path/'BTC_USDT_USDT_4h.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['timestamp','open','high','low','close','volume']);writer.writerows(rows)
    bars,note=pub.candles_for(engine,r)
    assert len(bars)==1 and 'STALE' in note
    assert pub.candles_for(engine,{**r,'mode':'real'})[0]==[]
    assert pub.price_move(100,90,'short') == pytest.approx(10)
    assert pub.price_move(0,90,'short') is None


def test_real_never_uses_paper_or_dry_results(monkeypatch,tmp_path):
    monkeypatch.setenv('RISK_DIR',str(tmp_path))
    (tmp_path/'live_config.json').write_text(json.dumps({'mode':'dry','exchange':'thetruetrade'}))
    r=pub.real_snapshot()
    assert r['records']==[] and not r['publishable']
    assert r['account']['return_pct'] is None


def test_real_uses_only_reader_and_keeps_missing_pnl_unknown(monkeypatch,tmp_path):
    import portal_thetruetrade
    from exchanges import LivePosition
    monkeypatch.setenv('RISK_DIR',str(tmp_path))
    (tmp_path/'live_config.json').write_text(json.dumps({'mode':'live','exchange':'thetruetrade'}))
    class Reader:
        def __init__(self,*args):pass
        def positions(self):return {'BTCUSDT':LivePosition('BTCUSDT','long',2,None)}
        def equity(self):return 1234
    monkeypatch.setattr(portal_thetruetrade,'CustomerReader',Reader)
    r=pub.real_snapshot()
    assert r['publishable'] and r['account']['equity_usd']==1234
    assert r['records'][0]['entry'] is None and r['records'][0]['pnl_usd'] is None
    assert r['account']['pnl_usd'] is None


def test_official_receipt_and_checksum(publication,tmp_path,monkeypatch):
    import lbank_official_candles as official
    _,engine=publication
    engine.data.mode='csv-lbank';engine.data.ohlcv_dir=tmp_path
    monkeypatch.setenv('LBANK_OFFICIAL_CANDLES','1')
    now=int(time.time())//14400*14400
    bars=[[(now-(1000-i)*14400)*1000,100,111,90,110,20] for i in range(1000)]
    official.publish(tmp_path,'BTC/USDT:USDT',bars,now)
    r=pub.record('c3','closed',dict(id=1,symbol='BTC/USDT:USDT',side='long',entry=100,exit=110,closed=now,pnl=9))
    result,note=pub.candles_for(engine,r)
    assert len(result)==36
    path,_=official.paths(tmp_path,'BTC/USDT:USDT')
    path.write_text(path.read_text().replace('111','112'))
    assert pub.candles_for(engine,r)[0]==[]


def test_futures_units_fees_and_account_equity(publication):
    _,engine=publication
    p=setup_position(engine,state='INITIAL')
    with engine.db.connect() as db:db.execute('UPDATE positions SET contract_size=2')
    engine.data.prices[p['symbol']]=110
    result=pub.paper_snapshot(engine)
    position=next(r for r in result['records'] if r['status']=='open')
    expected=40-(100+110)*4*.0012/2
    assert position['pnl_usd']==pytest.approx(expected)
    assert position['price_move_pct']==pytest.approx(10)
    assert result['account']['equity_usd']==pytest.approx(10000-2+expected)
