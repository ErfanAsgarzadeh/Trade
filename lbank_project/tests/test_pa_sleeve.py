"""PA sleeve (third strategy): parity with the research backtest, order/position life cycle, shared account, dashboard."""
import json,sys,time
from pathlib import Path
import numpy as np,pytest
import pa_sleeve as P
ROOT=Path(__file__).resolve().parents[2]
H4=4*3600;HDR={'X-Bot-Pin':'test'}

def pcfg(**kw):
    c=json.loads((Path(__file__).parents[1]/'pa_config.json').read_text());c.update(kw);return P.validate(c)

def test_config_is_paper_only_and_validated():
    c=pcfg();assert c['dry_run_mode'] is True and len(c['symbols'])==20 and c['risk_per_trade_pct']==.0015 and c['target_r']==2. and c['time_stop_bars']==30
    for bad in (dict(dry_run_mode=False),dict(timeframe='1h'),dict(time_stop_bars=2.5),dict(risk_per_trade_pct=.05),dict(candle_fetch_limit=50),dict(symbols=[])):
        with pytest.raises(ValueError):pcfg(**bad)
    with pytest.raises(ValueError):P.validate({**pcfg(),'surprise':1})

@pytest.mark.parametrize('coin,min_range',[('LINKUSDT',0.),('ATOMUSDT',0.),('LINKUSDT',1.1)])
def test_signals_match_the_backtest(coin,min_range):
    """Every 4h key-reversal signal, entry level and stop equals high_cagr/ideas/pa_bot.py on real data."""
    p=ROOT/'high_cagr/prepared_stage2'/coin/'prices.npy'
    if not p.exists():pytest.skip('research data not restored')
    sys.path.insert(0,str(ROOT));from high_cagr.ideas import pa_bot as R, ltf_search as L;from high_cagr import run_suite as rs
    px=np.load(p);g=R.signals(px,240,'KEYREV');o,h,l,c=L.bars(px,240);n=len(c);conf=pcfg(min_range_atr=min_range)
    if min_range:   # same filter as high_cagr/ideas/pa_opt_combo.py fn: skip signal bars whose range < min_range x ATR
        g=dict(g);g['side']=np.where((h-l)>=min_range*g['atr'],g['side'],0)
    ts=rs.START+np.arange(n)*240*60000;rows=np.column_stack([ts,o,h,l,c,np.zeros(n)])
    want=np.where(g['side']!=0)[0];rng=np.random.default_rng(2)
    check=sorted(set(want[want>400].tolist())|set(rng.choice(np.arange(400,n-1),300,replace=False).tolist()));hits=0
    for t in check:
        win=rows[t-299:t+2].tolist();now=(ts[t]+240*60000)/1000+3
        s=P.signal(P.features(win,now,conf),conf)
        if g['side'][t]==0:assert s is None,(coin,t,s);continue
        assert s and s['side']==('long' if g['side'][t]>0 else 'short'),(coin,t,s)
        assert s['level']==pytest.approx(g['lev'][t],rel=1e-12) and s['stop']==pytest.approx(g['stp'][t],rel=1e-6);hits+=1
    assert hits>50

class FakeData:
    def __init__(self,rows,price):self.rows=rows;self.px=price
    def candles(self,s,tf,limit):return self.rows[-limit:]
    def price(self,s):return self.px
    def market(self,s):return {'contractSize':1.0}
    def precision(self,s,q):return float(f'{q:.6f}')
    def tradable(self,s,q,p):return q>0

