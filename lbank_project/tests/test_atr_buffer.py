import copy
from types import SimpleNamespace
import pytest
import lbank_bot as lb
import strategy_archetypes as shared
from test_system import cfg,system,setup_position,bars_for

def test_buffer_default_preserves_old_config(cfg):
 from pathlib import Path
 import json
 c=json.loads((Path(__file__).parents[1]/'config.json').read_text())
 if 'strategy_settings' in c:
  c['strategy_settings'].pop('trail_atr_buffer',None)
  c=lb.validate_config(c)
  assert c['risk_and_exit']['trail_atr_buffer']==0

@pytest.mark.parametrize('side,expected',[('long',103.5),('short',96.5)])
def test_buffer_direction(side,expected):
 bar=SimpleNamespace(opposite_low_10=104.,opposite_high_10=96.,atr=2.)
 assert shared.buffered_trail_stop(bar,side,'DONCHIAN10',.25)==expected

@pytest.mark.parametrize('side',['long','short'])
def test_runtime_buffer_and_ratchet(system,monkeypatch,side):
 c=system.config.read();c['bot_control']['auto_trade_enabled']=False;system.config.write(c)
 p=setup_position(system,side=side,state=lb.TRAILING)
 with system.db.connect() as db:
  db.execute("UPDATE positions SET trail_source='DONCHIAN10',trail_atr=.25 WHERE symbol=?",(p['symbol'],))
 original=lb.indicators;level=[104. if side=='long' else 96.]
 def indicator(bars,c,tf,now):
  df=original(bars,c,tf,now)
  df.loc[len(df)-1,['opposite_low_10','opposite_high_10','close','atr']]=[level[0],level[0],106 if side=='long' else 94,2]
  return df
 monkeypatch.setattr(lb,'indicators',indicator);now=1_800_000_003
 system.data.bars[p['symbol'],'1h']=bars_for(now);system.scan(now)
 stop=103.5 if side=='long' else 96.5
 assert system.db.position(p['symbol'])['active_sl']==pytest.approx(stop)
 level[0]+= -1 if side=='long' else 1
 now+=3600;system.data.bars[p['symbol'],'1h']=bars_for(now);system.scan(now)
 assert system.db.position(p['symbol'])['active_sl']==pytest.approx(stop)

@pytest.mark.parametrize('value',[.25,.5])
def test_public_buffer_survives_validation(value):
 from pathlib import Path
 import json
 c=json.loads((Path(__file__).parents[1]/'config.json').read_text())
 c['strategy_settings']['trail_atr_buffer']=value
 assert lb.validate_config(c)['risk_and_exit']['trail_atr_buffer']==value

@pytest.mark.parametrize('value',[-.1,5.1,float('nan'),float('inf')])
def test_invalid_buffer_rejected(value):
 from pathlib import Path
 import json
 c=json.loads((Path(__file__).parents[1]/'config.json').read_text())
 c['strategy_settings']['trail_atr_buffer']=value
 with pytest.raises((ValueError,TypeError)):
  lb.validate_config(c)

def test_close_only_ignores_price_buffer():
 from pathlib import Path
 import json
 c=json.loads((Path(__file__).parents[1]/'config.json').read_text())
 c['strategy_settings'].update(exit_tp_mode='CLOSE_TRAIL_KIJUN',trail_atr_buffer=.25,pyramid_enabled=False)
 assert lb.validate_config(c)['risk_and_exit']['trail_atr_buffer']==0
