"""C3 sleeve: 4h trend-pullback strategy on 10 coins, run next to the main bot. PAPER ONLY.

Research: high_cagr/ideas/mtf_search.py (4h PULL, exit TRAILW, filter NOWKND), cross-universe and holdout checks in
high_cagr/output/ideas/xuni.json and holdout_test.json, coin choice in c3_per_coin.csv, portfolio in c3_combo.json.

Rules, on CLOSED 4h candles (same definitions as the backtest):
  long  : EMA50 > EMA200 and RSI14 crosses up through 40 (prev <= 40 < now)
  short : EMA50 < EMA200 and RSI14 crosses down through 60 (prev >= 60 > now)
  no new entry when the signal candle closes on Saturday or Sunday (UTC)
  entry at the current price, initial stop = entry -/+ 2 x ATR14 of the signal candle; skip stops < 0.4% of price
  trail: at every later closed candle, best close -/+ 4.5 x ATR14 of that candle; the stop only ratchets
  exit when the price touches the stop. One position per coin; own DB and config.
Runs inside the main bot (lbank_bot.run starts it in its own thread; C3_IN_BOT=0 turns that off) or alone with
`python c3_sleeve.py`. Inside the bot it sizes on the shared paper account: one seed + both realized P&Ls + both net unrealized P&Ls.
Sizing: risk_per_trade_pct of that equity / (stop distance + round-trip fee + slippage allowance),
notional capped at max_notional_pct of equity.
"""
from __future__ import annotations
import json,math,os,sqlite3,sys,time,logging,argparse,contextlib
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lbank_bot as bot

LOG=logging.getLogger('c3_sleeve');H4=4*3600
DEFAULTS=dict(enabled=True,dry_run_mode=True,timeframe='4h',paper_capital=10000.,risk_per_trade_pct=.0025,max_notional_pct=.4,max_open_positions=0,
    round_trip_fee=.0012,sizing_slippage_pct=.0004,isolated_leverage=5,ema_fast=50,ema_slow=200,rsi_period=14,rsi_long=40.,rsi_short=60.,atr_period=14,
    stop_atr=2.,trail_atr=4.5,min_stop_pct=.004,skip_weekend=True,candle_fetch_limit=1000,check_interval_seconds=15,confirm_bars=0,symbols=[])

def validate(c:dict)->dict:
    c={**DEFAULTS,**c}
    if set(c)!=set(DEFAULTS):raise ValueError(f'Unknown C3 keys: {sorted(set(c)-set(DEFAULTS))}')
    if c['dry_run_mode'] is not True:raise ValueError('C3 sleeve is paper-only: dry_run_mode must be true')
    if type(c['isolated_leverage']) is not int or not 1<=c['isolated_leverage']<=5:raise ValueError('isolated_leverage must be an integer 1..5')
    if type(c['max_open_positions']) is not int or not 0<=c['max_open_positions']<=100:raise ValueError('max_open_positions must be an integer 0..100; 0 disables the count cap')
    if c['timeframe']!='4h':raise ValueError('C3 was researched on 4h only')
    if not (0<c['risk_per_trade_pct']<=.01 and 0<c['max_notional_pct']<=1 and c['stop_atr']>0 and c['trail_atr']>0):raise ValueError('Invalid C3 risk settings')
    if not (type(c['confirm_bars']) is int and 0<=c['confirm_bars']<=12):raise ValueError('confirm_bars must be an int 0..12')
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

def weekday_close(ts_ms:int)->bool:return pd.Timestamp(int(ts_ms)+H4*1000,unit='ms').weekday()<5

