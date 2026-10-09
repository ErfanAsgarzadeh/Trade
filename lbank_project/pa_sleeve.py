"""Ghoghnous (ققنوس, the PA sleeve): third bot, 4h price-action KEY REVERSAL on 20 other coins, run next to Shahin (main
bot) and Mojsavar (C3). PAPER ONLY.

Research: high_cagr/ideas/pa_bot.py (pre-declared test of 19 price-action entries x 1h/4h x 3 exits x 2 filters = 228
configs); result in high_cagr/output/ideas/pa_bot/. 4h KEYREV with a 2R target was the only config passing all gates.

Rules, on CLOSED 4h candles (same definitions as the backtest):
  long  signal: outside bar (high > previous high and low < previous low) whose low is the lowest of the last 11
        candles, close > previous close and close in the top 25% of the bar's range
  short signal: the exact mirror (highest high of 11 candles, close < previous close, close in the bottom 25%)
  entry : buy-stop at the signal high (sell-stop at the signal low), valid until the NEXT 4h candle closes; the order
          is cancelled when the price reaches the stop level first
  stop  : signal low - 0.1 x ATR14 (signal high + 0.1 x ATR14 for shorts); skip stops < 0.4% of the fill price
  filter: skip signal candles whose range is < 1.1 x ATR14 (min_range_atr), and (C2) trade only in a LOW-VOLATILITY
          regime: volrank < 0.354, volrank = share of the previous 500 4h candles whose ATR14/close is below the signal
          candle's (vol_rank_max / vol_rank_window; 1.0 turns the gate off)
  exit  : the stop, or at the close of the 30th 4h candle after entry (time stop), or (C2) at the close of a candle that
          prints an opposite key reversal (opposite_exit; the raw signal, before the volatility gate); no target
          (target_r=0; a positive target_r restores the original 2R target)
Defaults = variant C2 of the second 12-agent meeting (high_cagr/ideas/pa2_final.py, winner F3_vol_opp), risk 0.4%.
History: C1 (pa_opt_combo.py, 0.25%) -> C2.
One position per coin; own DB and config. Runs inside the main bot (lbank_bot.run starts it in its own thread;
PA_IN_BOT=0 turns that off). Sizing as C3: risk_per_trade_pct of the shared paper equity / (stop distance + round-trip
fee + slippage allowance), notional capped at max_notional_pct of equity (PER_SLOT) or by the shared free margin.
"""
from __future__ import annotations
import json,os,sys,time,logging,argparse
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lbank_bot as bot
import c3_sleeve as c3

LOG=logging.getLogger('pa_sleeve');H4=c3.H4;NAME='Ghoghnous';OLD_RISK=.0015   # first shipped defaults: 2R target, no range filter, 0.15%
C1_RISK=.0025;OLD_FETCH=300   # C1 defaults (upgraded to C2 when untouched)
DEFAULTS=dict(enabled=True,dry_run_mode=True,timeframe='4h',paper_capital=10000.,risk_per_trade_pct=.004,max_notional_pct=1.,max_open_positions=0,
    round_trip_fee=.0012,sizing_slippage_pct=.0004,isolated_leverage=5,atr_period=14,lookback=10,close_frac=.75,stop_buffer_atr=.1,
    target_r=0.,min_range_atr=1.1,vol_rank_max=.354,vol_rank_window=500,opposite_exit=True,time_stop_bars=30,min_stop_pct=.004,
    candle_fetch_limit=800,check_interval_seconds=15,max_gap_bars=3,symbols=[])

