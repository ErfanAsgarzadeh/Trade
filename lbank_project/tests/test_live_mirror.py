"""Live mirror (paper -> exchange) and exchange adapters, with a simulated exchange and fake paper books."""
import json, time
import pytest
import exchanges as X
import live_mirror as L

MK = {'BTCUSDT': dict(step=.001, tick=.1, min_qty=.001, min_notional=5), 'AAVEUSDT': dict(step=.01, tick=.01, min_qty=.01, min_notional=5),
      '1000SHIBUSDT': dict(step=1, tick=1e-6, min_qty=1, min_notional=5)}
PX = {'BTCUSDT': 80000., 'AAVEUSDT': 100., '1000SHIBUSDT': .005}


class FakePaper:
    def __init__(self, eq=10000.):self.book = {};self.eq = eq
    def positions(self):return {k: dict(v) for k, v in self.book.items()}
    def equity(self):return self.eq


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('RISK_DIR', str(tmp_path));clock = [1_000_000.]
    ex = X.Sim(price_fn=lambda s: PX[s], equity=1000., markets=MK);paper = FakePaper()
    m = L.Mirror(ex, paper, L.validate({'mode': 'live'}), now=lambda: clock[0])
    def step(dt=10):clock[0] += dt;m.cycle()
    return m, ex, paper, step, tmp_path, clock


def main_pos(qty=.05, stop=78000., side='long', ts=1):return dict(bot='main', side=side, qty=qty, stop=stop, key=f'main|BTC/USDT:USDT|{ts}', opened=None)


def test_new_position_is_mirrored_with_proportional_size_and_stop(env):
    m, ex, paper, step, tmp, _ = env
    step()                                                     # mirror running, nothing open
    paper.book['BTC/USDT:USDT'] = main_pos();step()
    pos = ex.positions()['BTCUSDT'];assert pos.side == 'long' and pos.qty == pytest.approx(.005)   # 0.05 x 1000/10000
    assert ex.stops['BTCUSDT'] == 78000. and m.state['managed']['BTCUSDT']['bot'] == 'main'
    assert any(json.loads(l)['kind'] == 'open' for l in (tmp / 'live_log.jsonl').read_text().splitlines())


def test_positions_open_before_start_are_not_copied_but_fresh_sleeve_ones_are(env):
    m, ex, paper, step, _, clock = env
    paper.book['BTC/USDT:USDT'] = main_pos()
    paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='short', qty=10., stop=110., key='c3|AAVE|1', opened=clock[0] - 60)
    step()
    assert 'BTCUSDT' not in ex.positions()                     # main position already open at start: entered late -> skipped
    assert ex.positions()['AAVEUSDT'].qty == pytest.approx(1.) and ex.positions()['AAVEUSDT'].side == 'short'


def test_follows_stop_reduce_add_and_exit(env):
    m, ex, paper, step, _, _ = env
    step();paper.book['BTC/USDT:USDT'] = main_pos(qty=.1);step();assert ex.positions()['BTCUSDT'].qty == pytest.approx(.01)
    paper.book['BTC/USDT:USDT']['stop'] = 79000.;step();assert ex.stops['BTCUSDT'] == 79000.
    paper.book['BTC/USDT:USDT']['qty'] = .05;step();assert ex.positions()['BTCUSDT'].qty == pytest.approx(.005)    # take-profit part
    paper.book['BTC/USDT:USDT']['qty'] = .1;step();assert ex.positions()['BTCUSDT'].qty == pytest.approx(.01)      # pyramid add
    del paper.book['BTC/USDT:USDT'];step();assert 'BTCUSDT' not in ex.positions() and not m.state['managed']


def test_shib_units_and_unmanaged_positions_untouched(env):
    m, ex, paper, step, _, clock = env
    ex.open('BTCUSDT', 'short', .002, 5, None)                 # the user's own position
    paper.book['SHIB/USDT:USDT'] = dict(bot='pa', side='long', qty=20_000_000., stop=4.5e-6, key='pa|SHIB|1', opened=clock[0])
    step()
    p = ex.positions()['1000SHIBUSDT'];assert p.qty == pytest.approx(2000.) and ex.stops['1000SHIBUSDT'] == pytest.approx(4.5e-3)
    paper.book['BTC/USDT:USDT'] = main_pos(ts=9);step()
    assert ex.positions()['BTCUSDT'].side == 'short' and ex.positions()['BTCUSDT'].qty == .002 and m.state['unmanaged'] == ['BTCUSDT']