def confirm_step(pending:list,close:float,trend:int,bar_ts:int,new_side:str|None,window:int)->tuple[str|None,list]:
    """Variant D (agent 1, high_cagr/ideas/c3_a1_followthrough.py): a PULL signal becomes an entry only when a LATER
    closed candle, within `window` candles, closes beyond the signal candle's close; it is dropped as soon as EMA50 vs
    EMA200 no longer agrees. trend = +1 (EMA50 > EMA200), -1 (<), 0 (equal). Pure function, shared with the tests."""
    hit=set();keep=[]
    for p in pending:
        sign=1 if p['side']=='long' else -1
        if trend!=sign:continue
        if sign*(close-p['level'])>0:hit.add(p['side']);continue
        if bar_ts<p['deadline']:keep.append(p)
    if new_side:keep.append(dict(side=new_side,level=float(close),deadline=int(bar_ts)+window*H4*1000))
    return ('long' if 'long' in hit else 'short' if 'short' in hit else None),keep

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
            db.execute('CREATE TABLE IF NOT EXISTS pending(symbol TEXT PRIMARY KEY,data TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS position_margin(symbol TEXT PRIMARY KEY,opened REAL,isolated_leverage INTEGER NOT NULL)')
    def db(self):return sqlite3.connect(self.path,timeout=30)
    def positions(self)->list[dict]:
        with self.db() as db:
            db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute('SELECT p.*,COALESCE(m.isolated_leverage,5) AS isolated_leverage FROM positions p LEFT JOIN position_margin m ON p.symbol=m.symbol AND p.opened=m.opened')]
    def realized(self)->float:
        with self.db() as db:return float(db.execute('SELECT COALESCE(SUM(pnl),0) FROM trades').fetchone()[0])

class Sleeve:
    def __init__(self,config:dict,store:Store,data,base_equity=None,shared_account=None):
        self.c=validate(config);self.store=store;self.data=data;self.base_equity=base_equity;self._shared_account=shared_account
    @property
    def shared_account(self):
        return self._shared_account() if callable(self._shared_account) else self._shared_account

    def equity(self)->float:
        if self.shared_account is not None:return self.shared_account.equity()
        base=self.base_equity() if self.base_equity else self.c['paper_capital']
        return base+self.store.realized()

    def execution_lock(self):
        return bot.file_lock(self.shared_account.lock_path) if self.shared_account is not None else bot.file_lock(self.store.path.with_suffix('.trade.lock'))

    def close(self,p:dict,price:float,reason:str,now:float):
        with self.execution_lock():return self._close(p,price,reason,now)

    def _close(self,p:dict,price:float,reason:str,now:float):
        sign=1 if p['side']=='long' else -1;pnl=sign*(price-p['entry'])*p['qty']-(p['entry']+price)*p['qty']*self.c['round_trip_fee']/2
        with self.store.db() as db:
            if not db.execute('DELETE FROM positions WHERE symbol=? AND opened=?',(p['symbol'],p['opened'])).rowcount:return 0.0
            else:
                db.execute('DELETE FROM position_margin WHERE symbol=? AND opened=?',(p['symbol'],p['opened']))
                db.execute('INSERT INTO trades(symbol,side,entry,exit,qty,opened,closed,pnl,reason) VALUES(?,?,?,?,?,?,?,?,?)',(p['symbol'],p['side'],p['entry'],price,p['qty'],p['opened'],now,pnl,reason))
        LOG.info('C3 close %s %s at %.6g pnl %.2f (%s)',p['symbol'],p['side'],price,pnl,reason);return pnl

    def close_all(self,reason:str='manual',now:float|None=None)->list[dict]:
        now=now or time.time();out=[]
        for p in self.store.positions():
            try:out.append(dict(symbol=p['symbol'],result='closed',pnl=self.close(p,self.data.price(p['symbol']),reason,now)))
            except Exception as exc:LOG.exception('C3 close failed for %s',p['symbol']);out.append(dict(symbol=p['symbol'],result='error',error=str(exc)))
        return out

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
                        with self.execution_lock(), self.store.db() as db:
                            ratchet='MAX' if sign==1 else 'MIN'
                            db.execute(f'UPDATE positions SET best={ratchet}(best,?),stop={ratchet}(stop,?),last_bar_ts=? WHERE symbol=? AND opened=? AND last_bar_ts<?',(best,stop,stamp,s,pos['opened'],stamp))
                side=signal(df,c)
                if c['confirm_bars']>0:   # variant D: track signals (also while a position is open) and wait for confirmation
                    with self.store.db() as db:row=db.execute('SELECT data FROM pending WHERE symbol=?',(s,)).fetchone()
                    trend=int(np.sign(b.ema_f-b.ema_s))
                    side,pend=confirm_step(json.loads(row[0]) if row else [],float(b.close),trend,stamp,side,c['confirm_bars'])
                    if side and c['skip_weekend'] and not weekday_close(stamp):side=None
                    with self.store.db() as db:db.execute('INSERT INTO pending VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET data=excluded.data',(s,json.dumps(pend)))
                if not pos and c['enabled'] and side:self.open(s,side,b,now)
                with self.store.db() as db:db.execute('INSERT INTO scanned VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET candle_ts=excluded.candle_ts',(s,stamp))
            except Exception:
                ok=False;LOG.exception('C3 scan failed for %s',s)
        self.watchdog(now);return ok

    def open(self,s:str,side:str,b:pd.Series,now:float):
        with self.execution_lock():return self._open(s,side,b,now)

    def _open(self,s:str,side:str,b:pd.Series,now:float):
        positions=self.store.positions()
        limit=self.c['max_open_positions']
        if (limit>0 and len(positions)>=limit) or any(p['symbol']==s for p in positions):return None
        c=self.c;sign=1 if side=='long' else -1;price=self.data.price(s);stop=price-sign*c['stop_atr']*b.atr;dist=sign*(price-stop)
        if dist<=0 or dist/price<c['min_stop_pct']:return None
        eq=self.equity()
        if eq<=0:return None
        notional=c['risk_per_trade_pct']*eq/(dist/price+c['round_trip_fee']+c['sizing_slippage_pct'])
        account=self.shared_account
        pooled=account is not None and account.engine.config.read()['portfolio_risk']['margin_allocation_mode']=='SHARED_POOL'
        if not pooled:notional=min(notional,c['max_notional_pct']*eq)
        if self.shared_account is not None:
            conf=self.shared_account.engine.config.read()
            if not conf['portfolio_risk']['shared_c3_account']:return None
            notional=min(notional,self.shared_account.available_margin(eq,leverage=c['isolated_leverage'],fee_rate=c['round_trip_fee'])*c['isolated_leverage'])
        cs=float(self.data.market(s).get('contractSize') or 1);qty=self.data.precision(s,notional/price/cs)*cs
        if qty<=0 or not self.data.tradable(s,qty/cs,price):return None
        with self.store.db() as db:
            db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(s,side,price,qty,stop,float(b.close),now,int(b.timestamp),int(b.timestamp),qty*dist))
            db.execute('INSERT OR REPLACE INTO position_margin VALUES(?,?,?)',(s,now,c['isolated_leverage']))
        LOG.info('C3 open %s %s at %.6g stop %.6g qty %.6g',s,side,price,stop,qty);return True

