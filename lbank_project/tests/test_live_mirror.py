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
    paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='long', qty=1., stop=90., key='c3|AAVE|first', opened=clock[0])
    step()
    assert m.state['paused'] and 'AAVEUSDT' in m.state['pending_orders']
    (tmp / 'live_command.json').write_text(json.dumps({'resume': True}))
    step()
    assert m.state['paused'] and 'AAVEUSDT' in m.state['pending_orders']
    assert 'AAVEUSDT' not in ex.positions()
    # Operator must reconcile the exchange first, then explicitly clear the
    # uncertainty marker. A dashboard config save alone may never unlock it.
    m.state['pending_orders'].clear();m.save()
    paper.book.clear()  # Do not retry the same failed paper signal.
    (tmp / 'live_command.json').write_text(json.dumps({'resume': True}))
    step()
    assert not m.state['paused']
    ex.open = X.Sim.open.__get__(ex)
    paper.book['AAVE/USDT:USDT'] = dict(bot='c3', side='long', qty=1., stop=90.,
                                       key='c3|AAVE|new', opened=clock[0])
    paper.book['AAVE/USDT:USDT']['opened'] = clock[0]
    step()
    assert 'AAVEUSDT' in ex.positions()
    (tmp / 'live_command.json').write_text(json.dumps({'close_all': True}))
    step()
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



def test_thetruetrade_equity_uses_futures_summary_without_double_count(monkeypatch):
    # Actual API response shape; totalAssets already includes unrealized PnL.
    payload = {
        'summary': {
            'totalAssets': '9.828017869708509526',
            'availableBalance': '1.645366040000000002',
            'positionMarginBalance': '8.182651829708509457',
            'totalUnrealizedPnl': '0.513053230987205807',
        },
        'assets': [{
            'symbol': 'USDT',
            'totalAssets': '9.828017869708509526',
            'availableBalance': '1.645366040000000002',
        }],
    }
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda method, path, **kw: payload)
    def should_not_fetch_positions():
        raise AssertionError('summary.totalAssets must not add position PnL again')
    monkeypatch.setattr(t, '_raw_positions', should_not_fetch_positions)
    assert len(t._list(payload)) == 1
    assert t.equity() == pytest.approx(9.82801786970851)


def test_thetruetrade_equity_fallback_to_modern_asset_rows(monkeypatch):
    payload = {'assets': [{'symbol': 'USDT', 'totalAssets': '9.83'},
                          {'symbol': 'BTC', 'totalAssets': '0.01'}]}
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *args, **kw: payload)
    monkeypatch.setattr(t, '_raw_positions', lambda: (_ for _ in ()).throw(
        AssertionError('modern totalAssets should not fetch positions')))
    assert t.equity() == pytest.approx(9.83)


@pytest.mark.parametrize('payload', [
    {'summary': {'totalAssets': 'NaN'}, 'assets': [{'symbol': 'USDT', 'totalAssets': '9.83'}]},
    {'summary': {'totalAssets': '-1'}},
    {'summary': {'totalAssets': True}},
    {'summary': {'totalAssets': 'not-a-number'}},
    {'assets': []},
    {'assets': [{'symbol': 'BTC', 'totalAssets': '1'}]},
    {'assets': [{'symbol': 'USDT', 'totalAssets': None}]},
    {'assets': [{'symbol': 'USDT', 'totalAssets': 'inf'}]},
    {'assets': {'symbol': 'USDT', 'totalAssets': '9.83'}},
    {'summary': 'bad', 'assets': [{'symbol': 'USDT', 'totalAssets': '9.83'}]},
    {},
    None,
])
def test_thetruetrade_equity_invalid_response_fails_closed(monkeypatch, payload):
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *args, **kw: payload)
    with pytest.raises(X.ExchangeError):
        t.equity()


def test_thetruetrade_zero_futures_equity_is_valid(monkeypatch):
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *args, **kw:
                        {'summary': {'totalAssets': '0'}, 'assets': []})
    assert t.equity() == 0.0



