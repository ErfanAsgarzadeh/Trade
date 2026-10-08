from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,pandas as pd,pytest
import c3_sleeve as C,lbank_bot as B
from test_system import system,cfg,setup_position
@pytest.fixture
def shared(system):
 c=system.config.read();c['portfolio_risk']['shared_c3_account']=True;c['risk_and_exit'].update(engaged_capital_pct=.6,default_isolated_leverage=5);system.config.write(c);a=system.shared_paper_account();conf=a.config_reader();conf.update(risk_per_trade_pct=.01,max_notional_pct=1.)
 return system,a,C.Sleeve(conf,a.store,system.data,shared_account=system.shared_paper_account)
def put(a,s='AVAX/USDT:USDT',qty=2):
 with a.store.db() as db:
  db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(s,'long',100.,qty,95.,100.,1.,0,0,qty*5))
  db.execute('INSERT INTO position_margin VALUES(?,?,?)',(s,1.,5))
 return a.store.positions()[0]
def test_equity_no_double_count_and_idempotent_close(shared):
 e,a,sl=shared;p=put(a);e.data.prices[p['symbol']]=110.;expected=e.main_paper_equity()+20.-.0012/2*210*2
 assert e.paper_equity()==pytest.approx(expected) and sl.equity()==pytest.approx(expected)
 sl.close(p,110.,'test',2);assert e.paper_equity()==pytest.approx(expected)
 assert sl.close(p,110.,'test',3)==0
 with a.store.db() as db:assert db.execute('SELECT COUNT(*) FROM trades').fetchone()[0]==1
 assert a.reserved_margin()==0

def test_main_counts_c3_and_pending(shared):
 e,a,sl=shared;put(a,qty=250);p=setup_position(e);eq=e.paper_equity();c=e.config.read();reserved=a.reserved_margin()
 assert e.available_notional(eq,c)==pytest.approx(max(0,eq*.6-reserved)/(1+.6*5*c['risk_and_exit']['lbank_round_trip_fee'])*5)
 assert a.reserved_margin()>=5000+B.position_margin(p)

def test_exhausted_capacity_blocks_c3(shared):
 e,a,sl=shared;put(a,qty=300)
 assert sl.open('UNI/USDT:USDT','long',pd.Series(dict(close=100.,atr=1.,timestamp=0)),2) is None
 assert len(a.store.positions())==1

def test_concurrent_entries_share_margin(shared):
 e,a,sl=shared;b=pd.Series(dict(close=100.,atr=.25,timestamp=0));syms=['AAVE/USDT:USDT','UNI/USDT:USDT','AVAX/USDT:USDT','DOT/USDT:USDT','DOGE/USDT:USDT','TRX/USDT:USDT']
 with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda s:sl.open(s,'long',b,10),syms))
 snap=a.snapshot();assert snap['reserved_margin_usd']<=snap['allowed_margin_usd']+1e-6
 assert len(a.store.positions())>1

def test_missing_prices_fail_closed(shared):
 e,a,sl=shared;p=put(a);e.data.fail.add(p['symbol'])
 with pytest.raises(RuntimeError):e.paper_equity()
 with pytest.raises(RuntimeError):sl.open('UNI/USDT:USDT','long',pd.Series(dict(close=100.,atr=1.,timestamp=0)),2)

def test_dashboard_shared_equity_and_c3_margin(shared,monkeypatch):
 from fastapi.testclient import TestClient
 from dashboard_server import create_app
 e,a,sl=shared;put(a);monkeypatch.setenv('BOT_PIN','test')
 with TestClient(create_app(e)) as api:
  b=api.get('/api/status',headers={'X-Bot-Pin':'test'}).json();c=api.get('/api/c3/status',headers={'X-Bot-Pin':'test'}).json()
 assert b['equity_usd']==pytest.approx(c['equity_usd']) and c['engaged_margin_usd']==40

def test_hot_reload(shared):
 e,a,sl=shared;c=e.config.read();c['portfolio_risk']['shared_c3_account']=False;e.config.write(c);assert sl.shared_account is None
 c['portfolio_risk']['shared_c3_account']=True;e.config.write(c);assert sl.shared_account is not None

def test_runtime_apply_idempotent_preserves_strategy(tmp_path):
 from apply_shared_capital import apply
 m=tmp_path/'m.json';c=tmp_path/'c.json';sh=json.loads((Path(__file__).parents[1]/'config.json').read_text());sh['strategy_settings']['donchian_entry_period']=20;m.write_text(json.dumps(sh))
 apply(m,c);first=(m.read_bytes(),c.read_bytes());apply(m,c);assert first==(m.read_bytes(),c.read_bytes());assert B.ConfigStore(m).read()['strategy_settings']['donchian_entry_period']==20