def load(path:Path)->dict:return validate(json.loads(path.read_text()))

def write_config(path:Path,c:dict)->dict:
    """Validate (paper-only, ranges, unknown keys) then replace the file atomically; the running sleeve reloads it within seconds."""
    import tempfile
    v=validate(c);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as h:
        h.write(json.dumps(v,ensure_ascii=False,indent=2)+'\n');h.flush();os.fsync(h.fileno());tmp=Path(h.name)
    os.replace(tmp,path);return v

def summary(store:Store,conf:dict,price,base_equity:float,net_costs:bool=False)->dict:
    """Dashboard view: open positions with live P&L, realized totals, equity of the shared paper account."""
    pos=[];unreal=0.;errors=[]
    for p in store.positions():
        sign=1 if p['side']=='long' else -1;px=None;pnl=None;r=None
        try:
            px=price(p['symbol']);pnl=sign*(px-p['entry'])*p['qty']
            if net_costs:pnl-=(px+p['entry'])*p['qty']*conf['round_trip_fee']/2
            unreal+=pnl;r=pnl/p['risk_usd'] if p['risk_usd'] else None
        except Exception as exc:errors.append(dict(symbol=p['symbol'],error=str(exc)))
        pos.append(dict(p,live_price=px,unrealized_pnl_usd=pnl,current_r=r))
    with store.db() as db:
        n,wins,realized=db.execute('SELECT COUNT(*),COALESCE(SUM(pnl>0),0),COALESCE(SUM(pnl),0) FROM trades').fetchone()
        day=db.execute('SELECT COALESCE(SUM(pnl),0),COUNT(*) FROM trades WHERE closed>=?',(time.time()-86400,)).fetchone()
        recent=[dict(zip(('symbol','side','entry','exit','pnl','reason','closed'),r)) for r in db.execute('SELECT symbol,side,entry,exit,pnl,reason,closed FROM trades ORDER BY id DESC LIMIT 20')]
    return dict(enabled=conf['enabled'],risk_per_trade_pct=conf['risk_per_trade_pct'],confirm_bars=conf['confirm_bars'],coins=len(conf['symbols']),
        max_open_positions=conf['max_open_positions'],open_positions_count=len(pos),notional_usd=float(sum(p['qty']*p['entry'] for p in pos)),engaged_margin_usd=float(sum(p['qty']*p['entry']/p['isolated_leverage'] for p in pos)),positions=pos,price_errors=errors,unrealized_pnl_usd=None if errors else unreal,realized_total_usd=float(realized),
        trades_total=int(n),win_rate_pct=float(wins/n*100) if n else None,daily_realized_pnl=float(day[0]),daily_trades_count=int(day[1]),recent_trades=recent,
        equity_usd=None if errors else base_equity+float(realized)+unreal)

