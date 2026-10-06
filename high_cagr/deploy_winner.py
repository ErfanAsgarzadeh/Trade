"""Deploy only the predeclared eligible CAGR winner; preserve archived benchmarks."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lbank_project'))
import lbank_bot as bot

def main():
 m=json.loads((ROOT/'high_cagr/output/matrix.json').read_text());w=m['winner']
 if not w:print('NO ELIGIBLE WINNER: prior deployment retained');return
 assert w['eligible'] and w['worst_period_dd_pct']<=35
 # The selected result is 4h Donchian stop trailing, fully implemented below.
 assert w['entry_timeframe']=='4h' and w['trail']=='DONCHIAN10'
 p=ROOT/'lbank_project/config.json';prior=ROOT/'high_cagr/prior/config.json';prior.parent.mkdir(parents=True,exist_ok=True)
 if not prior.exists():prior.write_text(p.read_text())
 c=json.loads(prior.read_text());c['symbols']=[s[:-4]+'/USDT:USDT' for s in w['symbols']]
 c['strategy_mode'].update(mode='SINGLE',single_timeframe='4h')
 c['risk_and_exit'].update(risk_per_trade_pct=w['risk'],max_open_positions=w['max_open_positions'],engaged_capital_pct=.60,leverage_mode='FIXED_LEVERAGE',default_isolated_leverage=5)
 c['strategy_settings'].update(ichimoku_preset=w['preset'],donchian_entry_period=w['lookback'],initial_stop_mode='ATR2',exit_tp_mode='STOP_TRAIL_DONCHIAN10',hard_tp_rr=0.,breakeven_trigger_rr=0.,pyramid_enabled=w['pyramid'],initial_stop_anchor='SIGNAL')
 c=bot.validate_config(c);text=json.dumps(c,indent=2)+'\n';p.write_text(text);(ROOT/'high_cagr/output/winning_config.json').write_text(text);print('DEPLOYED',w['id'])
if __name__=='__main__':main()