def test_exchange_side_close_and_minimums_and_caps(env):
    m, ex, paper, step, _, clock = env
    step();paper.book['BTC/USDT:USDT'] = main_pos(qty=.001);step()                 # 0.0001 BTC < step -> skipped
    assert 'BTCUSDT' not in ex.positions()
    m.cfg = L.validate({'mode': 'live', 'max_position_usd': 50.})
    paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='long', qty=100., stop=90., key='c3|AAVE|2', opened=clock[0])
    step();assert ex.positions()['AAVEUSDT'].qty == pytest.approx(.5)              # capped at $50
    ex.close(ex.positions()['AAVEUSDT']);step()                                    # stop hit on the exchange
    assert 'AAVEUSDT' not in m.state['managed'] and 'AAVEUSDT' not in ex.positions()


def test_errors_pause_and_dashboard_commands(env):
    m, ex, paper, step, tmp, clock = env
    step()
    def boom(*a, **k):raise X.ExchangeError('down')
    ex.open = boom
    for i in range(5):
        paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='long', qty=1., stop=90., key=f'c3|AAVE|{i}', opened=clock[0]);step()
    assert m.state['paused']
    (tmp / 'live_command.json').write_text(json.dumps({'resume': True}));step();assert not m.state['paused']
    ex.open = X.Sim.open.__get__(ex);paper.book['AAVE/USDT:USDT']['key'] = 'c3|AAVE|new';paper.book['AAVE/USDT:USDT']['opened'] = clock[0];step()
    assert 'AAVEUSDT' in ex.positions()
    (tmp / 'live_command.json').write_text(json.dumps({'close_all': True}));step()
    assert not ex.positions() and m.state['paused']


def test_mode_off_does_nothing(env):
    m, ex, paper, step, _, clock = env
    m.cfg = L.validate({'mode': 'off'});paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='long', qty=10., stop=90., key='k', opened=clock[0]);step()
    assert not ex.positions()


def test_config_validation(tmp_path, monkeypatch):
    monkeypatch.setenv('RISK_DIR', str(tmp_path))
    assert L.read_config()['mode'] == 'off'
    for bad in ({'mode': 'yes'}, {'exchange': 'lbank'}, {'size_factor': 0}, {'leverage': 50}, {'max_positions': 0}):
        with pytest.raises(ValueError):L.write_config(bad)
    assert L.write_config({'mode': 'dry', 'exchange': 'binance'})['exchange'] == 'binance' and L.read_config()['mode'] == 'dry'


def test_symbol_mapping():
    assert X.bot_to_exchange('BTC/USDT:USDT') == ('BTCUSDT', 1.) and X.bot_to_exchange('SHIB/USDT:USDT') == ('1000SHIBUSDT', 1000.)


