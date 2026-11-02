"""Deterministic smoke/regression tests; synthetic candles are NOT performance evidence."""
import numpy as np
import pandas as pd
import pytest
from .backtester import Settings, backtest, features


def candles(n=2400):
    rng=np.random.default_rng(42)
    close=100*np.exp(np.cumsum(rng.normal(0,0.004,n)))
    open_=np.concatenate(([100],close[:-1]))
    high=np.maximum(open_,close)*(1+rng.uniform(0.001,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0.001,.006,n))
    index=pd.date_range('2021-10-01',periods=n,freq='15min',tz='UTC')
    return pd.DataFrame({'open':open_,'high':high,'low':low,'close':close,'volume':1.0},index=index)


def test_history_cannot_change_prior_signal():
    d=candles(); a=features(d)
    d.loc[d.index[-1],'close']*=1.1
    d.loc[d.index[-1],'high']=max(d.iloc[-1].open,d.iloc[-1].close)*1.01
    b=features(d)
    assert a.iloc[:-1].long_signal.equals(b.iloc[:-1].long_signal)
    assert a.iloc[:-1].short_signal.equals(b.iloc[:-1].short_signal)


def test_h4_regime_known_only_after_h4_close():
    d=candles(); a=features(d)
    # The signal before the most recent completed 4h boundary cannot
    # depend on the contents of a future H4 candle.
    cutoff=pd.Timestamp('2021-10-20T00:00:00Z')
    future=d.index>=cutoff
    d.loc[future,'high']*=1.03
    d.loc[future,'low']*=.97
    b=features(d)
    assert a.loc[a.index<cutoff,'htf_bull'].equals(b.loc[b.index<cutoff,'htf_bull'])
    assert a.loc[a.index<cutoff,'htf_bear'].equals(b.loc[b.index<cutoff,'htf_bear'])


def test_gap_rejected():
    d=candles().drop(candles().index[123])
    with pytest.raises(ValueError,match='Missing or non-contiguous'):
        backtest(d)


def test_smoke_equity_and_trade_ledger():
    d=candles()
    s=Settings(start='2021-10-01',end='2021-10-25')
    report,ledger,curve=backtest(d,s)
    assert curve.index.is_monotonic_increasing
    assert np.isfinite(curve.equity).all()
    assert curve.equity.iloc[-1]>0
    assert report['closed_trades']==len(ledger)
    assert report['max_drawdown_pct']<=0
    assert report['bars']==len(curve)
    assert all(ledger.entry_time <= ledger.exit_time) if len(ledger) else True