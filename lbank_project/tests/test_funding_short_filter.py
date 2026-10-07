"""Funding short filter F4: no new short while the mean of the last N funding prints before the entry bar is < threshold."""
import json
from pathlib import Path
import pytest
import lbank_bot as lb
from test_system import cfg,system,bars_for

SYMS=['BTC/USDT:USDT','ETH/USDT:USDT']

def deployed():
    return lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))

def run(system,monkeypatch,side,funding,enabled=True):
    c=deployed();c['symbols']=SYMS;c['risk_and_exit']['max_open_positions']=2
    c['strategy_settings'].update(btc_regime_filter_enabled=False,stop_width_filter_enabled=False,funding_short_filter_enabled=enabled)
    system.config.write(c);now=1_800_000_003;calls=[]
    for symbol in SYMS:
        bars=bars_for(now,'4h');bars[-2][4]=110;bars[-2][2]=max(bars[-2][2],111);bars[-2][3]=min(bars[-2][3],109);system.data.bars[symbol,'4h']=bars;system.data.prices[symbol]=110.
    if funding is not ...:
        def funding_mean(symbol,prints,before_ms):
            calls.append((symbol,prints,before_ms));return funding.get(symbol)
        system.data.funding_mean=funding_mean
    original=lb.indicators
    def indicators(raw,cfg_,tf,when):
        f=original(raw,cfg_,tf,when);last=len(f)-1;f.loc[last,['kijun','donchian_high_10','donchian_low_10','atr','kumo_top','kumo_bottom']]=[130,135,115,2,135,130];return f
    monkeypatch.setattr(lb,'indicators',indicators);monkeypatch.setattr(lb,'regime',lambda df,c:side);monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
    assert system.scan(now)
    return sorted(p['symbol'] for p in system.db.positions()),calls,now

def test_short_blocked_when_funding_negative_only_for_that_symbol(system,monkeypatch):
    opened,calls,now=run(system,monkeypatch,'short',{SYMS[0]:-1e-5,SYMS[1]:2e-5})
    assert opened==[SYMS[1]]
    # prints strictly before the entry bar = close of the last closed 4h bar
    assert all(p==9 and b==(int(now)//14400)*14400*1000 for _,p,b in calls)

def test_longs_never_consult_funding(system,monkeypatch):
    opened,calls,_=run(system,monkeypatch,'long',{SYMS[0]:-1e-3,SYMS[1]:-1e-3})
    assert opened==sorted(SYMS) and calls==[]

def test_switch_off(system,monkeypatch):
    opened,calls,_=run(system,monkeypatch,'short',{SYMS[0]:-1e-3,SYMS[1]:-1e-3},enabled=False)
    assert opened==sorted(SYMS) and calls==[]

def test_missing_funding_does_not_block(system,monkeypatch):
    assert run(system,monkeypatch,'short',{})[0]==sorted(SYMS)

def test_data_source_without_funding_does_not_block(system,monkeypatch):
    assert not hasattr(system.data,'funding_mean')
    assert run(system,monkeypatch,'short',...)[0]==sorted(SYMS)

def test_csv_reader(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_DATA_MODE','csv-lbank');monkeypatch.setenv('FUNDING_DIR',str(tmp_path))
    md=lb.MarketData();h=8*3600*1000;t0=1_700_000_000_000
    rows=[(t0+k*h,r) for k,r in enumerate([5e-4]*3+[-1e-4]*9+[9e-4])]   # last print is AT before_ms -> excluded
    (tmp_path/'ETH_USDT_USDT_funding.csv').write_text('timestamp,funding_rate\n'+''.join(f'{t},{r}\n' for t,r in rows))
    before=rows[-1][0]
    assert md.funding_mean('ETH/USDT:USDT',9,before)==pytest.approx(-1e-4)
    assert md.funding_mean('ETH/USDT:USDT',12,before)==pytest.approx((3*5e-4-9*1e-4)/12)
    assert md.funding_mean('ETH/USDT:USDT',13,before) is None                # too few prints
    assert md.funding_mean('ETH/USDT:USDT',9,before+2*h) is None             # stale feed
    assert md.funding_mean('BTC/USDT:USDT',9,before) is None                 # no file
    (tmp_path/'XRP_USDT_USDT_funding.csv').write_text('ts,rate\n1,2\n')
    with pytest.raises(ValueError):md.funding_mean('XRP/USDT:USDT',1,10)
    monkeypatch.setenv('PAPER_DATA_MODE','demo');assert lb.MarketData().funding_mean('ETH/USDT:USDT',9,before) is None

def test_config():
    c=deployed();s=c['strategy_settings']
    assert s['funding_short_filter_enabled'] is False and s['funding_short_prints']==9 and s['funding_short_threshold']==0.0
    for k,v in (('funding_short_prints',0),('funding_short_prints',91),('funding_short_threshold',0.05)):
        bad=json.loads(json.dumps(c));bad['strategy_settings'][k]=v
        with pytest.raises(lb.ConfigError):lb.validate_config(bad)

def test_fetch_funding_roundtrip(tmp_path,monkeypatch):
    import fetch_funding as ff
    assert ff.binance_symbol('1000SHIB/USDT:USDT')=='1000SHIBUSDT'
    rows=ff.rows_from([{'fundingTime':2000,'fundingRate':'-0.0001'},{'fundingTime':1000,'fundingRate':'0.0002'}])
    path=tmp_path/'ETH_USDT_USDT_funding.csv';ff.write_csv(path,rows)
    monkeypatch.setenv('PAPER_DATA_MODE','csv-lbank');monkeypatch.setenv('FUNDING_DIR',str(tmp_path))
    assert lb.MarketData().funding_mean('ETH/USDT:USDT',2,2001)==pytest.approx(5e-5)

def test_lbank_snapshot_merge(tmp_path):
    import fetch_funding as ff
    path=tmp_path/'ETH_USDT_USDT_funding.csv'
    for info in ({'fundingTimestamp':1000,'fundingRate':1e-4},{'fundingTimestamp':1000,'fundingRate':-2e-4},{'fundingTimestamp':2000,'fundingRate':3e-4}):
        ff.write_csv(path,ff.merge_lbank(path,info))
    assert ff.read_csv(path)=={1000:-2e-4,2000:3e-4}      # one row per settlement, latest observation kept