def test_thetruetrade_opened_positions_with_real_response_shape(monkeypatch):
    # TheTrueTrade /futures/positions returns {items, meta}; live statuses are OPENED.
    rows = [
        dict(id='a1', symbol='BTCUSDT', side='SHORT', status='OPENED', isActive=True,
             size='0.00002', entryPrice='80000'),
        dict(id='a2', symbol='ETHUSDT', side='SHORT', status='OPENED', isActive=True,
             size='0.01', entryPrice='2200'),
        dict(id='a3', symbol='ADAUSDT', side='LONG', status='OPENED', isActive=True,
             size='10', entryPrice='0.19'),
        dict(id='a4', symbol='SOLUSDT', side='SHORT', status='OPENED', isActive=True,
             size='0.1', entryPrice='140'),
    ]
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda method, path, query=None: {
        'items': rows, 'meta': {'total': len(rows)}
    })
    positions = t.positions()
    assert len(positions) == 4
    assert positions['BTCUSDT'].side == 'short'
    assert positions['BTCUSDT'].qty == pytest.approx(.00002)
    assert positions['BTCUSDT'].ids == ['a1']
    assert positions['ADAUSDT'].side == 'long'


def test_thetruetrade_aggregates_same_side_positions_and_excludes_closed(monkeypatch):
    rows = [
        {'id': 1, 'symbol': 'BTCUSDT', 'side': 'LONG', 'status': 'OPEN', 'size': '1', 'entryPrice': '100'},
        {'id': 2, 'symbol': 'BTCUSDT', 'side': 'LONG', 'status': 'OPENED', 'size': '3', 'entryPrice': '200', 'isActive': True},
        {'id': 3, 'symbol': 'ETHUSDT', 'side': 'SHORT', 'status': 'CLOSED', 'size': '2', 'entryPrice': '100', 'isActive': False},
    ]
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *a, **k: {'items': rows})
    positions = t.positions()
    assert len(positions) == 1
    assert positions['BTCUSDT'].qty == pytest.approx(4)
    assert positions['BTCUSDT'].entry == pytest.approx(175)
    assert positions['BTCUSDT'].ids == [1, 2]


@pytest.mark.parametrize('payload', [
    None,
    {},
    {'items': {}},
    {'items': [None]},
    {'items': [{'status': 'UNKNOWN', 'isActive': True}]},
    {'items': [{'status': 'OPENED', 'isActive': False}]},
    {'items': [{'status': 'CLOSED', 'isActive': True}]},
    {'items': [{'status': 'OPENED', 'isActive': 'true'}]},
])
def test_thetruetrade_invalid_position_responses_fail_closed(monkeypatch, payload):
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *a, **kw: payload)
    with pytest.raises(X.ExchangeError):
        t.positions()


@pytest.mark.parametrize('mutation', [
    {'size': 'NaN'}, {'size': 'inf'}, {'size': '-2'}, {'size': None},
    {'side': 'BOTH'}, {'side': None}, {'entryPrice': 'nan'},
    {'entryPrice': '-1'}, {'id': None}, {'symbol': ''},
])
def test_thetruetrade_invalid_open_position_values_fail_closed(monkeypatch, mutation):
    row = dict(id=4, symbol='BTCUSDT', side='SHORT', status='OPENED', isActive=True,
               size='0.01', entryPrice='80000')
    row.update(mutation)
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *a, **kw: {'items': [row]})
    with pytest.raises(X.ExchangeError):
        t.positions()


def test_thetruetrade_empty_positions_list_is_valid(monkeypatch):
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *a, **kw: {'items': [], 'meta': {'total': 0}})
    assert t.positions() == {}



def test_thetruetrade_available_balance_uses_free_margin(monkeypatch):
    t = X.TheTrueTrade('key', 'secret')
    payload = {'summary': {'totalAssets': '9.828017869708509526',
                           'availableBalance': '1.645366040000000002',
                           'positionMarginBalance': '8.182651829708509457'},
               'assets': [{'symbol': 'USDT', 'availableBalance': '1.645366040000000002'}]}
    monkeypatch.setattr(t, 'request', lambda *a, **kw: payload)
    assert t.available_balance() == pytest.approx(1.64536604)
    assert t.equity() == pytest.approx(9.82801786970851)


