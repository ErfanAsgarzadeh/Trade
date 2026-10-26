"""F risk manager connection to the bots (risk_gate.py): neutral while OFF, applied only when ON and fresh."""
import json, time
import pytest
from fastapi.testclient import TestClient
import risk_gate as G
import lbank_bot as lb
import c3_sleeve as C
from pathlib import Path
from dashboard_server import create_app
from test_system import system, cfg, setup_position

H = {'X-Bot-Pin': 'test'}


@pytest.fixture(autouse=True)
def gate_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('RISK_DIR', str(tmp_path / 'rt'));G._cache.clear();return tmp_path / 'rt'


def decision(folder, ai=1., brake=1., mult=None, age=0.):
    folder.mkdir(parents=True, exist_ok=True)
    m = mult if mult is not None else 1.41 * ai * brake
    d = dict(computed_at=time.time() - age, ai=dict(multiplier=ai), brake=dict(multiplier=brake),
             bots={b: dict(multiplier=m) for b in ('main', 'c3', 'pa')})
    (folder / 'risk_overlay.json').write_text(json.dumps(d));G._cache.clear()


def test_off_by_default_is_neutral(gate_dir):
    decision(gate_dir, ai=0.)
    assert G.read_control()['enabled'] is False and G.multiplier('main') == 1. and G.keep_fraction('c3', 'X|1') == 1.
    assert G.status()['active'] is False


def test_on_uses_fresh_decision_and_falls_back_when_stale(gate_dir):
    G.write_control({'enabled': True});decision(gate_dir, ai=1.4, mult=2.)
    assert G.multiplier('pa') == 2. and not G.status()['active'] and not G.status()['bot_ready']   # old bot build
    G.announce();assert G.status()['active'] and G.status()['bot_ready']
    decision(gate_dir, mult=9.);assert G.multiplier('main') == G.MAX_MULT                     # capped
    decision(gate_dir, mult=2., age=40 * 3600);assert G.multiplier('main') == 1.               # stale -> x1
    (gate_dir / 'risk_overlay.json').write_text('{broken');G._cache.clear();assert G.multiplier('main') == 1.
    with pytest.raises(ValueError):G.write_control({'enabled': 'yes'})


def test_open_cuts_follow_falls_only(gate_dir):
    G.write_control({'enabled': True});decision(gate_dir, ai=1.4)
    G.record('c3', 'A|1');decision(gate_dir, ai=1.);assert G.keep_fraction('c3', 'A|1') == pytest.approx(1 / 1.4)
    G.mark('c3', 'A|1');assert G.keep_fraction('c3', 'A|1') == 1.                              # applied once
    decision(gate_dir, ai=1.4);assert G.keep_fraction('c3', 'A|1') == 1.                         # never increased
    decision(gate_dir, ai=1., brake=.5);assert G.keep_fraction('c3', 'A|1') == pytest.approx(.5)
    decision(gate_dir, ai=0.);assert G.keep_fraction('c3', 'A|1') == 0.
    assert G.keep_fraction('c3', 'NEW|2') == 1.                                                  # unknown position: recorded, not cut
    G.write_control({'enabled': True, 'open_cuts': False});assert G.keep_fraction('c3', 'A|1') == 1.


class Data:
    def price(self, s, cached=False):return 110.
    def market(self, s):return {}
    def tradable(self, s, q, p):return q > 0
    def precision(self, s, q):return round(q, 6)


def test_mojsavar_reduce_and_f_cut(tmp_path, gate_dir):
    conf = C.validate(json.loads((Path(__file__).parents[1] / 'c3_config.json').read_text()))
    sl = C.Sleeve(conf, C.Store(tmp_path / 'c3.db'), Data())
    with sl.store.db() as db:db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)', ('AAA', 'long', 100., 2., 90., 100., 1., 0, 0, 20.))
    p = sl.store.positions()[0];assert sl.f_cut(p, 110., 5.) is False                         # F off: nothing happens
    G.write_control({'enabled': True});decision(gate_dir, ai=1.4);G.record('c3', 'AAA|1.0')
    decision(gate_dir, ai=.7);assert sl.f_cut(p, 110., 5.) is True
    q = sl.store.positions()[0];assert q['qty'] == pytest.approx(1.) and q['risk_usd'] == pytest.approx(10.)
    with sl.store.db() as db:assert db.execute("SELECT reason,qty FROM trades").fetchone() == ('f_cut', pytest.approx(1.))
    decision(gate_dir, ai=0.);assert sl.f_cut(q, 110., 6.) and not sl.store.positions()             # bad zone: closed


def test_shahin_f_cut_partial_close(system, gate_dir):
    setup_position(system, state=lb.INITIAL);p = system.db.positions()[0]
    assert system._f_cut(p, 105., time.time()) is False
    G.write_control({'enabled': True});decision(gate_dir, ai=1.4);G.record('main', 'BTC/USDT:USDT|0');decision(gate_dir, ai=.7)
    assert system._f_cut(p, 105., time.time()) is True
    q = system.db.positions()[0];assert q['qty'] == pytest.approx(1.)
    with system.db.connect() as db:assert db.execute("SELECT reason FROM trade_history").fetchone()[0] == 'f_cut'


def test_dashboard_control_and_account(system, gate_dir, monkeypatch):
    monkeypatch.setenv('BOT_PIN', 'test');monkeypatch.delenv('LBANK_API_KEY', raising=False);monkeypatch.delenv('LBANK_SECRET_KEY', raising=False)
    with TestClient(create_app(system)) as c:
        assert c.get('/api/risk/control').status_code == 401
        s = c.get('/api/risk/control', headers=H).json();assert s['control']['enabled'] is False and not s['active']
        s = c.put('/api/risk/control', headers=H, json={'enabled': True}).json();assert s['control']['enabled'] is True and not s['active']   # no decision yet
        assert c.put('/api/risk/control', headers=H, json={'enabled': 1}).status_code == 422
        a = c.get('/api/account', headers=H).json();assert a['mode'] == 'paper' and a['live_available'] is False and a['keys']['configured'] is False
        assert c.post('/api/account/test', headers=H).json()['ok'] is False
        assert c.post('/api/account/mode', headers=H, json={'mode': 'live'}).status_code == 409


def test_signature_matches_documented_recipe():
    import hashlib, hmac, lbank_account as P
    s = P.sign({'asset': 'USDT', 'productGroup': 'SwapU', 'api_key': 'k'}, 'sec', '1', 'e' * 30)
    text = 'api_key=k&asset=USDT&echostr=' + 'e' * 30 + '&productGroup=SwapU&signature_method=HmacSHA256&timestamp=1'
    assert s == hmac.new(b'sec', hashlib.md5(text.encode()).hexdigest().upper().encode(), hashlib.sha256).hexdigest()