START=1_700_006_400_000
def rows_with_keyrev(side='long',n=120):
    """Slow drift, then an outside bar at a fresh 11-bar low that closes near its high (mirror for short); +1 forming candle."""
    out=[];base=100.
    for i in range(n-1):
        cl=base-.2*i if side=='long' else base+.2*i;out.append([START+i*H4*1000,cl+.1,cl+.6,cl-.6,cl,1.])
    p=out[-1]
    if side=='long':out.append([START+(n-1)*H4*1000,p[4],p[2]+1.,p[3]-1.,p[2]+.8,1.])
    else:out.append([START+(n-1)*H4*1000,p[4],p[2]+1.,p[3]-1.,p[3]-.8,1.])
    out.append([START+n*H4*1000,out[-1][4],out[-1][4],out[-1][4],out[-1][4],1.]);return out

def sleeve(tmp_path,rows,price,db='pa.db',**kw):
    st=P.Store(tmp_path/db);return P.Sleeve(pcfg(symbols=['LINK/USDT:USDT'],**kw),st,FakeData(rows,price)),st

def scan_time(rows):return (rows[-1][0])/1000+3   # just after the signal candle closed

def test_long_order_fill_target_and_pnl(tmp_path):
    rows=rows_with_keyrev('long');sig=rows[-2];sl,st=sleeve(tmp_path,rows,sig[4]);now=scan_time(rows)
    sl.scan(now);o=st.orders()['LINK/USDT:USDT'];assert o['side']=='long' and o['level']==sig[2] and o['stop']<sig[3]
    assert st.positions()==[]                                  # price below the level: still waiting
    sl.data.px=sig[2]+.05;sl.watchdog(now+60);p=st.positions()[0];assert st.orders()=={}
    dist=p['entry']-p['stop'];assert p['target']==pytest.approx(p['entry']+2*dist)
    assert p['qty']*p['entry']==pytest.approx(.0015*10000/(dist/p['entry']+.0012+.0004),rel=1e-4)
    sl.data.px=p['target']+.01;sl.watchdog(now+120);assert st.positions()==[]
    with st.db() as db:r=db.execute('SELECT reason,pnl FROM trades').fetchone()
    assert r[0]=='target' and r[1]>0

def test_short_mirror_and_stop_exit(tmp_path):
    rows=rows_with_keyrev('short');sig=rows[-2];sl,st=sleeve(tmp_path,rows,sig[4]);now=scan_time(rows)
    sl.scan(now);o=st.orders()['LINK/USDT:USDT'];assert o['side']=='short' and o['level']==sig[3] and o['stop']>sig[2]
    sl.data.px=sig[3]-.05;sl.watchdog(now+60);p=st.positions()[0];assert p['side']=='short'
    sl.data.px=p['stop']+.01;sl.watchdog(now+120)
    with st.db() as db:assert db.execute('SELECT reason FROM trades').fetchone()[0]=='stop'

def test_order_cancelled_by_stop_or_expiry(tmp_path):
    rows=rows_with_keyrev('long');sl,st=sleeve(tmp_path,rows,rows[-2][4]);now=scan_time(rows)
    sl.scan(now);sl.data.px=st.orders()['LINK/USDT:USDT']['stop']-.01;sl.watchdog(now+60);assert st.orders()=={} and st.positions()==[]
    sl2,st2=sleeve(tmp_path,rows,rows[-2][4],db='pa2.db');sl2.scan(now)
    sl2.data.px=rows[-2][2]+1;sl2.watchdog(now+H4*2);assert st2.orders()=={} and st2.positions()==[]   # next candle closed: expired

def test_time_stop_after_30_candles(tmp_path):
    rows=rows_with_keyrev('long');sig=rows[-2];sl,st=sleeve(tmp_path,rows,sig[4]);now=scan_time(rows)
    sl.scan(now);sl.data.px=sig[2]+.05;sl.watchdog(now+60);p=st.positions()[0]
    later=rows[:-1]+[[rows[-1][0]+k*H4*1000,sig[2],sig[2]+.1,sig[2]-.1,sig[2],1.] for k in range(32)]
    sl.data.rows=later;sl.scan(later[-2][0]/1000+3);assert st.positions()   # entry candle + 29 later candles closed: 29 < 30
    sl.scan(later[-1][0]/1000+3);assert st.positions()==[]
    with st.db() as db:assert db.execute('SELECT reason FROM trades').fetchone()[0]=='time'