def validate(c:dict)->dict:
    c={**DEFAULTS,**c}
    if set(c)!=set(DEFAULTS):raise ValueError(f'Unknown PA keys: {sorted(set(c)-set(DEFAULTS))}')
    if c['dry_run_mode'] is not True:raise ValueError('PA sleeve is paper-only: dry_run_mode must be true')
    if c['timeframe']!='4h':raise ValueError('PA was researched on 4h only')
    if type(c['isolated_leverage']) is not int or not 1<=c['isolated_leverage']<=5:raise ValueError('isolated_leverage must be an integer 1..5')
    if type(c['max_open_positions']) is not int or not 0<=c['max_open_positions']<=100:raise ValueError('max_open_positions must be an integer 0..100; 0 disables the count cap')
    if not (0<c['risk_per_trade_pct']<=.01 and 0<c['max_notional_pct']<=1 and c['target_r']>=0 and c['stop_buffer_atr']>=0 and 0<=c['min_range_atr']<=5):raise ValueError('Invalid PA risk settings')
    if not (type(c['time_stop_bars']) is int and 1<=c['time_stop_bars']<=500):raise ValueError('time_stop_bars must be an int 1..500')
    if not (type(c['lookback']) is int and 2<=c['lookback']<=100 and 0<c['close_frac']<1):raise ValueError('Invalid PA signal settings')
    if not (0<c['vol_rank_max']<=1 and type(c['vol_rank_window']) is int and 50<=c['vol_rank_window']<=2000 and type(c['opposite_exit']) is bool):raise ValueError('Invalid PA volatility/exit settings')
    if not (type(c['max_gap_bars']) is int and 0<=c['max_gap_bars']<=12):raise ValueError('max_gap_bars must be an int 0..12')
    need=max(100,c['lookback']+10*c['atr_period'])+(c['vol_rank_window']+1 if c['vol_rank_max']<1 else 0)
    if c['candle_fetch_limit']<need:raise ValueError(f'candle_fetch_limit too small for the ATR warm-up and the volatility window (need >= {need})')
    if not c['symbols'] or len(set(c['symbols']))!=len(c['symbols']):raise ValueError('PA needs a list of distinct symbols')
    return c

def features(rows:list,now:float,c:dict)->pd.DataFrame:
    """Closed 4h candles only, with Wilder ATR as in the backtest."""
    df=pd.DataFrame(rows,columns=['timestamp','open','high','low','close','volume']).astype(float).iloc[:-1]
    df=df[df.timestamp+H4*1000<=now*1000].reset_index(drop=True)
    if len(df)<c['lookback']+3*c['atr_period']:raise ValueError('Not enough closed candles')
    steps=np.diff(df.timestamp.to_numpy())//(H4*1000)
    if (steps<1).any() or (steps-1).max(initial=0)>c['max_gap_bars']:raise ValueError('Gaps in candle history')
    if (steps>1).any():   # short exchange gaps: flat candles at the previous close (as the minute data used in research)
        full=np.arange(df.timestamp.iloc[0],df.timestamp.iloc[-1]+1,H4*1000);df=df.set_index('timestamp').reindex(full)
        df['close']=df.close.ffill()
        for k in ('open','high','low'):df[k]=df[k].fillna(df.close)
        df['volume']=df.volume.fillna(0.);df=df.rename_axis('timestamp').reset_index()
    tr=pd.concat([df.high-df.low,(df.high-df.close.shift()).abs(),(df.low-df.close.shift()).abs()],axis=1).max(axis=1)
    df['atr']=tr.ewm(alpha=1/c['atr_period'],adjust=False).mean();return df

def vol_rank(df:pd.DataFrame,window:int)->float:
    """Share of the previous `window` candles whose ATR/close is below the last candle's (pa2_confluence.prank)."""
    x=(df.atr/df.close).to_numpy()
    if len(x)<window+1:return float('nan')
    prev=x[-window-1:-1];prev=prev[np.isfinite(prev)];return float((prev<x[-1]).mean()) if len(prev) else float('nan')

def tradable_signal(df:pd.DataFrame,c:dict)->tuple[dict|None,dict|None]:
    """(raw key-reversal signal, the same signal if it passes the volatility gate else None)."""
    sig=signal(df,c)
    if sig is None or c['vol_rank_max']>=1:return sig,sig
    vr=vol_rank(df,c['vol_rank_window']);return sig,(sig if vr==vr and vr<c['vol_rank_max'] else None)

