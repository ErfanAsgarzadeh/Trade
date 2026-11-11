"""Local strategy-setup outbox. Publishing never inserts an order or position."""
import json
import math
import os
from pathlib import Path
import sqlite3
import time

import license_access


def enabled(now=None):
    return os.getenv('BOT_SIGNAL_FEED_ENABLED','0')=='1' and license_access.signals_allowed(now)


def path():
    return Path(os.getenv('BOT_SIGNAL_FEED_DB',str(Path(os.getenv('BOT_DB','runtime/lbank_ichimoku_bot.db')).parent/'signal_feed.db')))


def publish(bot,symbol,side,entry,stop,candle_ts,timeframe,expires_at,now=None,target=None,source_mode=None):
    now=time.time() if now is None else now
    if not enabled(now) or source_mode!='csv-lbank':return False
    entry,stop=float(entry),float(stop)
    seconds={'1m':60,'5m':300,'15m':900,'30m':1800,'1h':3600,'4h':14400,'1d':86400}.get(timeframe)
    if bot not in ('main','c3','pa') or side not in ('long','short') or seconds is None:raise ValueError('Invalid signal')
    if not all(math.isfinite(v) for v in (entry,stop,float(candle_ts),float(expires_at),float(now))) or min(entry,stop)<=0:
        raise ValueError('Invalid signal levels')
    if (entry-stop)*(1 if side=='long' else -1)<=0:raise ValueError('Invalid stop direction')
    if candle_ts+seconds*1000>now*1000 or expires_at<=now:return False
    if target is not None and (not math.isfinite(float(target)) or (float(target)-entry)*(1 if side=='long' else -1)<=0):raise ValueError('Invalid target')
    document=dict(bot=bot,symbol=symbol,side=side,entry=entry,stop=stop,target=target,
                  candle_ts=int(candle_ts),timeframe=timeframe,published_at=now,expires_at=expires_at,
                  kind='strategy_setup',execution='not_executed',source_mode=source_mode)
    destination=path();destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(destination,timeout=5) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS signal_feed(id INTEGER PRIMARY KEY,bot TEXT,symbol TEXT,side TEXT,candle_ts INTEGER,timeframe TEXT,published REAL,document TEXT,UNIQUE(bot,symbol,side,candle_ts,timeframe))')
        cursor=db.execute('INSERT OR IGNORE INTO signal_feed(bot,symbol,side,candle_ts,timeframe,published,document) VALUES(?,?,?,?,?,?,?)',
                          (bot,symbol,side,int(candle_ts),timeframe,now,json.dumps(document,allow_nan=False)))
        db.execute('DELETE FROM signal_feed WHERE published<?',(now-90*86400,))
    destination.chmod(0o600)
    return cursor.rowcount==1


def read_feed(filename,limit=100,now=None):
    now=time.time() if now is None else now
    file=Path(filename) if filename else None
    if file is None or not file.is_file():return dict(status='not_configured',signals=[])
    try:
        with sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            rows=db.execute('SELECT document FROM signal_feed ORDER BY published DESC,id DESC LIMIT ?', (min(100,max(1,limit)),)).fetchall()
        signals=[]
        for (document,) in rows:
            item=json.loads(document);item['status']='active' if item['expires_at']>now else 'expired';signals.append(item)
        return dict(status='ready',signals=signals)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):return dict(status='unavailable',signals=[])
