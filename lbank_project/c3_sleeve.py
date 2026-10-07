"""C3 sleeve: 4h trend-pullback strategy on 10 coins, run next to the main bot. PAPER ONLY.

Research: high_cagr/ideas/mtf_search.py (4h PULL, exit TRAILW, filter NOWKND), cross-universe and holdout checks in
high_cagr/output/ideas/xuni.json and holdout_test.json, coin choice in c3_per_coin.csv, portfolio in c3_combo.json.

Rules, on CLOSED 4h candles (same definitions as the backtest):
  long  : EMA50 > EMA200 and RSI14 crosses up through 40 (prev <= 40 < now)
  short : EMA50 < EMA200 and RSI14 crosses down through 60 (prev >= 60 > now)
  no new entry when the signal candle closes on Saturday or Sunday (UTC)
  entry at the current price, initial stop = entry -/+ 2 x ATR14 of the signal candle; skip stops < 0.4% of price
  trail: at every later closed candle, best close -/+ 4.5 x ATR14 of that candle; the stop only ratchets
  exit when the price touches the stop. One position per coin; separate equity, DB and config from the main bot.
Sizing: risk_per_trade_pct of the sleeve's paper equity / (stop distance + round-trip fee + slippage allowance),
notional capped at max_notional_pct of equity.
"""
from __future__ import annotations
import json,math,os,sqlite3,sys,time,logging,argparse
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lbank_bot as bot

LOG=logging.getLogger('c3_sleeve');H4=4*3600
DEFAULTS=dict(enabled=True,dry_run_mode=True,timeframe='4h',paper_capital=10000.,risk_per_trade_pct=.0025,max_notional_pct=.4,
    round_trip_fee=.0012,sizing_slippage_pct=.0004,ema_fast=50,ema_slow=200,rsi_period=14,rsi_long=40.,rsi_short=60.,atr_period=14,
    stop_atr=2.,trail_atr=4.5,min_stop_pct=.004,skip_weekend=True,candle_fetch_limit=1000,check_interval_seconds=15,symbols=[])

def validate(c:dict)->dict:
    c={**DEFAULTS,**c}
    if set(c)!=set(DEFAULTS):raise ValueError(f'Unknown C3 keys: {sorted(set(c)-set(DEFAULTS))}')
    if c['dry_run_mode'] is not True:raise ValueError('C3 sleeve is paper-only: dry_run_mode must be true')
    if c['timeframe']!='4h':raise ValueError('C3 was researched on 4h only')
    if not (0<c['risk_per_trade_pct']<=.01 and 0<c['max_notional_pct']<=1 and c['stop_atr']>0 and c['trail_atr']>0):raise ValueError('Invalid C3 risk settings')
    if c['candle_fetch_limit']<c['ema_slow']*3:raise ValueError('candle_fetch_limit too small for the EMA warm-up')
    if not c['symbols'] or len(set(c['symbols']))!=len(c['symbols']):raise ValueError('C3 needs a list of distinct symbols')
    return c

def features(rows:list,now:float,c:dict)->pd.DataFrame:
    """Closed candles only (the exchange's last, forming candle is dropped), with EMA/RSI/ATR as in the backtest."""
    df=pd.DataFrame(rows,columns=['timestamp','open','high','low','close','volume']).astype(float).iloc[:-1]
    df=df[df.timestamp+H4*1000<=now*1000].reset_index(drop=True)
    if len(df)<c['ema_slow']+5:raise ValueError('Not enough closed candles')
    if (np.diff(df.timestamp.to_numpy())!=H4*1000).any():raise ValueError('Gaps in candle history')
    cl=df.close
    df['ema_f']=cl.ewm(span=c['ema_fast'],adjust=False).mean();df['ema_s']=cl.ewm(span=c['ema_slow'],adjust=False).mean()
    d=cl.diff().fillna(0.);g=d.clip(lower=0).ewm(alpha=1/c['rsi_period'],adjust=False).mean();l=(-d.clip(upper=0)).ewm(alpha=1/c['rsi_period'],adjust=False).mean()
    df['rsi']=100-100/(1+g/l.where(l!=0,1e-12))
    tr=pd.concat([df.high-df.low,(df.high-cl.shift()).abs(),(df.low-cl.shift()).abs()],axis=1).max(axis=1)
    df['atr']=tr.ewm(alpha=1/c['atr_period'],adjust=False).mean();return df

def signal(df:pd.DataFrame,c:dict)->str|None:
    b,p=df.iloc[-1],df.iloc[-2]
    if c['skip_weekend'] and pd.Timestamp(int(b.timestamp)+H4*1000,unit='ms').weekday()>=5:return None
    if b.ema_f>b.ema_s and p.rsi<=c['rsi_long']<b.rsi:return 'long'
    if b.ema_f<b.ema_s and p.rsi>=c['rsi_short']>b.rsi:return 'short'
    return None

