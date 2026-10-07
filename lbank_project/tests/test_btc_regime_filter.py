"""BTC regime gate: alts skip entries while BTC's last closed 4h bar is inside its Kumo; BTC itself is never gated."""
import pytest
import lbank_bot as lb
from test_system import cfg,system,bars_for

SYMS=['BTC/USDT:USDT','ETH/USDT:USDT']

def deployed():
    import json;from pathlib import Path
    return lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))

def setup(system,monkeypatch,btc_kumo,enabled=True):
    c=deployed();c['symbols']=SYMS;c['risk_and_exit']['max_open_positions']=2
    c['strategy_settings'].update(atr_regime_filter_enabled=False,btc_regime_filter_enabled=enabled,btc_regime_symbol=SYMS[0],stop_width_filter_enabled=False)
    system.config.write(c);now=1_800_000_003
    for symbol in SYMS:
        bars=bars_for(now,'4h');bars[-2][4]=110;bars[-2][2]=max(bars[-2][2],111);bars[-2][3]=min(bars[-2][3],109);system.data.bars[symbol,'4h']=bars;system.data.prices[symbol]=110.
    return c,now,lb.indicators

def run(system,monkeypatch,btc_inside,enabled=True):
    c,now,original=setup(system,monkeypatch,None,enabled)
    def indicators(raw,cfg_,tf,when):
        f=original(raw,cfg_,tf,when);last=len(f)-1;f.loc[last,['kijun','donchian_high_10','donchian_low_10','atr']]=[90,100,85,2]
        is_btc=raw is system.data.btc_raw
        f.loc[last,['kumo_top','kumo_bottom']]=([200.,50.] if (is_btc and btc_inside) else [100.,85.]);return f
    candles=system.data.candles
    def tagged(symbol,tf,limit):
        out=candles(symbol,tf,limit)
        if symbol==SYMS[0]:system.data.btc_raw=out
        return out
    system.data.candles=tagged;monkeypatch.setattr(lb,'indicators',indicators);monkeypatch.setattr(lb,'regime',lambda df,c:'long');monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
    return system.scan(now)

def test_alts_blocked_while_btc_inside_kumo_but_btc_trades(system,monkeypatch):
    assert run(system,monkeypatch,btc_inside=True)
    assert [p['symbol'] for p in system.db.positions()]==[SYMS[0]]

def test_open_when_btc_outside_kumo(system,monkeypatch):
    run(system,monkeypatch,btc_inside=False)
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS)

def test_switch_off_means_no_gate(system,monkeypatch):
    run(system,monkeypatch,btc_inside=True,enabled=False)
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS)

def test_stale_btc_data_retries_without_consuming_the_candle(system,monkeypatch):
    c,now,original=setup(system,monkeypatch,None)
    def candles(symbol,tf,limit):
        if symbol==SYMS[0]:raise RuntimeError('BTC feed down')
        return system.data.bars[symbol,tf][-limit:]
    system.data.candles=candles;monkeypatch.setattr(lb,'regime',lambda df,c:'long');monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
    assert system.scan(now) is False and not system.db.positions()
    with system.db.connect() as db:assert db.execute('SELECT COUNT(*) FROM scanned_candles').fetchone()[0]==0

def test_config_rules():
    import json;from pathlib import Path
    c=lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()));s=c['strategy_settings']
    assert not s['btc_regime_filter_enabled'] and not s['stop_width_filter_enabled'] and s['atr_regime_filter_enabled'] and s['initial_stop_atr_mult']==2.0
    bad=json.loads(json.dumps(c));bad['strategy_settings'].update(btc_regime_filter_enabled=True,btc_regime_symbol='XYZ/USDT:USDT')
    with pytest.raises(lb.ConfigError):lb.validate_config(bad)
    legacy=json.loads(json.dumps(c))
    for k in ('btc_regime_filter_enabled','btc_regime_symbol'):legacy['strategy_settings'].pop(k)
    assert lb.validate_config(legacy)['strategy_settings']['btc_regime_filter_enabled'] is False
