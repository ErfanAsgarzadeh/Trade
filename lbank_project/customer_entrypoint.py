"""Start one customer service with fixed, isolated runtime paths."""
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading


def prepare():
    customer = os.getenv('BOT_CUSTOMER_ID', '')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}', customer):
        raise ValueError('A valid BOT_CUSTOMER_ID is required')
    runtime = Path(os.environ['BOT_RUNTIME_DIR']).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (runtime / '.identity.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        identity = runtime / 'customer_identity.json'
        if identity.exists():
            if json.loads(identity.read_text()) != {'customer_id': customer}:
                raise ValueError('Runtime belongs to another customer; refusing to start')
        else:
            identity.write_text(json.dumps({'customer_id': customer}))
            identity.chmod(0o600)
    os.environ['BOT_LICENSE_REQUIRED'] = '1'
    for env, name in (('BOT_CONFIG','config.json'),('BOT_DB','lbank_ichimoku_bot.db'),
                      ('C3_CONFIG','c3_config.json'),('C3_DB','c3_sleeve.db'),
                      ('PA_CONFIG','pa_config.json'),('PA_DB','pa_sleeve.db'),
                      ('OHLCV_DIR','ohlcv'),('FUNDING_DIR','funding')):
        os.environ[env] = str(runtime / name)
    for name in ('config.json','c3_config.json','pa_config.json'):
        c = json.loads((runtime / name).read_text())
        if (c['bot_control']['dry_run_mode'] if name == 'config.json' else c['dry_run_mode']) is not True:
            raise ValueError('Customer distribution currently supports paper execution only')


def main():
    prepare()
    role = sys.argv[1] if len(sys.argv) == 2 else ''
    if role in ('bot','dashboard'):
        from deployment_security import dashboard_secret
        if len(dashboard_secret()) < 16:
            raise ValueError('Configure a dashboard secret of at least 16 characters')
    if role == 'bot':
        import lbank_bot
        lbank_bot.run()
    elif role == 'dashboard':
        import uvicorn
        uvicorn.run('dashboard_server:app', host='0.0.0.0', port=8000, proxy_headers=False)
    elif role == 'candles':
        import lbank_candles
        lbank_candles.main([])
    elif role == 'funding':
        import fetch_funding
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):signal.signal(sig, lambda *_:stop.set())
        while not stop.is_set():
            for env in ('BOT_CONFIG','C3_CONFIG','PA_CONFIG'):
                if stop.is_set():break
                fetch_funding.main(os.environ[env])
            stop.wait(3600)
    else:
        raise ValueError('Service must be bot, dashboard, candles or funding')


if __name__ == '__main__':main()