def signal(df:pd.DataFrame,c:dict)->dict|None:
    """Key reversal on the last closed candle -> pending stop order {side, level, stop}; None if no signal."""
    h,l,cl=df.high.to_numpy(),df.low.to_numpy(),df.close.to_numpy();a=float(df.atr.iloc[-1]);n=c['lookback']
    if len(df)<n+2 or not a>0:return None
    rng=max(h[-1]-l[-1],1e-12);outside=h[-1]>h[-2] and l[-1]<l[-2]
    if c['min_range_atr']>0 and not rng>=c['min_range_atr']*a:return None   # skip small signal bars (high_cagr/ideas/pa_opt_combo.py)
    if outside and l[-1]<=l[-n-1:-1].min() and cl[-1]>cl[-2] and (cl[-1]-l[-1])/rng>=c['close_frac']:
        return dict(side='long',level=float(h[-1]),stop=float(l[-1]-c['stop_buffer_atr']*a))
    if outside and h[-1]>=h[-n-1:-1].max() and cl[-1]<cl[-2] and (h[-1]-cl[-1])/rng>=c['close_frac']:
        return dict(side='short',level=float(l[-1]),stop=float(h[-1]+c['stop_buffer_atr']*a))
    return None

def order_step(order:dict,price:float)->str:
    """'fill' when the price reached the entry level, 'cancel' when it reached the stop level first, else 'wait'."""
    sign=1 if order['side']=='long' else -1
    if sign*(price-order['level'])>=0:return 'fill'
    if sign*(price-order['stop'])<=0:return 'cancel'
    return 'wait'

class Store(c3.Store):
    """C3's position/trade schema (so the shared account and the dashboard read it the same way) + target/time stop."""
    def __init__(self,path:Path):
        super().__init__(path)
        with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS exits(symbol TEXT,opened REAL,target REAL,entry_bar_ts INTEGER,PRIMARY KEY(symbol,opened))')
    def positions(self)->list[dict]:
        out=super().positions()
        with self.db() as db:ex={(r[0],r[1]):(r[2],r[3]) for r in db.execute('SELECT symbol,opened,target,entry_bar_ts FROM exits')}
        for p in out:p['target'],p['entry_bar_ts']=ex.get((p['symbol'],p['opened']),(None,None))
        return out
    def orders(self)->dict:
        with self.db() as db:return {s:json.loads(d) for s,d in db.execute('SELECT symbol,data FROM pending')}
    def set_order(self,s:str,order:dict|None):
        with self.db() as db:
            if order is None:db.execute('DELETE FROM pending WHERE symbol=?',(s,))
            else:db.execute('INSERT INTO pending VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET data=excluded.data',(s,json.dumps(order)))

