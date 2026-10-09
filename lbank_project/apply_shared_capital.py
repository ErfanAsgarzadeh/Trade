"""Apply the requested paper allocation to runtime configs without changing signals/exits."""
import argparse,json
from pathlib import Path
import lbank_bot as bot
import c3_sleeve as c3
import pa_sleeve as pa

def apply(main_path,c3_path,pa_path=None):
    store=bot.ConfigStore(main_path);cfg=store.read()
    cfg['bot_control']['dry_run_mode']=True
    cfg['risk_and_exit'].update(risk_per_trade_pct=.01,engaged_capital_pct=.8,max_open_positions=4,leverage_mode='FIXED_LEVERAGE',default_isolated_leverage=5)
    cfg['portfolio_risk'].update(shared_c3_account=True,enforce_shared_margin=True,margin_allocation_mode='SHARED_POOL')
    c3_path=Path(c3_path)
    if not c3_path.exists():c3.prepare_config(c3_path,Path(__file__).with_name('c3_config.json'))
    conf=c3.load(c3_path);conf.update(risk_per_trade_pct=.004,isolated_leverage=5,max_open_positions=0,dry_run_mode=True)
    c3.write_config(c3_path,conf);store.write(cfg)
    out=dict(main_risk=.01,c3_risk=.004,shared_margin_cap=.8,dry_run_mode=True)
    if pa_path:   # Ghoghnous (PA): C1 defaults (no target, signal range >= 1.1 ATR, 0.25%)
        pa_path=Path(pa_path)
        if not pa_path.exists():pa.prepare_config(pa_path,Path(__file__).with_name('pa_config.json'))
        p=pa.load(pa_path);p.update(risk_per_trade_pct=.0025,target_r=0.,min_range_atr=1.1,isolated_leverage=5,dry_run_mode=True);pa.write_config(pa_path,p);out['pa_risk']=.0025
    return out
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='runtime/config.json');ap.add_argument('--c3-config',default='runtime/c3_config.json');ap.add_argument('--pa-config',default='runtime/pa_config.json');a=ap.parse_args();print(json.dumps(apply(a.config,a.c3_config,a.pa_config)))