@pytest.mark.parametrize('payload', [
    {}, {'summary': {'totalAssets': '9.83'}},
    {'summary': {'availableBalance': 'NaN'}},
    {'summary': {'availableBalance': None}},
    {'summary': {'availableBalance': '-1'}},
    {'summary': {'availableBalance': 'infinity'}},
    {'summary': {'availableBalance': True}},
    {'assets': []},
    {'assets': [{'symbol': 'USDT'}]},
])
def test_thetruetrade_missing_or_invalid_free_margin_fails(monkeypatch, payload):
    t = X.TheTrueTrade('key', 'secret')
    monkeypatch.setattr(t, 'request', lambda *a, **kw: payload)
    with pytest.raises(X.ExchangeError):
        t.available_balance()


def test_thetruetrade_refuses_unprotected_order_before_post(monkeypatch):
    t = X.TheTrueTrade('key', 'secret')
    sent = []
    monkeypatch.setattr(t, 'request', lambda *args, **kw: sent.append((args, kw)))
    with pytest.raises(X.ExchangeError, match='stop loss'):
        t.open('BTCUSDT', 'long', 0.001, 5, None)
    assert not sent


def test_live_mirror_blocks_unverified_exchange_stop_without_order(env):
    m, sim, paper, step, tmp, clock = env
    step()
    def unverified():
        raise X.ExchangeError('TheTrueTrade stop loss readback unavailable')
    sim.ensure_protected_entries = unverified
    paper.book['BTC/USDT:USDT'] = main_pos(ts=17)
    step()
    assert 'BTCUSDT' not in sim.positions()
    assert 'BTCUSDT' not in m.state['pending_orders']
    assert not [x for x in sim.log if x[0] == 'open']


def test_live_mirror_checks_available_margin_before_order(env):
    m, sim, paper, step, tmp, clock = env
    step()
    sim.available_balance = lambda: 0.01
    paper.book['BTC/USDT:USDT'] = main_pos()
    step()
    assert 'BTCUSDT' not in sim.positions()
    assert 'BTCUSDT' not in m.state['pending_orders']
    assert not [x for x in sim.log if x[0] == 'open']


def test_live_mirror_rejects_invalid_stop_and_pauses(env):
    m, sim, paper, step, tmp, clock = env
    step()
    paper.book['BTC/USDT:USDT'] = main_pos(stop=81000)
    step()
    assert m.state['paused']
    assert 'BTCUSDT' not in sim.positions()
    assert not [x for x in sim.log if x[0] == 'open']


def test_live_mirror_timeout_writes_durable_uncertainty_and_never_retries(env):
    m, sim, paper, step, tmp, clock = env
    step()
    calls = []
    def timeout_after_fill(symbol, side, qty, leverage, stop=None):
        calls.append(symbol)
        X.Sim.open(sim, symbol, side, qty, leverage, stop)
        raise TimeoutError('response lost after fill')
    sim.open = timeout_after_fill
    paper.book['BTC/USDT:USDT'] = main_pos()
    step()
    assert len(calls) == 1
    assert m.state['paused'] and 'BTCUSDT' in m.state['pending_orders']
    assert 'BTCUSDT' in sim.positions()
    # Recreate mirror process from durable state file, do not open again.
    restarted = L.Mirror(sim, paper, m.cfg, now=lambda: clock[0])
    assert restarted.state['paused'] and restarted.state['pending_orders']
    restarted.cycle()
    assert len(calls) == 1
    (tmp / 'live_command.json').write_text(json.dumps({'resume': True}))
    restarted.cycle()
    assert restarted.state['paused'] and len(calls) == 1


def test_live_mirror_fails_closed_if_state_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv('RISK_DIR', str(tmp_path))
    path = tmp_path / 'live_state_live_thetruetrade.json'
    path.write_text('{not valid json')
    sim = X.Sim()
    with pytest.raises(X.ExchangeError, match='Cannot load'):
        L.Mirror(sim, FakePaper(), L.validate({'mode': 'live'}))


def test_live_mirror_missing_post_fill_stop_halts_and_journals(env):
    m, sim, paper, step, tmp, clock = env
    step()
    def open_without_stop(symbol, side, qty, leverage, stop=None):
        X.Sim.open(sim, symbol, side, qty, leverage, None)
    sim.open = open_without_stop
    paper.book['BTC/USDT:USDT'] = main_pos()
    step()
    assert 'BTCUSDT' in sim.positions()
    assert m.state['paused'] and 'BTCUSDT' in m.state['pending_orders']
    assert 'BTCUSDT' not in m.state['managed']


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
