"""C3 sleeve: parity with the research backtest, position life cycle, paper-only guard."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd,pytest
import c3_sleeve as C
ROOT=Path(__file__).resolve().parents[2]
H4=4*3600

def cfg(**kw):
    c=json.loads((Path(__file__).parents[1]/'c3_config.json').read_text());c.update(kw);return C.validate(c)

def test_config_is_paper_only_and_validated():
    assert cfg()['dry_run_mode'] is True and len(cfg()['symbols'])==10
    with pytest.raises(ValueError):cfg(dry_run_mode=False)
    with pytest.raises(ValueError):cfg(timeframe='1h')
    with pytest.raises(ValueError):cfg(candle_fetch_limit=300)
    with pytest.raises(ValueError):C.validate({**cfg(),'surprise':1})

@pytest.mark.parametrize('coin',['AVAXUSDT','DOTUSDT'])
def test_signals_match_the_backtest(coin):
    """Every 4h signal (and the ATR used for the stop) equals the research engine's on real data."""
    p=ROOT/'high_cagr/prepared_stage2'/coin/'prices.npy'
    if not p.exists():pytest.skip('research data not restored')
    sys.path.insert(0,str(ROOT));from high_cagr.ideas import ltf_search as L;from high_cagr import run_suite as rs
    o,h,l,c=L.bars(np.load(p),240);sig,atr,adx=L.signals(o,h,l,c);le,se,_,_=sig['PULL'];n=len(c)
    wk=pd.to_datetime(rs.START+(np.arange(n)+1)*240*60000,unit='ms').weekday<5
    ts=rs.START+np.arange(n)*240*60000;rows=np.column_stack([ts,o,h,l,c,np.zeros(n)]);conf=cfg();checked=0
    want=np.where(le&wk)[0].tolist()+np.where(se&wk)[0].tolist()
    rng=np.random.default_rng(1);others=rng.choice(np.arange(1001,n-1),300,replace=False).tolist()
    for t in sorted(set([x for x in want if x>1001])|set(others)):
        win=rows[t-999:t+2].tolist();now=(ts[t]+240*60000)/1000+3   # last row = forming candle, dropped
        df=C.features(win,now,conf);s=C.signal(df,conf)
        exp='long' if (le[t] and wk[t]) else ('short' if (se[t] and wk[t]) else None)
        assert s==exp,(coin,t,s,exp)
        if exp:assert df.atr.iloc[-1]==pytest.approx(atr[t],rel=1e-6);checked+=1
    assert checked>50

class FakeData:
    def __init__(self,rows,price):self.rows=rows;self.px=price
    def candles(self,s,tf,limit):return self.rows[-limit:]
    def price(self,s):return self.px
    def market(self,s):return {'contractSize':1.0}
    def precision(self,s,q):return float(f'{q:.6f}')
    def tradable(self,s,q,p):return q>0

def make_rows(closes,start=1_700_006_400_000):
    """Flat-ish OHLC around given closes; one extra forming candle at the end."""
    out=[];prev=closes[0]
    for i,cl in enumerate(list(closes)+[closes[-1]]):
        hi=max(prev,cl)*1.004;lo=min(prev,cl)*.996;out.append([start+i*H4*1000,prev,hi,lo,cl,1.]);prev=cl
    return out

def uptrend_with_dip(n=700):
    x=np.linspace(0,1,n);c=100*np.exp(1.2*x)                 # steady uptrend -> EMA50 > EMA200, RSI high
    c[-8:-1]=c[-9]*np.linspace(.985,.94,7);c[-1]=c[-2]*1.03   # pullback drives RSI under 40, last candle recovers
    return c

def find_signal_end(c,conf):
    for k in range(len(c),len(c)-1,-1):
        rows=make_rows(c[:k]);now=rows[-1][0]/1000+3;df=C.features(rows,now,conf)
        return rows,now,C.signal(df,conf),df

def test_long_entry_trail_and_stop(tmp_path):
    conf=cfg(skip_weekend=False);c=uptrend_with_dip();rows,now,side,df=find_signal_end(c,conf)
    assert side=='long'
    st=C.Store(tmp_path/'c3.db');data=FakeData(rows,float(c[-1]));sl=C.Sleeve({**conf},st,data)
    sl.c['symbols']=['AVAX/USDT:USDT'];assert sl.scan(now)
    p=st.positions()[0];atr=df.atr.iloc[-1]
    assert p['side']=='long' and p['stop']==pytest.approx(c[-1]-2*atr) and p['risk_usd']==pytest.approx(p['qty']*2*atr)
    assert p['qty']*p['entry']<=.4*10000+1e-6
    # next closed candle higher -> trail = best close - 4.5 ATR, but never below the old stop
    rows2=make_rows(list(c)+[c[-1]*1.2]);data.rows=rows2;data.px=float(c[-1]*1.2);sl.scan(rows2[-1][0]/1000+3);p2=st.positions()[0]
    df2=C.features(rows2,rows2[-1][0]/1000+3,conf);assert p2['stop']==pytest.approx(max(p['stop'],c[-1]*1.2-4.5*df2.atr.iloc[-1]))
    data.px=p2['stop']*.999;sl.watchdog(rows2[-1][0]/1000+10)
    assert not st.positions()
    with st.db() as db:t=db.execute('SELECT side,reason,pnl FROM trades').fetchone()
    assert t[0]=='long' and t[1]=='stop'

def test_weekend_signal_skipped():
    conf=cfg(skip_weekend=True);c=uptrend_with_dip();rows=make_rows(c)
    df=C.features(rows,rows[-1][0]/1000+3,conf);close_day=pd.Timestamp(int(df.timestamp.iloc[-1])+H4*1000,unit='ms').weekday()
    assert (C.signal(df,conf) is None)==(close_day>=5)

def test_no_double_processing_of_a_candle(tmp_path):
    conf=cfg(skip_weekend=False);c=uptrend_with_dip();rows,now,side,df=find_signal_end(c,conf)
    st=C.Store(tmp_path/'c3.db');sl=C.Sleeve({**conf},st,FakeData(rows,float(c[-1])));sl.c['symbols']=['AVAX/USDT:USDT']
    sl.scan(now);sl.scan(now+60)
    with st.db() as db:assert db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
