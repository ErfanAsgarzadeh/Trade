"""Five-year BTCUSDT closed-candle backtest using the delivered strategy.

Minute OHLC paths are assumptions, not observed tick sequences. Indicator
values reproduce the engine's 199-closed-bar windows, including Wilder resets.
"""
from pathlib import Path
import sys
import copy
import json
import math
import zipfile
from collections import deque

import numpy as np
import pandas as pd

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT.parent/'lbank_project'))
import lbank_bot as bot

START=int(pd.Timestamp('2021-10-05',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-10-05',tz='UTC').timestamp()*1000)
SYMBOL='BTC/USDT:USDT'
BASE_PATH=ROOT.parent/'optimization/baseline/config.json'
CONFIG=json.loads((BASE_PATH if BASE_PATH.exists() else ROOT.parent/'lbank_project/config.json').read_text())
CONFIG['symbols']=[SYMBOL]


def load_minutes():
    manifest=json.loads((ROOT/'output/data_manifest.json').read_text())
    records=[r for r in manifest if r['name'].startswith('BTCUSDT-1m-')]
    failures=[r for r in records if r['status']!='verified']
    if failures:raise ValueError('Incomplete archive coverage: '+str(failures))
    frames=[]
    for record in sorted(records,key=lambda r:r['name']):
        with zipfile.ZipFile(ROOT/'cache'/record['name']) as archive:
            with archive.open(archive.namelist()[0]) as handle:
                df=pd.read_csv(handle,header=None,usecols=range(6),low_memory=False,
                               names=['timestamp','open','high','low','close','volume'])
                df=df[pd.to_numeric(df.timestamp,errors='coerce').notna()]
                df=df.astype(float)
                if df.timestamp.max()>1e14:df['timestamp']/=1000
                frames.append(df)
    data=pd.concat(frames,ignore_index=True).sort_values('timestamp').reset_index(drop=True)
    data=data[data.timestamp<END].reset_index(drop=True)
    if data.timestamp.duplicated().any():raise ValueError('Duplicate minute candles')
    expected=pd.date_range(pd.Timestamp(data.timestamp.iloc[0],unit='ms',tz='UTC'),pd.Timestamp(END-60000,unit='ms',tz='UTC'),freq='min')
    missing=np.setdiff1d(expected.astype('int64')//1_000_000,data.timestamp.astype('int64').to_numpy())
    if len(missing):raise ValueError(f'Missing {len(missing)} minute candles, first={missing[:10]}')
    if not np.isfinite(data.to_numpy()).all():raise ValueError('Non-finite price data')
    if ((data.high<data[['open','close','low']].max(axis=1)) | (data.low>data[['open','close','high']].min(axis=1)) | (data[['open','high','low','close']].min(axis=1)<=0)).any():
        raise ValueError('Invalid minute candle geometry')
    return data


def aggregate(minutes,frequency):
    source=minutes.set_index(pd.to_datetime(minutes.timestamp,unit='ms',utc=True))
    frame=source.resample(frequency,closed='left',label='left').agg(
        {'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    counts=source.close.resample(frequency).count()
    required=60 if frequency=='1h' else 240
    frame=frame[counts==required].copy()
    frame.insert(0,'timestamp',frame.index.astype('int64')//1_000_000)
    return frame.reset_index(drop=True)


def weighted_wilder_last(raw,n,window,first_override=None):
    """Exact last value of each independently seeded rolling Wilder window."""
    weights=np.zeros(window)
    weights[:n]=((n-1)/n)**(window-n)/n
    weights[n:]=((n-1)/n)**np.arange(window-n-1,-1,-1)/n
    values=np.full(len(raw),np.nan)
    views=np.lib.stride_tricks.sliding_window_view(raw,window)
    output=views@weights
    if first_override is not None:
        output+=(first_override[:len(output)]-raw[:len(output)])*weights[0]
    values[window-1:]=output
    return values


def prepare_indicators(raw,c=CONFIG):
    df=raw.copy();i,f=c['ichimoku_params'],c['filters_and_triggers']
    closed=i['candle_fetch_limit']-1
    for name,n in [('tenkan',i['tenkan']),('kijun',i['kijun']),('senkou_b_future',i['senkou_b'])]:
        df[name]=(df.high.rolling(n).max()+df.low.rolling(n).min())/2
    df['senkou_a_future']=(df.tenkan+df.kijun)/2
    df['senkou_a_curr']=df.senkou_a_future.shift(i['displacement'])
    df['senkou_b_curr']=df.senkou_b_future.shift(i['displacement'])
    df['kumo_top']=df[['senkou_a_curr','senkou_b_curr']].max(axis=1,skipna=False)
    df['kumo_bottom']=df[['senkou_a_curr','senkou_b_curr']].min(axis=1,skipna=False)
    differences=np.diff(df.close.to_numpy())
    gains=weighted_wilder_last(np.maximum(differences,0),f['rsi_period'],closed-1)
    losses=weighted_wilder_last(np.maximum(-differences,0),f['rsi_period'],closed-1)
    with np.errstate(divide='ignore',invalid='ignore'):
        rsi=100-100/(1+gains/losses)
    rsi[(gains>0)&(losses==0)]=100
    rsi[(gains==0)&(losses>0)]=0
    rsi[(gains==0)&(losses==0)]=50
    df['rsi']=np.r_[np.nan,rsi]
    previous=df.close.shift(1)
    tr=pd.concat([df.high-df.low,(df.high-previous).abs(),(df.low-previous).abs()],axis=1).max(axis=1).to_numpy()
    df['atr']=weighted_wilder_last(tr,f['atr_period'],closed,(df.high-df.low).to_numpy())
    return df


def verify_indicator_equivalence(raw,fast,tf):
    columns=['tenkan','kijun','senkou_a_future','senkou_b_future','senkou_a_curr','senkou_b_curr','kumo_top','kumo_bottom','rsi','atr']
    checked=0
    for end in np.linspace(199,len(raw)-2,25,dtype=int):
        batch=raw.iloc[end-198:end+2][['timestamp','open','high','low','close','volume']].values.tolist()
        now=(raw.iloc[end+1].timestamp+3000)/1000
        expected=bot.indicators(batch,CONFIG,tf,now).iloc[-1]
        actual=fast.iloc[end]
        np.testing.assert_allclose(actual[columns].astype(float),expected[columns].astype(float),rtol=1e-11,atol=1e-8)
        checked+=1
    return checked


def compile_signals(hourly,fourhour):
    # Only the most recent COMPLETED 4h bar is matched to each completed 1h bar.
    close_times=hourly.timestamp.to_numpy(dtype='int64')+3600000
    htf_close=fourhour.timestamp.to_numpy(dtype='int64')+14400000
    regimes=[]
    for index in range(len(fourhour)):
        regimes.append(bot.regime(fourhour.iloc[max(0,index-30):index+1],CONFIG))
    matched=np.searchsorted(htf_close,close_times,side='right')-1
    signals={}
    f=CONFIG['filters_and_triggers'];a=CONFIG['al_brooks_filters']
    eligible=0
    for index in range(198,len(hourly)):
        timestamp=int(close_times[index])
        if not START<=timestamp<END or matched[index]<0:continue
        side=regimes[matched[index]]
        if side is None:continue
        b=hourly.iloc[index]
        if abs(b.close-b.kijun)>f['max_kijun_extension_atr']*b.atr:continue
        if not f[f'{side}_rsi_min']<=b.rsi<=f[f'{side}_rsi_max']:continue
        if side=='long' and not (b.low<=b.kijun+f['kijun_touch_atr_tolerance']*b.atr and b.close>b.kijun):continue
        if side=='short' and not (b.high>=b.kijun-f['kijun_touch_atr_tolerance']*b.atr and b.close<b.kijun):continue
        eligible+=1
        if bot.entry_signal(hourly.iloc[max(0,index-max(a['h2_l2_lookback_bars']+2,a['barb_wire_lookback']+1)):index+1].reset_index(drop=True),side,CONFIG):
            signals[timestamp]=(side,b)
    print('Signals:',len(signals),'coarse entry candidates:',eligible,flush=True)
    return signals


def load_funding():
    frames=[]
    for path in sorted((ROOT/'cache').glob('BTCUSDT-fundingRate-*.zip')):
        with zipfile.ZipFile(path) as z:
            frames.append(pd.read_csv(z.open(z.namelist()[0])))
    data=pd.concat(frames,ignore_index=True)
    data['minute']=(data.calc_time.astype('int64')//60000)*60000
    if data.minute.duplicated().any():raise ValueError('Duplicate funding event')
    return dict(zip(data.minute.astype(int),data.last_funding_rate.astype(float)))


class Precision:
    def market(self,symbol):return {'contractSize':1.0}
    def precision(self,symbol,qty):return math.floor(qty*10000+1e-9)/10000
    def tradable(self,symbol,qty,price):return qty>=.0001 and qty*price>=5


class Simulator:
    def __init__(self,path='adverse',slippage_bps=0,funding=False):
        self.path=path;self.slippage=slippage_bps/10000;self.with_funding=funding
        self.balance=10000.0;self.p=None;self.history=[];self.trades=[];self.equity=[]
        self.realized=deque();self.daily=0.0;self.highwater=10000.0;self.max_dd=0.0
        self.precision=Precision();self.setups=0;self.cancelled=0;self.funding_flow=0.0
        self.funding_exposures_missing=[];self.ambiguous_minutes=0

    def daily_pnl(self,timestamp):
        cutoff=timestamp-86400000
        while self.realized and self.realized[0][0]<cutoff:
            self.daily-=self.realized.popleft()[1]
        return self.daily

    def mark(self,price):
        if self.p is None or self.p['state']==bot.PENDING:return self.balance
        return self.balance+bot.net_pnl(self.p,price,self.p['qty'])

    def observe(self,price):
        equity=self.mark(price);self.highwater=max(self.highwater,equity)
        if self.highwater>0:self.max_dd=max(self.max_dd,(self.highwater-equity)/self.highwater)
        return equity

    def cancel(self):
        self.p=None;self.cancelled+=1

    def enter(self,raw_price,timestamp):
        p=self.p;sign=1 if p['side']=='long' else -1
        equity=self.balance
        if equity<=0 or self.daily_pnl(timestamp)<=-equity*CONFIG['risk_and_exit']['daily_max_loss_pct']:
            self.cancel();return
        price=raw_price*(1+sign*self.slippage)
        distance=sign*(price-p['initial_sl'])
        if distance<=0:self.cancel();return
        p['risk_budget']=min(p['risk_budget'],equity*CONFIG['risk_and_exit']['risk_per_trade_pct'])
        p['qty']=self.precision.precision(SYMBOL,min(p['qty'],p['risk_budget']/(distance+price*p['fee_rate']),p['max_notional']/price))
        if not self.precision.tradable(SYMBOL,p['qty'],price):self.cancel();return
        p.update(state=bot.INITIAL,entry_price=price,tp1_price=price+sign*p['tp1_rr']*distance)
        record={'id':len(self.trades)+1,'side':p['side'],'signal_time':iso(p['signal_ts']+3600000),
                'entry_time':iso(timestamp),'entry_price':price,'initial_qty_btc':p['qty'],
                'initial_sl':p['initial_sl'],'tp1_price':p['tp1_price'],
                'gross_pnl':0.0,'fees':0.0,'funding_pnl':0.0,'net_pnl':0.0,'exit_reason':'','exit_time':''}
        self.trades.append(record);p['trade_id']=record['id']
        self.observe(price)

    def close(self,raw_price,timestamp,reason,partial=False):
        p=self.p;sign=1 if p['side']=='long' else -1
        price=raw_price*(1-sign*self.slippage)
        qty=self.precision.precision(SYMBOL,p['qty']*p['tp1_close_pct']) if partial else p['qty']
        if partial and (not self.precision.tradable(SYMBOL,qty,price) or not self.precision.tradable(SYMBOL,p['qty']-qty,price)):
            qty=p['qty'];partial=False;reason='tp1_full_small_position'
        gross=sign*(price-p['entry_price'])*qty
        fees=(p['entry_price']+price)*qty*p['fee_rate']/2
        pnl=gross-fees
        self.balance+=pnl
        self.realized.append((timestamp,pnl));self.daily+=pnl
        record=self.trades[p['trade_id']-1]
        record['gross_pnl']+=gross;record['fees']+=fees;record['net_pnl']+=pnl
        self.history.append({'trade_id':p['trade_id'],'timestamp':iso(timestamp),'qty_btc':qty,
                             'entry_price':p['entry_price'],'exit_price':price,'gross_pnl':gross,
                             'fees':fees,'net_pnl':pnl,'reason':reason})
        if partial:
            p['qty']-=qty;p['active_sl']=p['entry_price'];p['state']=bot.TRAILING
        else:
            record['exit_time']=iso(timestamp);record['exit_reason']=reason;self.p=None
        self.observe(raw_price)

    def point(self,price,timestamp):
        p=self.p
        if p is None:return
        sign=1 if p['side']=='long' else -1
        if p['state']==bot.PENDING:
            if timestamp>=p['expiry_ts']*1000 or sign*(price-p['cancel_price'])<=0:self.cancel()
            elif sign*(price-p['trigger_price'])>=0:self.enter(price,timestamp)
        else:
            if sign*(price-p['active_sl'])<=0:self.close(price,timestamp,'stop')
            elif p['state']==bot.INITIAL and sign*(price-p['tp1_price'])>=0:self.close(price,timestamp,'tp1',True)

    def segment(self,first,last,start,end):
        current=first;event_time=start
        for _ in range(5):
            p=self.p
            if p is None or current==last:break
            levels=[('entry',p['trigger_price']),('cancel',p['cancel_price'])] if p['state']==bot.PENDING else [('stop',p['active_sl'])]+([('tp1',p['tp1_price'])] if p['state']==bot.INITIAL else [])
            events=[]
            sign=1 if p['side']=='long' else -1
            for name,level in levels:
                if min(current,last)<=level<=max(current,last) and level!=current:
                    correct=(sign*(last-current)>0) if name in ('entry','tp1') else (sign*(last-current)<0)
                    if correct:events.append((abs(level-current),name,level))
            if not events:break
            _,name,level=min(events)
            fraction=abs((level-first)/(last-first)) if last!=first else 0
            event_time=int(start+(end-start)*fraction)
            if name=='entry':self.enter(level,event_time)
            elif name=='cancel':self.cancel()
            else:self.close(level,event_time,'stop' if name=='stop' else 'tp1',name=='tp1')
            current=level
        self.observe(last)

    def run(self,minutes,hourly,signals,funding):
        hour_lookup={int(row.timestamp)+3600000:row for row in hourly.itertuples(index=False)}
        arrays=minutes.loc[(minutes.timestamp>=START)&(minutes.timestamp<END),['timestamp','open','high','low','close']].to_numpy()
        for timestamp,opening,high,low,close in arrays:
            timestamp=int(timestamp)
            p=self.p
            if self.with_funding and p and p['state']!=bot.PENDING:
                if timestamp in funding:
                    flow=-(1 if p['side']=='long' else -1)*opening*p['qty']*funding[timestamp]
                    self.balance+=flow;self.funding_flow+=flow
                    self.trades[p['trade_id']-1]['funding_pnl']+=flow
                    self.trades[p['trade_id']-1]['net_pnl']+=flow
                elif timestamp>=int(pd.Timestamp('2026-10-01',tz='UTC').timestamp()*1000) and timestamp%28800000==0:
                    self.funding_exposures_missing.append({'time':iso(timestamp),'qty':p['qty']})
            # Gap checks occur at the first available minute price before scanning.
            self.point(opening,timestamp)
            if timestamp%3600000==0:
                bar=hour_lookup.get(timestamp)
                if self.p and self.p['state']==bot.TRAILING and bar:
                    sign=1 if self.p['side']=='long' else -1
                    if sign*(bar.close-bar.kijun)<0:self.close(opening,timestamp+3000,'kijun_break')
                    else:
                        candidate=bar.kijun-sign*.2*bar.atr
                        self.p['active_sl']=max(self.p['active_sl'],candidate) if sign==1 else min(self.p['active_sl'],candidate)
                        self.point(opening,timestamp+3000)
                if self.p is None and timestamp in signals:
                    side,bar=signals[timestamp]
                    if self.balance>0 and self.daily_pnl(timestamp+3000)>-self.balance*CONFIG['risk_and_exit']['daily_max_loss_pct']:
                        p=bot.size_position(self.precision,SYMBOL,side,bar,self.balance,CONFIG,'1h')
                        if p:
                            self.p=p;self.setups+=1;self.point(opening,timestamp+3000)
            if self.p:
                sign=1 if self.p['side']=='long' else -1
                if self.p['state']==bot.PENDING:
                    if low<=self.p['cancel_price']<=high and low<=self.p['trigger_price']<=high:self.ambiguous_minutes+=1
                elif self.p['state']==bot.INITIAL:
                    if low<=self.p['active_sl']<=high and low<=self.p['tp1_price']<=high:self.ambiguous_minutes+=1
                adverse=self.path=='adverse'
                points=[opening,low,high,close] if (sign==1)==adverse else [opening,high,low,close]
                offsets=[0,20000,40000,59999]
                for index in range(3):
                    self.segment(points[index],points[index+1],timestamp+offsets[index],timestamp+offsets[index+1])
            self.observe(close)
            if (timestamp+60000)%3600000==0:
                self.equity.append({'timestamp':iso(timestamp+60000),'equity_usd':self.mark(close),'balance_usd':self.balance})
        if self.p:
            if self.p['state']==bot.PENDING:self.cancel()
            else:self.close(float(arrays[-1,4]),END-1,'end_of_test')
        if self.equity:self.equity[-1]['equity_usd']=self.balance;self.equity[-1]['balance_usd']=self.balance
        return self.summary()

    def summary(self):
        pnls=[t['net_pnl'] for t in self.trades]
        profits=sum(max(p,0) for p in pnls);losses=-sum(min(p,0) for p in pnls)
        assert math.isclose(self.balance-10000,sum(pnls),rel_tol=1e-9,abs_tol=1e-6)
        return {'path_model':self.path,'slippage_bps_per_fill':self.slippage*10000,
                'historical_binance_funding_included':self.with_funding,
                'initial_equity':10000,'final_equity':self.balance,'net_profit':self.balance-10000,
                'return_pct':(self.balance/10000-1)*100,'trades':len(pnls),
                'winning_trades':int(sum(p>0 for p in pnls)),'losing_trades':int(sum(p<0 for p in pnls)),
                'win_rate_pct':sum(p>0 for p in pnls)/len(pnls)*100 if pnls else 0,
                'profit_factor':profits/losses if losses else None,'max_drawdown_pct':self.max_dd*100,
                'long_trades':sum(t['side']=='long' for t in self.trades),
                'short_trades':sum(t['side']=='short' for t in self.trades),
                'gross_profit':sum(t['gross_pnl'] for t in self.trades),
                'fees':sum(t['fees'] for t in self.trades),'funding_pnl':self.funding_flow,
                'exit_fills':len(self.history),'setups_created':self.setups,
                'setups_cancelled':self.cancelled,'ambiguous_minutes':self.ambiguous_minutes,
                'missing_funding_exposures':self.funding_exposures_missing}


def iso(timestamp):return pd.Timestamp(int(timestamp),unit='ms',tz='UTC').isoformat()


def main():
    minutes=load_minutes();print('Loaded minute rows:',len(minutes),flush=True)
    hour_raw=aggregate(minutes,'1h');four_raw=aggregate(minutes,'4h')
    hourly=prepare_indicators(hour_raw);fourhour=prepare_indicators(four_raw)
    checks=verify_indicator_equivalence(hour_raw,hourly,'1h')+verify_indicator_equivalence(four_raw,fourhour,'4h')
    print('Engine indicator equivalence checks:',checks,flush=True)
    signals=compile_signals(hourly,fourhour);funding=load_funding()
    scenarios=[('strategy_fee_only','adverse',0,False),('execution_costs','adverse',2,True),('intrabar_sensitivity','reverse',2,True)]
    summaries=[]
    for name,path,slippage,with_funding in scenarios:
        sim=Simulator(path,slippage,with_funding)
        summary=sim.run(minutes,hourly,signals,funding)
        summary['scenario']=name;summaries.append(summary)
        for title,values in [('trades',sim.trades),('exit_fills',sim.history),('equity',sim.equity)]:
            (ROOT/'output'/f'{name}_{title}.json').write_text(json.dumps(values,indent=2,allow_nan=False))
        print(json.dumps(summary,indent=2),flush=True)
    metadata={'start_utc':iso(START),'end_exclusive_utc':iso(END),'source':'Binance USD-M BTCUSDT perpetual, official public archives',
              'requested_test_minutes':(END-START)//60000,'loaded_minutes_including_warmup':len(minutes),
              'signal_candidates':len(signals),'indicator_equivalence_checks':checks,
              'parameters':CONFIG,'scenarios':summaries}
    (ROOT/'output'/'summary.json').write_text(json.dumps(metadata,indent=2,allow_nan=False))
    print('Saved summary and all trade ledgers.',flush=True)

if __name__=='__main__':main()