class Sleeve(c3.Sleeve):
    NAME=NAME;LOG=LOG
    def __init__(self,config:dict,store:Store,data,base_equity=None,shared_account=None):
        self.c=validate(config);self.store=store;self.data=data;self.base_equity=base_equity;self._shared_account=shared_account

    def _close(self,p:dict,price:float,reason:str,now:float):
        pnl=super()._close(p,price,reason,now)
        with self.store.db() as db:db.execute('DELETE FROM exits WHERE symbol=? AND opened=?',(p['symbol'],p['opened']))
        return pnl

    def close_all(self,reason:str='manual',now:float|None=None)->list[dict]:
        for s in self.store.orders():self.store.set_order(s,None)
        return super().close_all(reason,now)

    def watchdog(self,now:float|None=None):
        now=now or time.time()
        for p in self.store.positions():
            try:
                price=self.data.price(p['symbol']);sign=1 if p['side']=='long' else -1
                if sign*(price-p['stop'])<=0:self.close(p,price,'stop',now)
                elif p['target'] is not None and sign*(price-p['target'])>=0:self.close(p,price,'target',now)
            except Exception:LOG.exception('Ghoghnous watchdog failed for %s',p['symbol'])
        held={p['symbol'] for p in self.store.positions()}
        for s,o in self.store.orders().items():
            try:
                if s in held or now*1000>=o['expires']:self.store.set_order(s,None);continue
                step=order_step(o,self.data.price(s))
                if step=='cancel' or (step=='fill' and not self.c['enabled']):self.store.set_order(s,None)
                elif step=='fill':self.open(s,o,now);self.store.set_order(s,None)
            except Exception:LOG.exception('Ghoghnous order check failed for %s',s)

    def scan(self,now:float|None=None)->bool:
        now=now or time.time();ok=True;c=self.c
        for s in c['symbols']:
            try:
                df=features(self.data.candles(s,c['timeframe'],c['candle_fetch_limit']),now,c);b=df.iloc[-1];stamp=int(b.timestamp)
                if stamp<(int(now)//H4-1)*H4*1000:raise ValueError(f'stale candles for {s}: last closed {stamp}')   # retried, never skipped
                with self.store.db() as db:prev=db.execute('SELECT candle_ts FROM scanned WHERE symbol=?',(s,)).fetchone()
                if prev and stamp<=prev[0]:continue
                pos={p['symbol']:p for p in self.store.positions()}.get(s)
                if pos and pos['entry_bar_ts'] is not None and (stamp-pos['entry_bar_ts'])//(H4*1000)>=c['time_stop_bars']:
                    self.close(pos,self.data.price(s),'time',now);pos=None
                raw,sig=tradable_signal(df,c)
                if pos and c['opposite_exit'] and raw and raw['side']!=pos['side']:
                    self.close(pos,self.data.price(s),'opposite',now);pos=None
                if not pos and c['enabled'] and sig:   # valid until the next candle (stamp + 4h) has closed
                    self.store.set_order(s,dict(sig,signal_ts=stamp,expires=stamp+2*H4*1000,atr=float(b.atr)))
                with self.store.db() as db:db.execute('INSERT INTO scanned VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET candle_ts=excluded.candle_ts',(s,stamp))
            except Exception:
                ok=False;LOG.exception('Ghoghnous scan failed for %s',s)
        self.watchdog(now);return ok

    def open(self,s:str,order:dict,now:float):
        with self.execution_lock():return self._open(s,order,now)

    def _open(self,s:str,order:dict,now:float):
        positions=self.store.positions();limit=self.c['max_open_positions']
        if (limit>0 and len(positions)>=limit) or any(p['symbol']==s for p in positions):return None
        c=self.c;sign=1 if order['side']=='long' else -1;price=self.data.price(s);stop=order['stop'];dist=sign*(price-stop)
        if dist<=0 or dist/price<c['min_stop_pct']:return None
        eq=self.equity()
        if eq<=0:return None
        notional=c['risk_per_trade_pct']*eq/(dist/price+c['round_trip_fee']+c['sizing_slippage_pct'])
        account=self.shared_account
        if account is not None:
            conf=account.engine.config.read()
            if not conf['portfolio_risk']['shared_c3_account']:return None
            if conf['portfolio_risk']['margin_allocation_mode']!='SHARED_POOL':notional=min(notional,c['max_notional_pct']*eq)
            notional=min(notional,account.available_margin(eq,leverage=c['isolated_leverage'],fee_rate=c['round_trip_fee'])*c['isolated_leverage'])
        else:notional=min(notional,c['max_notional_pct']*eq)
        cs=float(self.data.market(s).get('contractSize') or 1);qty=self.data.precision(s,notional/price/cs)*cs
        if qty<=0 or not self.data.tradable(s,qty/cs,price):return None
        target=price+sign*c['target_r']*dist if c['target_r']>0 else None;entry_bar=int(now*1000)//(H4*1000)*(H4*1000)
        with self.store.db() as db:
            db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(s,order['side'],price,qty,stop,price,now,int(order['signal_ts']),int(order['signal_ts']),qty*dist))
            db.execute('INSERT OR REPLACE INTO position_margin VALUES(?,?,?)',(s,now,c['isolated_leverage']))
            db.execute('INSERT OR REPLACE INTO exits VALUES(?,?,?,?)',(s,now,target,entry_bar))
        LOG.info('Ghoghnous open %s %s at %.6g stop %.6g target %s qty %.6g',s,order['side'],price,stop,'none' if target is None else f'{target:.6g}',qty);return True

def load(path:Path)->dict:return validate(json.loads(path.read_text()))

def write_config(path:Path,c:dict)->dict:
    import tempfile
    v=validate(c);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as h:
        h.write(json.dumps(v,ensure_ascii=False,indent=2)+'\n');h.flush();os.fsync(h.fileno());tmp=Path(h.name)
    os.replace(tmp,path);return v

