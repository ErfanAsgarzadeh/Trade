"""Apply the requested paper allocation to runtime configs without changing signals/exits."""
import argparse,json
from pathlib import Path
import lbank_bot as bot
import c3_sleeve as c3

def apply(main_path,c3_path):
    store=bot.ConfigStore(main_path);cfg=store.read()
    cfg['bot_control']['dry_run_mode']=True
    cfg['risk_and_exit'].update(risk_per_trade_pct=.01,engaged_capital_pct=.6,max_open_positions=4,leverage_mode='FIXED_LEVERAGE',default_isolated_leverage=5)
    cfg['portfolio_risk'].update(shared_c3_account=True,enforce_shared_margin=True,margin_allocation_mode='SHARED_POOL')
    c3_path=Path(c3_path)
    if not c3_path.exists():c3.prepare_config(c3_path,Path(__file__).with_name('c3_config.json'))
    conf=c3.load(c3_path);conf.update(risk_per_trade_pct=.004,isolated_leverage=5,max_open_positions=0,dry_run_mode=True)
    c3.write_config(c3_path,conf);store.write(cfg)
    return dict(main_risk=.01,c3_risk=.004,shared_margin_cap=.6,dry_run_mode=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='runtime/config.json');ap.add_argument('--c3-config',default='runtime/c3_config.json');a=ap.parse_args();print(json.dumps(apply(a.config,a.c3_config)))