def test_disabled_sleeve_places_no_orders(tmp_path):
    rows=rows_with_keyrev('long');sl,st=sleeve(tmp_path,rows,rows[-2][4],enabled=False);sl.scan(scan_time(rows));assert st.orders()=={}

def test_in_bot_switch(monkeypatch):
    class E:main_paper_equity=staticmethod(lambda:1e4);shared_paper_account=staticmethod(lambda:None)
    import threading;stop=threading.Event();stop.set()
    monkeypatch.setenv('PA_IN_BOT','0');assert P.start_in_bot(E(),stop) is None

from test_system import system, cfg   # noqa: E402,F401  (fixtures)

def put_pa(sym,qty=2.):
    _,st=P.paths()
    with st.db() as db:
        db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(sym,'long',100.,qty,95.,100.,1.,0,0,qty*5))
        db.execute('INSERT INTO position_margin VALUES(?,?,?)',(sym,1.,5))
    return st

def test_shared_account_counts_pa(system):
    c=system.config.read();c['portfolio_risk']['shared_c3_account']=True;system.config.write(c)
    sym='LINK/USDT:USDT';system.data.prices[sym]=110.;before=system.paper_equity();a0=system.shared_paper_account().reserved_margin()
    put_pa(sym);a=system.shared_paper_account()
    assert system.paper_equity()==pytest.approx(before+20.-.0012/2*210*2) and a.reserved_margin()==pytest.approx(a0+40.)

def test_dashboard_pa_api_and_panic(system,monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard_server import create_app
    monkeypatch.setenv('BOT_PIN','test');sym=system.config.read()['symbols'][0];st=put_pa(sym)
    st.set_order('LINK/USDT:USDT',dict(side='long',level=1.,stop=.9,expires=9e15,signal_ts=0,atr=.1))
    with TestClient(create_app(system)) as api:
        assert api.get('/api/pa/status').status_code==401
        s=api.get('/api/pa/status',headers=HDR).json();assert s['open_positions_count']==1 and len(s['pending_orders'])==1 and s['coins']==20
        r=api.get('/api/pa/config',headers=HDR);c=r.json();c['risk_per_trade_pct']=.002
        assert api.put('/api/pa/config',headers={**HDR,'If-Match':r.headers['ETag']},json=c).status_code==200
        assert api.put('/api/pa/config',headers=HDR,json={**c,'dry_run_mode':False}).status_code==422
        assert api.post('/api/pa/close',headers=HDR,json={'symbol':'LINK/USDT:USDT'}).json()['result']=='cancelled'
        res=api.post('/api/positions/close-all',headers=HDR,json={'disable_auto_trade':True}).json()
    assert [x['result'] for x in res['pa']]==['closed'] and st.positions()==[] and P.load(P.paths()[0])['enabled'] is False

def test_no_target_option_exits_only_by_stop_or_time(tmp_path):
    rows=rows_with_keyrev('long');sig=rows[-2];sl,st=sleeve(tmp_path,rows,sig[4],target_r=0.);now=scan_time(rows)
    sl.scan(now);sl.data.px=sig[2]+.05;sl.watchdog(now+60);p=st.positions()[0];assert p['target'] is None
    sl.data.px=p['entry']+10*(p['entry']-p['stop']);sl.watchdog(now+120);assert st.positions()   # far beyond 2R: still open

def test_min_range_filter(tmp_path):
    rows=rows_with_keyrev('long');sl,st=sleeve(tmp_path,rows,rows[-2][4],min_range_atr=5.);sl.scan(scan_time(rows));assert st.orders()=={}
    sl2,st2=sleeve(tmp_path,rows,rows[-2][4],db='b.db',min_range_atr=1.1);sl2.scan(scan_time(rows));assert st2.orders()