OLD_DEFAULT_RISK=.0015   # shipped default before the risk sweep; runtime copies still holding it are upgraded

def prepare_config(path:Path,shipped:Path)->Path:
    """Seed the runtime config from the shipped one; add keys it lacks and upgrade an untouched old default risk."""
    ship=json.loads(shipped.read_text())
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(shipped.read_text());return path
    cur=json.loads(path.read_text());new={**{k:v for k,v in ship.items() if k not in cur},**cur}
    if cur.get('risk_per_trade_pct') in (OLD_DEFAULT_RISK,.002):new['risk_per_trade_pct']=ship['risk_per_trade_pct']
    if new!=cur:
        LOG.info('C3 runtime config upgraded: %s',{k:new[k] for k in new if cur.get(k)!=new[k]});path.write_text(json.dumps(new,indent=2))
    return path

def paths()->tuple[Path,Store]:
    here=Path(__file__).resolve().parent;cfg=Path(os.getenv('C3_CONFIG',here/'c3_config.json'))
    if cfg.resolve()!=(here/'c3_config.json').resolve():prepare_config(cfg,here/'c3_config.json')
    return cfg,Store(Path(os.getenv('C3_DB',here/'data/c3_sleeve.db')))

def loop(sl:Sleeve,cfg:Path,stop=None,once=False):
    """Scan each closed 4h candle once, run the stop watchdog in between; stop = threading.Event (or None)."""
    last=None
    while not (stop and stop.is_set()):
        try:
            try:sl.c=load(cfg)   # dashboard edits apply within one cycle; an invalid file keeps the previous settings
            except Exception:LOG.exception('C3 config unreadable; keeping previous settings')
            now=time.time();boundary=int(now)//H4*H4
            if now>=boundary+3 and boundary!=last:
                if sl.scan(now):last=boundary
            else:sl.watchdog(now)
        except Exception:LOG.exception('C3 cycle failed; will retry')
        if once:break
        (stop.wait if stop else time.sleep)(sl.c['check_interval_seconds'])

def start_in_bot(engine,stop):
    """Called by lbank_bot.run(): C3 in its own thread, own market-data client, sized on the bot's paper equity."""
    import threading
    if os.getenv('C3_IN_BOT','1')=='0':LOG.info('C3 disabled in the bot (C3_IN_BOT=0)');return None
    cfg,store=paths();sl=Sleeve(load(cfg),store,bot.MarketData(),base_equity=engine.main_paper_equity,shared_account=engine.shared_paper_account)
    t=threading.Thread(target=loop,args=(sl,cfg,stop),name='c3-sleeve',daemon=True);t.start()
    LOG.info('C3 sleeve started inside the bot: %d coins, risk %.2f%%/trade, confirm_bars %d',len(sl.c['symbols']),sl.c['risk_per_trade_pct']*100,sl.c['confirm_bars'])
    return t

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--once',action='store_true');a=ap.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    cfg,store=paths();data=bot.MarketData();engine=bot.Engine(bot.ConfigStore(),bot.Database(),data)
    loop(Sleeve(load(cfg),store,data,base_equity=engine.main_paper_equity,shared_account=engine.shared_paper_account),cfg,once=a.once)

if __name__=='__main__':main()