def test_thetruetrade_signing_and_requests(monkeypatch):
    import hashlib, hmac
    assert X.TheTrueTrade.sign('sec', '1700', 'get', '/users/profile') == hmac.new(b'sec', b'1700GET/users/profile', hashlib.sha256).hexdigest()
    sent = []
    class R:
        def __init__(self, body):self.body = body
        def read(self):return json.dumps(self.body).encode()
        def __enter__(self):return self
        def __exit__(self, *a):return False
    def fake(req, timeout):
        sent.append(req)
        if req.full_url.endswith('/futures/positions?active=true'):
            return R([{'id': 7, 'symbol': 'BTCUSDT', 'side': 'LONG', 'status': 'OPEN', 'size': '0.01', 'entryPrice': '80000', 'unrealizedPnL': '5'}])
        if req.full_url.endswith('/futures/assets'):return R([{'asset': 'USDT', 'balance': '1000'}])
        return R({'positionId': '7'})
    monkeypatch.setattr(X.urllib.request, 'urlopen', fake)
    t = X.TheTrueTrade('k', 's', 'https://api.test')
    t.open('BTCUSDT', 'long', .01, 5, 78000.)
    body = json.loads(sent[-1].data);assert body == {'symbol': 'BTCUSDT', 'side': 'LONG', 'tradeType': 'MARKET', 'leverage': 5, 'size': '0.01', 'walletType': 'debit', 'stopLoss': '78000'}
    h = {k.lower(): v for k, v in sent[-1].header_items()};assert h['x-api-key'] == 'k' and h['x-signature'] == X.TheTrueTrade.sign('s', h['x-timestamp'], 'POST', '/futures/positions')
    pos = t.positions()['BTCUSDT'];assert pos.qty == .01 and pos.ids == [7] and t.equity() == 1005.
    t.close(pos, .004);assert sent[-1].full_url.endswith('/futures/positions/7/close') and json.loads(sent[-1].data) == {'orderType': 'MARKET', 'size': '0.004'}
    t.set_stop(pos, 79000.);assert sent[-1].get_method() == 'PATCH' and json.loads(sent[-1].data)['stopLoss'] == '79000'
    with pytest.raises(X.ExchangeError):X.TheTrueTrade('', '', 'https://api.test').equity()


def test_binance_adapter_orders():
    calls = []
    class FakeCcxt:
        markets = {}
        def set_leverage(self, l, s):calls.append(('lev', l, s))
        def amount_to_precision(self, s, q):return str(q)
        def price_to_precision(self, s, p):return str(p)
        def create_order(self, s, typ, side, amount=None, price=None, params=None):calls.append((typ, side, amount, params or {}))
        def fetch_open_orders(self, s):return [{'id': '1', 'type': 'stop_market'}]
        def cancel_order(self, i, s):calls.append(('cancel', i))
    b = X.Binance(testnet=False, exchange=FakeCcxt())
    b.open('BTCUSDT', 'long', .01, 5, 78000.)
    assert calls[0] == ('lev', 5, 'BTC/USDT:USDT') and calls[1][:3] == ('market', 'buy', '0.01') and calls[-1][0] == 'STOP_MARKET' and calls[-1][3]['closePosition']
    b.close(X.LivePosition('BTCUSDT', 'long', .01, 80000., ['BTCUSDT']));assert ('market', 'sell', '0.01', {'reduceOnly': True}) in calls


def test_dashboard_live_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard_server import create_app
    import lbank_bot as lb
    from test_system import FakeData
    monkeypatch.setenv('RISK_DIR', str(tmp_path / 'rt'));monkeypatch.setenv('BOT_PIN', 'test-pin-0123456789')
    monkeypatch.delenv('TTT_API_KEY', raising=False)
    cfgstore = lb.ConfigStore(tmp_path / 'config.json')
    import json as _j
    cfgstore.write(_j.loads((__import__('pathlib').Path(__file__).parents[1] / 'config.json').read_text()))
    engine = lb.Engine(cfgstore, lb.Database(tmp_path / 'd.db'), FakeData(), paper_equity=10000)
    H = {'X-Bot-Pin': 'test-pin-0123456789'}
    with TestClient(create_app(engine)) as c:
        assert c.get('/api/live').status_code == 401
        d = c.get('/api/live', headers=H).json();assert d['config']['mode'] == 'off' and d['keys']['thetruetrade'] is False and not d['running']
        assert c.put('/api/live/config', headers=H, json={'mode': 'live'}).status_code == 422          # needs typed confirmation
        assert c.put('/api/live/config', headers=H, json={'mode': 'dry', 'exchange': 'binance', 'size_factor': .5}).json()['mode'] == 'dry'
        assert c.put('/api/live/config', headers=H, json={'mode': 'live', 'confirm': 'LIVE'}).json()['mode'] == 'live'
        assert c.put('/api/live/config', headers=H, json={'leverage': 99}).status_code == 422
        assert c.post('/api/live/close-all', headers=H).json()['queued'] and _j.loads((tmp_path / 'rt' / 'live_command.json').read_text())['close_all']
        assert 'id="live_panel"' in c.get('/').text
