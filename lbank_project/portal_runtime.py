"""Read an administrator-bound paper runtime without importing an engine or mutating it."""
import json
from pathlib import Path
import sqlite3
import time


def robots(runtime,expected_customer=None):
    identity_ok=True
    if runtime and expected_customer:
        try:
            identity_ok=json.loads((Path(runtime)/'customer_identity.json').read_text()) == {'customer_id':expected_customer}
        except (OSError,ValueError):identity_ok=False
    names=[('main','شاهین','config.json','lbank_ichimoku_bot.db'),
           ('c3','موج‌سوار','c3_config.json','c3_sleeve.db'),('pa','ققنوس','pa_config.json','pa_sleeve.db')]
    result=[]
    for code,name,config_name,db_name in names:
        item=dict(bot=code,name=name,state='not_provisioned',execution='paper',positions=[],trades=[])
        if not identity_ok:
            item['state']='unavailable';result.append(item);continue
        if runtime:
            root=Path(runtime)
            try:
                config=json.loads((root/config_name).read_text())
                control=config['bot_control'] if code=='main' else config
                if control['dry_run_mode'] is not True:raise ValueError('Unknown execution mode')
                item['entries_requested']=control['auto_trade_enabled'] if code=='main' else control['enabled']
                path=root/db_name
                if not path.is_file():
                    item['state']='not_started';result.append(item);continue
                db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
                db.row_factory=sqlite3.Row
                try:
                    fields='symbol,side,entry_price,qty,active_sl,state' if code=='main' else 'symbol,side,entry,qty,stop'
                    item['positions']=[dict(row) for row in db.execute('SELECT '+fields+' FROM positions LIMIT 100')]
                    table='trade_history' if code=='main' else 'trades'
                    fields='symbol,side,entry_price,exit_price,pnl_usd,reason' if code=='main' else 'symbol,side,entry,exit,pnl,reason'
                    item['trades']=[dict(row) for row in db.execute('SELECT '+fields+' FROM '+table+' ORDER BY id DESC LIMIT 50')]
                    # Only Shahin writes a heartbeat: don't invent health for the other sleeves.
                    item['state']='health_unknown'
                    if code=='main':
                        stamp=db.execute("SELECT value FROM runtime WHERE key='watchdog_at'").fetchone()
                        heartbeat=float(stamp[0]) if stamp else 0
                        item['state']='running' if heartbeat and time.time()-heartbeat<60 else 'stale'
                finally:db.close()
            except (OSError,ValueError,KeyError,sqlite3.Error):item['state']='unavailable'
        result.append(item)
    return result
