"""ATR regime filter 2A: no entry (or pyramid add) while ATR < min_ratio x median ATR of the prior `window` closed bars."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import lbank_bot as lb
from test_system import cfg,system,bars_for

SYMS=['BTC/USDT:USDT','ETH/USDT:USDT']

def deployed():
    return lb.validate_config(json.loads((Path(__file__).parents[1]/'config.json').read_text()))

def ranged(now,widths,tf='4h'):
    """Closed bars (plus one forming bar) whose true range is the given width each, around a flat 100."""
    seconds=lb.TIMEFRAMES[tf];boundary=int(now)//seconds*seconds;n=len(widths)+1;out=[]
    for i,w in enumerate(list(widths)+[widths[-1]]):
        stamp=boundary-(n-i-1)*seconds;out.append([stamp*1000,100.,100+w/2,100-w/2,100.,10.])
    return out

def test_ratio_reads_expansion_and_contraction():
    c=deployed();now=1_800_000_003;span=c['ichimoku_params']['candle_fetch_limit']-1
    calm=[1.]*(span+60)
    assert lb.atr_regime_ratio(ranged(now,calm),c,'4h',now,60)==pytest.approx(1.)
    wide=calm[:-1]+[30.];assert lb.atr_regime_ratio(ranged(now,wide),c,'4h',now,60)>1
    narrow=[2.]*(span+59)+[.01];assert lb.atr_regime_ratio(ranged(now,narrow),c,'4h',now,60)<1

def test_short_or_gapped_history_returns_none():
    c=deployed();now=1_800_000_003;span=c['ichimoku_params']['candle_fetch_limit']-1
    assert lb.atr_regime_ratio(ranged(now,[1.]*(span+30)),c,'4h',now,60) is None
    bars=ranged(now,[1.]*(span+60));del bars[100]
    assert lb.atr_regime_ratio(bars,c,'4h',now,60) is None

def test_ratio_matches_research_feature_when_data_is_present():
    """Same number the backtest used: frame ATR / rolling(60).median().shift(1) on the prepared 4h features."""
    root=Path(__file__).parents[2]/'high_cagr/prepared/BTCUSDT/4h_standard.npz'
    if not root.exists():pytest.skip('prepared research features not restored')
    z=np.load(root);f=pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])));c=deployed()
    expected=(f.atr/f.atr.rolling(60).median().shift(1)).to_numpy()
    for e in (400,3000,len(f)-2):
        bars=f.iloc[e-258:e+2][['timestamp','open','high','low','close','volume']].values.tolist()
        assert lb.atr_regime_ratio(bars,c,'4h',(f.timestamp.iloc[e+1]+3000)/1000,60)==pytest.approx(expected[e],rel=1e-12)

def run(system,monkeypatch,ratio,enabled=True):
    c=deployed();c['symbols']=SYMS;c['risk_and_exit']['max_open_positions']=2
    c['strategy_settings'].update(atr_regime_filter_enabled=enabled,btc_regime_filter_enabled=False,stop_width_filter_enabled=False)
    system.config.write(c);now=1_800_000_003
    for symbol in SYMS:
        bars=bars_for(now,'4h',n=300);bars[-2][4]=110;bars[-2][2]=max(bars[-2][2],111);bars[-2][3]=min(bars[-2][3],109);system.data.bars[symbol,'4h']=bars;system.data.prices[symbol]=110.
    original=lb.indicators
    def indicators(raw,cfg_,tf,when):
        f=original(raw,cfg_,tf,when);last=len(f)-1;f.loc[last,['kijun','donchian_high_10','donchian_low_10','atr','kumo_top','kumo_bottom']]=[90,100,85,2,100,85];return f
    monkeypatch.setattr(lb,'indicators',indicators);monkeypatch.setattr(lb,'regime',lambda df,c:'long');monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
    calls=[];candles=system.data.candles;last=[]
    def tracked(symbol,tf,limit):
        calls.append(limit);last[:]=[symbol];return candles(symbol,tf,limit)
    system.data.candles=tracked
    monkeypatch.setattr(lb,'atr_regime_ratio',lambda bars,c,tf,now,window:ratio[SYMS.index(last[0])])
    system.scan(now);return c,calls

def test_low_atr_symbol_is_skipped(system,monkeypatch):
    run(system,monkeypatch,(0.8,1.3))
    assert [p['symbol'] for p in system.db.positions()]==[SYMS[1]]

def test_high_atr_symbols_open_and_history_is_long_enough(system,monkeypatch):
    c,calls=run(system,monkeypatch,(1.3,1.3))
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS)
    assert c['ichimoku_params']['candle_fetch_limit']+60 in calls

def test_switch_off_means_no_filter(system,monkeypatch):
    run(system,monkeypatch,(0.5,0.5),enabled=False)
    assert sorted(p['symbol'] for p in system.db.positions())==sorted(SYMS)

def test_missing_history_blocks(system,monkeypatch):
    run(system,monkeypatch,(None,None))
    assert not system.db.positions()

def test_config_rules():
    c=deployed()
    for key,value in (('atr_regime_window',5),('atr_regime_min_ratio',0.0)):
        bad=json.loads(json.dumps(c));bad['strategy_settings'][key]=value
        with pytest.raises(lb.ConfigError):lb.validate_config(bad)
    legacy=json.loads(json.dumps(c))
    for k in ('atr_regime_filter_enabled','atr_regime_window','atr_regime_min_ratio'):legacy['strategy_settings'].pop(k,None)
    s=lb.validate_config(legacy)['strategy_settings'];assert s['atr_regime_filter_enabled'] is False and s['atr_regime_window']==60
