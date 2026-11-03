"""F risk manager (shadow service) and the dashboard's performance / risk views."""
import json, math, time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
import risk_overlay as RO
import performance as PF
from dashboard_server import create_app
from test_system import system, cfg

H = {'X-Bot-Pin': 'test'}
MODEL = RO.load_model()


def test_shipped_model_is_complete():
    assert len(MODEL['trees']) == 250 and len(MODEL['features']) == len(MODEL['medians']) == 27 and len(MODEL['quantiles']) == 1001
    s = RO.predict(MODEL, {})            # all inputs missing -> training medians, still a finite score
    assert math.isfinite(s) and 0 <= RO.percentile(MODEL, s) <= 1


def test_predict_handles_bad_inputs_like_missing():
    assert RO.predict(MODEL, {'btc_r1': float('nan'), 'fng': None, 'above20': 'x'}) == RO.predict(MODEL, {})


def test_tiny_tree_arithmetic():
    m = dict(features=['a'], medians=[0.], baseline=1., trees=[dict(f=[0, 0, 0], t=[.5, 0, 0], l=[1, 0, 0], r=[2, 0, 0], leaf=[0, 1, 1], v=[0, -1., 2.])])
    assert RO.predict(m, {'a': .2}) == 0. and RO.predict(m, {'a': .9}) == 3. and RO.predict(m, {}) == 0.


def test_multipliers_follow_the_researched_F_rules():
    assert RO.ai_multiplier(.1) == (0., 'bad') and RO.ai_multiplier(.5) == (1., 'normal') and RO.ai_multiplier(.9) == (1.4, 'good')
    assert RO.brake_multiplier(.05) == 1. and RO.brake_multiplier(.11) == pytest.approx(.6) and RO.brake_multiplier(.3) == .2
    assert RO.vol_multiplier([1.] * 5) == (1., None)
    eq = list(np.cumprod(np.r_[1e4, 1 + np.tile([.02, -.02], 10)]));m, v = RO.vol_multiplier(eq)
    assert v == pytest.approx(.02, rel=.01) and m == pytest.approx(.5, rel=.02)


def test_losing_streak_per_bot():
    tr = [dict(bot='pa', pnl=-30.) for _ in range(20)] + [dict(bot='c3', pnl=-30.) for _ in range(19)]
    s = RO.streaks(tr, 1e4, {'main': .01, 'c3': .004, 'pa': .006})
    assert s['pa']['active'] and s['pa']['multiplier'] == .5 and s['pa']['sum_r'] == pytest.approx(-10.)
    assert not s['c3']['active'] and not s['main']['active']          # fewer than 20 trades -> off


class FakeEngine:
    paper_seed = 1e4


class FakeBots:
    def __init__(self, eq, trades=(), pos=()):
        self.eq, self.tr, self.pos, self.engine = eq, list(trades), list(pos), FakeEngine()
    def equity(self):return self.eq
    def closed_trades(self):return self.tr
    def risk_pct(self):return {'main': .01, 'c3': .004, 'pa': .006}
    def positions(self):return self.pos


def test_decide_writes_json_safe_shadow_decision(tmp_path):
    st = RO.State(tmp_path);now = time.time()
    d = RO.decide(MODEL, FakeBots(1e4, pos=[dict(bot='main', side='long', r=1.5)]), st, now, fetch=False)
    json.dumps(d, allow_nan=False)                                      # no NaN anywhere
    assert d['mode'] == 'shadow' and d['features']['open_long'] == 1 and d['features']['open_R'] == 1.5
    assert d['combined'] == pytest.approx(RO.F['scale'] * d['ai']['multiplier'] * d['vol']['multiplier'] * d['brake']['multiplier'])
    st.append(st.log, d)
    d2 = RO.decide(MODEL, FakeBots(1.1e4), st, now + 86400, fetch=False)   # account +10% -> shadow +10% x yesterday's average multiplier
    assert d2['shadow_equity'] == pytest.approx(1e4 * (1 + .1 * d['avg_multiplier']))


def test_performance_summary():
    now = time.time();t = [dict(bot='main', symbol='BTC', side='long', pnl=100., closed=now - 40 * 86400), dict(bot='c3', symbol='X', side='short', pnl=-50., closed=now - 3 * 86400),
                          dict(bot='pa', symbol='Y', side='long', pnl=25., closed=now - 86400)]
    p = PF.summarize(t, 1e4, [], now)
    assert p['all']['trades'] == 3 and p['all']['total'] == 75. and p['bots']['main']['profit_factor'] is None and p['all']['profit_factor'] == pytest.approx(2.5)
    assert p['all']['pnl_7d'] == -25. and p['realized_curve'][-1]['equity'] == 10075. and p['recent'][0]['bot'] == 'pa'
    assert sum(r['total'] for r in p['monthly'].values()) == 75. and p['drawdown_max'] == pytest.approx(-50 / 10100 * 100)
    json.dumps(p, allow_nan=False)


@pytest.fixture
def panel(system, tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_PIN', 'test');monkeypatch.setenv('RISK_DIR', str(tmp_path))
    with TestClient(create_app(system)) as client:yield client, tmp_path


def test_dashboard_risk_and_performance_views(panel):
    client, tmp = panel
    assert client.get('/api/risk').status_code == 401
    r = client.get('/api/risk', headers=H).json();assert r['available'] is False and 'lbank-risk' in r['hint']
    st = RO.State(tmp);d = RO.decide(MODEL, FakeBots(1e4), st, time.time(), fetch=False);st.write_current(d);st.append(st.log, d)
    r = client.get('/api/risk', headers=H).json()
    assert r['available'] and r['current']['mode'] == 'shadow' and len(r['history']) == 1 and r['stale'] is False
    st.append(st.eqh, dict(t=time.time(), equity=1e4))
    p = client.get('/api/performance', headers=H).json();assert p['seed'] > 0 and len(p['snapshots']) == 1 and set(p['bots']) == {'main', 'c3', 'pa'}


def test_page_has_tabs_and_new_sections():
    from dashboard_server import HTML
    for t in ('overview', 'positions', 'performance', 'risk', 'settings'):assert f'data-tab="{t}"' in HTML and f'data-pane="{t}"' in HTML
    for i in ('eq_chart', 'dd_chart', 'monthly', 'hist_all', 'f_bots', 'f_needle'):assert f'id="{i}"' in HTML
    assert '/api/risk' in HTML and '/api/performance' in HTML
