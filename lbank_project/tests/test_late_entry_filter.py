"""Late-entry gate (win-rate study): no new root entry after a large move in the trade direction over 60 4h candles."""
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import cfg,system,bars_for

SYMS=['BTC/USDT:USDT','ETH/USDT:USDT']

def deployed():
    return lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))

def frame(closes):return pd.DataFrame({'close':closes})

def test_move_is_side_signed_log_return_of_closed_closes():
    f=frame([100.]*10+[120.]*51)
    assert lb.late_entry_move(f,'long',60)==pytest.approx(math.log(1.2))
    assert lb.late_entry_move(f,'short',60)==pytest.approx(-math.log(1.2))
    assert lb.late_entry_move(frame([100.]*60),'long',60) is None          # needs 61 closes
    assert lb.late_entry_move(frame([0.]+[1.]*60),'long',60) is None

def test_move_matches_the_research_feature_when_data_is_present():
    """Same number as high_cagr/ideas/winrate/ledger.py f_ret60 on the prepared 4h features."""
    p=Path(__file__).parents[2]/'high_cagr/prepared/BTCUSDT/4h_standard.npz'
    if not p.exists():pytest.skip('prepared research features not restored')
    z=np.load(p);f=pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))
    for e in (400,3000,len(f)-2):
        assert lb.late_entry_move(f.iloc[:e+1],'short',60)==pytest.approx(-math.log(f.close.iloc[e]/f.close.iloc[e-60]),rel=1e-12)

def run(system,monkeypatch,moves,enabled=True):
    c=deployed();c['symbols']=SYMS;c['risk_and_exit']['max_open_positions']=2
    c['strategy_settings'].update(late_entry_filter_enabled=enabled,atr_regime_filter_enabled=False,btc_regime_filter_enabled=False,stop_width_filter_enabled=False)
    system.config.write(c);now=1_800_000_003
    for symbol in SYMS:
        bars=bars_for(now,'4h',n=300);bars[-2][4]=110;bars[-2][2]=max(bars[-2][2],111);bars[-2][3]=min(bars[-2][3],109);system.data.bars[symbol,'4h']=bars;system.data.prices[symbol]=110.
    original=lb.indicators
    def indicators(raw,cfg_,tf,when):
        f=original(raw,cfg_,tf,when);last=len(f)-1;f.loc[last,['kijun','donchian_high_10','donchian_low_10','atr','kumo_top','kumo_bottom']]=[90,100,85,2,100,85];return f
    monkeypatch.setattr(lb,'indicators',indicators);monkeypatch.setattr(lb,'regime',lambda df,c:'long');monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
    seen=[]
    def move(df,side,bars):
        seen.append((side,bars));return moves[len(seen)-1]
    monkeypatch.setattr(lb,'late_entry_move',move)
    system.scan(now);return seen

def test_late_symbol_is_skipped(system,monkeypatch):
    seen=run(system,monkeypatch,(0.20,0.05))
    assert [p['symbol'] for p in system.db.positions()]==[SYMS[1]] and seen==[('long',60)]*2

def test_switch_off_means_no_gate(system,monkeypatch):
    seen=run(system,monkeypatch,(0.5,0.5),enabled=False)
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS) and not seen

def test_missing_history_does_not_block(system,monkeypatch):
    run(system,monkeypatch,(None,None))
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS)

def test_config_rules():
    s=deployed()['strategy_settings']
    assert s['late_entry_filter_enabled'] is True and s['late_entry_bars']==60 and s['late_entry_max_log_move']==pytest.approx(.1521)
    c=deployed()
    for key,value in (('late_entry_bars',5),('late_entry_max_log_move',0.0),('late_entry_max_log_move',3.0)):
        bad=json.loads(json.dumps(c));bad['strategy_settings'][key]=value
        with pytest.raises(lb.ConfigError):lb.validate_config(bad)
    legacy=json.loads(json.dumps(c))
    for k in ('late_entry_filter_enabled','late_entry_bars','late_entry_max_log_move'):legacy['strategy_settings'].pop(k)
    assert lb.validate_config(legacy)['strategy_settings']['late_entry_filter_enabled'] is False