def summary(store:Store,conf:dict,price,base_equity:float,net_costs:bool=False)->dict:
    view=c3.summary(store,{**conf,'confirm_bars':0},price,base_equity,net_costs);view.pop('confirm_bars',None)
    view['pending_orders']=[dict(symbol=s,**o) for s,o in store.orders().items()];return view

def prepare_config(path:Path,shipped:Path)->Path:
    """Seed the runtime config from the shipped one; add keys it lacks (values you changed are kept)."""
    ship=json.loads(shipped.read_text())
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(shipped.read_text());return path
    cur=json.loads(path.read_text());new={**{k:v for k,v in ship.items() if k not in cur},**cur}
    if cur.get('target_r')==2. and cur.get('min_range_atr',0.)==0. and cur.get('risk_per_trade_pct')==OLD_RISK:
        new.update(target_r=ship['target_r'],min_range_atr=ship['min_range_atr'],risk_per_trade_pct=ship['risk_per_trade_pct'])   # untouched first defaults -> current
    elif 'vol_rank_max' not in cur and cur.get('risk_per_trade_pct')==C1_RISK:new['risk_per_trade_pct']=ship['risk_per_trade_pct']   # untouched C1 -> C2 risk
    if cur.get('candle_fetch_limit',OLD_FETCH)==OLD_FETCH:new['candle_fetch_limit']=ship['candle_fetch_limit']   # C2 needs 500+ candles
    if '1000SHIB/USDT:USDT' in new.get('symbols',[]):new['symbols']=['SHIB/USDT:USDT' if x=='1000SHIB/USDT:USDT' else x for x in new['symbols']]   # LBank lists SHIBUSDT
    if new!=cur:
        LOG.info('%s runtime config upgraded: %s',NAME,{k:new[k] for k in new if cur.get(k)!=new[k]});path.write_text(json.dumps(new,indent=2))
    return path

def paths()->tuple[Path,Store]:
    here=Path(__file__).resolve().parent;cfg=Path(os.getenv('PA_CONFIG',here/'pa_config.json'))
    if cfg.resolve()!=(here/'pa_config.json').resolve():prepare_config(cfg,here/'pa_config.json')
    return cfg,Store(Path(os.getenv('PA_DB',here/'data/pa_sleeve.db')))

def in_bot()->bool:return os.getenv('PA_IN_BOT','1')!='0'

def loop(sl:Sleeve,cfg:Path,stop=None,once=False):
    """Scan each closed 4h candle once; between scans the watchdog fills/cancels orders and checks stops/targets."""
    last=None
    while not (stop and stop.is_set()):
        try:
            try:sl.c=load(cfg)
            except Exception:LOG.exception('Ghoghnous config unreadable; keeping previous settings')
            now=time.time();boundary=int(now)//H4*H4
            if now>=boundary+3 and boundary!=last:
                if sl.scan(now):last=boundary
            else:sl.watchdog(now)
        except Exception:LOG.exception('Ghoghnous cycle failed; will retry')
        if once:break
        (stop.wait if stop else time.sleep)(sl.c['check_interval_seconds'])

def start_in_bot(engine,stop):
    import threading
    if not in_bot():LOG.info('Ghoghnous disabled in the bot (PA_IN_BOT=0)');return None
    cfg,store=paths();sl=Sleeve(load(cfg),store,bot.MarketData(),base_equity=engine.main_paper_equity,shared_account=engine.shared_paper_account)
    t=threading.Thread(target=loop,args=(sl,cfg,stop),name='pa-sleeve',daemon=True);t.start()
    LOG.info('Ghoghnous (PA) started inside the bot: %d coins, risk %.2f%%/trade',len(sl.c['symbols']),sl.c['risk_per_trade_pct']*100)
    return t

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--once',action='store_true');a=ap.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    cfg,store=paths();data=bot.MarketData();engine=bot.Engine(bot.ConfigStore(),bot.Database(),data)
    loop(Sleeve(load(cfg),store,data,base_equity=engine.main_paper_equity,shared_account=engine.shared_paper_account),cfg,once=a.once)

if __name__=='__main__':main()