class Store:
    def __init__(self,path:Path):
        self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,side TEXT,entry REAL,qty REAL,stop REAL,best REAL,opened REAL,signal_ts INTEGER,last_bar_ts INTEGER,risk_usd REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,entry REAL,exit REAL,qty REAL,opened REAL,closed REAL,pnl REAL,reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS scanned(symbol TEXT PRIMARY KEY,candle_ts INTEGER)')
    def db(self):return sqlite3.connect(self.path,timeout=30)
    def positions(self)->list[dict]:
        with self.db() as db:
            db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute('SELECT * FROM positions')]
    def realized(self)->float:
        with self.db() as db:return float(db.execute('SELECT COALESCE(SUM(pnl),0) FROM trades').fetchone()[0])

class Sleeve:
    def __init__(self,config:dict,store:Store,data):
        self.c=validate(config);self.store=store;self.data=data
    def equity(self)->float:return self.c['paper_capital']+self.store.realized()

    def close(self,p:dict,price:float,reason:str,now:float):
        sign=1 if p['side']=='long' else -1;pnl=sign*(price-p['entry'])*p['qty']-(p['entry']+price)*p['qty']*self.c['round_trip_fee']/2
        with self.store.db() as db:
            if db.execute('DELETE FROM positions WHERE symbol=?',(p['symbol'],)).rowcount:
                db.execute('INSERT INTO trades(symbol,side,entry,exit,qty,opened,closed,pnl,reason) VALUES(?,?,?,?,?,?,?,?,?)',(p['symbol'],p['side'],p['entry'],price,p['qty'],p['opened'],now,pnl,reason))
        LOG.info('C3 close %s %s at %.6g pnl %.2f (%s)',p['symbol'],p['side'],price,pnl,reason);return pnl

    def watchdog(self,now:float|None=None):
        now=now or time.time()
        for p in self.store.positions():
            try:
                price=self.data.price(p['symbol']);sign=1 if p['side']=='long' else -1
                if sign*(price-p['stop'])<=0:self.close(p,price,'stop',now)
            except Exception:LOG.exception('C3 watchdog failed for %s',p['symbol'])

    def scan(self,now:float|None=None)->bool:
        now=now or time.time();ok=True;c=self.c
        for s in c['symbols']:
            try:
                df=features(self.data.candles(s,c['timeframe'],c['candle_fetch_limit']),now,c);b=df.iloc[-1];stamp=int(b.timestamp)
                with self.store.db() as db:
                    prev=db.execute('SELECT candle_ts FROM scanned WHERE symbol=?',(s,)).fetchone()
                if prev and stamp<=prev[0]:continue
                pos={p['symbol']:p for p in self.store.positions()}.get(s)
                if pos:   # trail on every closed candle after the signal candle
                    if stamp>pos['last_bar_ts']:
                        sign=1 if pos['side']=='long' else -1;best=max(pos['best'],b.close) if sign==1 else min(pos['best'],b.close)
                        new=best-sign*c['trail_atr']*b.atr;stop=max(pos['stop'],new) if sign==1 else min(pos['stop'],new)
                        with self.store.db() as db:db.execute('UPDATE positions SET best=?,stop=?,last_bar_ts=? WHERE symbol=?',(best,stop,stamp,s))
                elif c['enabled']:
                    side=signal(df,c)
                    if side:self.open(s,side,b,now)
                with self.store.db() as db:db.execute('INSERT INTO scanned VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET candle_ts=excluded.candle_ts',(s,stamp))
            except Exception:
                ok=False;LOG.exception('C3 scan failed for %s',s)
        self.watchdog(now);return ok

    def open(self,s:str,side:str,b:pd.Series,now:float):
        c=self.c;sign=1 if side=='long' else -1;price=self.data.price(s);stop=price-sign*c['stop_atr']*b.atr;dist=sign*(price-stop)
        if dist<=0 or dist/price<c['min_stop_pct']:return None
        eq=self.equity()
        if eq<=0:return None
        notional=min(c['risk_per_trade_pct']*eq/(dist/price+c['round_trip_fee']+c['sizing_slippage_pct']),c['max_notional_pct']*eq)
        cs=float(self.data.market(s).get('contractSize') or 1);qty=self.data.precision(s,notional/price/cs)*cs
        if qty<=0 or not self.data.tradable(s,qty/cs,price):return None
        with self.store.db() as db:
            db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(s,side,price,qty,stop,float(b.close),now,int(b.timestamp),int(b.timestamp),qty*dist))
        LOG.info('C3 open %s %s at %.6g stop %.6g qty %.6g',s,side,price,stop,qty);return True

def load(path:Path)->dict:return validate(json.loads(path.read_text()))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--once',action='store_true');a=ap.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    here=Path(__file__).resolve().parent;cfg=Path(os.getenv('C3_CONFIG',here/'c3_config.json'));store=Store(Path(os.getenv('C3_DB',here/'data/c3_sleeve.db')))
    if not cfg.exists() and (here/'c3_config.json').exists():   # first run in Docker: seed runtime config like the main bot
        cfg.parent.mkdir(parents=True,exist_ok=True);cfg.write_text((here/'c3_config.json').read_text())
    sl=Sleeve(load(cfg),store,bot.MarketData());last=None
    while True:
        now=time.time();boundary=int(now)//H4*H4
        if now>=boundary+3 and boundary!=last:
            sl.c=load(cfg)
            if sl.scan(now):last=boundary
        else:sl.watchdog(now)
        if a.once:break
        time.sleep(sl.c['check_interval_seconds'])

if __name__=='__main__':main()
