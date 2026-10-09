import pytest,pandas as pd
import lbank_bot as lb
from test_system import setup_position,cfg,system,bars_for

def test_old_schema_normalizes_options(cfg):
 assert lb.validate_config(cfg)['portfolio_risk']==dict(rank_by='LEGACY_RSI',enforce_shared_margin=False,shared_c3_account=False,margin_allocation_mode='PER_SLOT')

def test_pending_margin_reserved(system):
 p=setup_position(system);c=system.config.read();c['risk_and_exit']['default_isolated_leverage']=5
 assert system.available_notional(1000,c)==pytest.approx((1000-p['qty']*p['entry_price']/5)*5)
 assert system.available_notional(1000,c,p['symbol'])==5000

def test_wrong_family_rank_rejected(cfg):
 c=lb.validate_config(cfg);c['portfolio_risk']['rank_by']='BREAKOUT_DISTANCE'
 with pytest.raises(lb.ConfigError):lb.validate_config(c)

def test_activation_enforces_shared_margin(system):
 p=setup_position(system);c=system.config.read();c['portfolio_risk']['enforce_shared_margin']=True;system.config.write(c)
 system.available_notional=lambda equity,c,exclude_symbol=None:50.
 assert system._activate(p,101.,1_800_000_001)
 filled=system.db.position(p['symbol']);assert filled['qty']*filled['entry_price']<=50+1e-8

def test_scanner_prefers_stronger_breakout(system,monkeypatch):
 c=system.config.read();c['symbols']=['BTC/USDT:USDT','ETH/USDT:USDT'];c['strategy_mode']['mode']='SINGLE';c['strategy_mode']['single_timeframe']='4h'
 c['archetype_strategy'].update(family='DONCHIAN',entry_variant='MARKET',trail_source='DONCHIAN10',pending_policy='GTC_REGIME')
 c['al_brooks_filters']['require_signal_bar_breakout']=False;c['risk_and_exit']['max_open_positions']=1
 c['portfolio_risk']=dict(rank_by='BREAKOUT_DISTANCE',enforce_shared_margin=True);system.config.write(c)
 now=1_800_000_003
 for symbol in c['symbols']:
  bars=bars_for(now,'4h');bars[-2][4]=102 if symbol.startswith('BTC') else 110;bars[-2][2]=max(bars[-2][2],bars[-2][4]+1);bars[-2][3]=min(bars[-2][3],bars[-2][4]-1)
  system.data.bars[symbol,'4h']=bars;system.data.prices[symbol]=bars[-2][4]
 original=lb.indicators
 def indicators(raw,c,tf,now):
  f=original(raw,c,tf,now);f.loc[len(f)-1,['kijun','kumo_top','kumo_bottom','donchian_high_20','donchian_low_20','atr']]=[90,100,85,100,85,2];return f
 monkeypatch.setattr(lb,'indicators',indicators);monkeypatch.setattr(lb,'regime',lambda df,c:'long');monkeypatch.setattr(lb,'entry_signal',lambda *a:True)
 system.scan(now)
 assert [p['symbol'] for p in system.db.positions()]==['ETH/USDT:USDT']
