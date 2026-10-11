"""Selected Ghoghnous policy: causal gates, frozen sizing, migration and shared-capital limits."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import pa_sleeve as P
from test_pa_sleeve import pcfg, FakeData, rows_with_keyrev, scan_time
from test_system import system, cfg  # fixtures

SYM='LINK/USDT:USDT'

def calm_rows():
    rows=rows_with_keyrev(n=700,drift=.02)
    for row in rows[:-60]:row[2]=row[4]+6.
    return rows

def soft_sleeve(tmp_path, factor=1.5, name='soft.db'):
    rows=calm_rows();store=P.Store(tmp_path/name)
    sl=P.Sleeve(pcfg(symbols=[SYM],volume_multiplier=factor),store,FakeData(rows,rows[-2][4]))
    return sl,store,rows

def test_shipped_policy_and_old_config_compatibility():
    c=pcfg();assert c['strategy_variant']==P.SOFT_VARIANT and c['volume_multiplier']==1.5
    old={k:v for k,v in c.items() if k not in ('strategy_variant','volume_multiplier')}
    assert P.validate(old)['strategy_variant']=='C2_baseline'
    assert P.validate(old)['volume_multiplier']==1.

@pytest.mark.parametrize('bad',[{'volume_multiplier':2.},{'volume_multiplier':0.},
    {'volume_multiplier':float('nan')},{'volume_multiplier':float('inf')},
    {'volume_multiplier':True},{'strategy_variant':'NSD'}])
def test_composite_risk_cap(bad):
    with pytest.raises(ValueError):pcfg(**bad)

@pytest.mark.parametrize('side',['long','short'])
@pytest.mark.parametrize('aligned',[False,True])
def test_exhaustion_gate_preserves_raw_opposite_signal(monkeypatch,side,aligned):
    direction=1 if side=='long' else -1
    df=pd.DataFrame({'close':100.+direction*(1 if aligned else -1)*np.arange(80),'atr':np.ones(80)})
    raw={'side':side,'level':110.,'stop':90.}
    monkeypatch.setattr(P,'signal',lambda df,c:raw)
    monkeypatch.setattr(P,'vol_rank',lambda df,n:.254)
    got,entry=P.tradable_signal(df,pcfg())
    assert got is raw and 'risk_weight' not in raw
    assert (entry is None)==aligned
    if entry:assert entry['risk_weight']==pytest.approx(.9375/P.FUZZY_NORMALIZER)

@pytest.mark.parametrize('vr,allowed',[(.154,True),(.353,True),(.354,False),(float('nan'),False)])
def test_rank_boundary_and_fuzzy_budget(monkeypatch,vr,allowed):
    df=pd.DataFrame({'close':np.full(80,100.),'atr':np.ones(80)})
    raw={'side':'long','level':110.,'stop':90.}
    monkeypatch.setattr(P,'signal',lambda df,c:raw);monkeypatch.setattr(P,'vol_rank',lambda df,n:vr)
    got,entry=P.tradable_signal(df,pcfg());assert got is raw
    assert (entry is not None)==allowed
    if entry:
        expected=(.75+.25*min(1,max(0,(.554-vr)/.4)))/.7755069444444445
        assert P.planned_risk(pcfg(),entry)==pytest.approx(.004*1.5*expected)

def test_closed_candle_policy_ignores_forming_bar(tmp_path):
    sl,store,rows=soft_sleeve(tmp_path);now=scan_time(rows)
    raw,entry=P.tradable_signal(P.features(rows,now,sl.c),sl.c);assert entry
    altered=[r[:] for r in rows];altered[-1][1:5]=[1.,1e9,.001,1e8]
    assert P.tradable_signal(P.features(altered,now,sl.c),sl.c)==(raw,entry)

def test_real_scan_snapshots_weight_and_fill_scales_volume_only(tmp_path):
    sl,store,rows=soft_sleeve(tmp_path);now=scan_time(rows);assert sl.scan(now)
    saved=store.orders()[SYM];assert saved['policy_variant']==P.SOFT_VARIANT
    sl.data.px=saved['level']+.05
    sl.data.rows=[]  # a fill must use the stored signal, without fetching or recomputing indicators
    sl.watchdog(now+60);p=store.positions()[0]
    budget=.004*1.5*saved['risk_weight']*10000
    assert p['qty']*p['entry']==pytest.approx(budget/((p['entry']-p['stop'])/p['entry']+.0016),rel=1e-5)
    other,st2,rows2=soft_sleeve(tmp_path,factor=1.,name='unscaled.db');other.scan(now)
    other.data.px=sl.data.px;other.watchdog(now+60);p2=st2.positions()[0]
    assert p['qty']==pytest.approx(1.5*p2['qty'],rel=1e-6)
    assert (p['entry'],p['stop'],p['target'])==(p2['entry'],p2['stop'],p2['target'])
    sl.c=pcfg(symbols=[SYM],volume_multiplier=1.)
    sl.watchdog(now+70);assert store.positions()[0]==p  # hot reload never resizes an existing position

@pytest.mark.parametrize('extra',[{}, {'policy_variant':P.SOFT_VARIANT,'risk_weight':float('nan')},
    {'policy_variant':P.SOFT_VARIANT,'risk_weight':-1.}, {'policy_variant':P.SOFT_VARIANT,'risk_weight':100.}])
def test_legacy_or_invalid_pending_cannot_fill(tmp_path,extra):
    sl,store,rows=soft_sleeve(tmp_path);now=scan_time(rows);sl.data.px=100.
    store.set_order(SYM,dict(side='long',level=100.,stop=95.,signal_ts=0,expires=(now+3600)*1000,**extra))
    sl.watchdog(now);assert store.orders()=={} and store.positions()==[]

def test_upgrade_is_idempotent_and_retains_custom_values(tmp_path):
    shipped=Path(P.__file__).with_name('pa_config.json');path=tmp_path/'config.json'
    old=json.loads(shipped.read_text());old.pop('strategy_variant');old.pop('volume_multiplier')
    old['risk_per_trade_pct']=.003;old['enabled']=False
    path.write_text(json.dumps(old));P.prepare_config(path,shipped);first=path.read_bytes()
    P.prepare_config(path,shipped);assert path.read_bytes()==first
    got=P.load(path);assert got['strategy_variant']==P.SOFT_VARIANT and got['volume_multiplier']==1.5
    assert got['risk_per_trade_pct']==.003 and got['enabled'] is False

def test_invalid_upgrade_leaves_existing_config_intact(tmp_path):
    shipped=Path(P.__file__).with_name('pa_config.json');path=tmp_path/'config.json'
    old=json.loads(shipped.read_text());old.pop('strategy_variant');old.pop('volume_multiplier')
    old['risk_per_trade_pct']=.01;path.write_text(json.dumps(old));before=path.read_bytes()
    with pytest.raises(ValueError,match='Effective PA risk'):P.prepare_config(path,shipped)
    assert path.read_bytes()==before

def test_filtered_opposite_still_closes_existing_position(tmp_path,monkeypatch):
    sl,store,rows=soft_sleeve(tmp_path);now=scan_time(rows);sl.scan(now)
    sl.data.px=store.orders()[SYM]['level']+.05;sl.watchdog(now+60);assert store.positions()
    later=rows[:-1]+[rows[-1][:],rows[-1][:]]
    later[-1][0]+=P.H4*1000
    sl.data.rows=later;sl.data.px=rows[-2][2]+.05
    monkeypatch.setattr(P,'signal',lambda df,c:{'side':'short','level':1.,'stop':200.})
    monkeypatch.setattr(P,'vol_rank',lambda df,n:.354)  # entry blocked, raw exit retained
    sl.scan(scan_time(later))
    assert store.positions()==[] and store.orders()=={}
    with store.db() as db:assert db.execute('SELECT reason FROM trades').fetchone()[0]=='opposite'

def test_shared_pool_caps_selected_sizing(system):
    conf=system.config.read();conf['portfolio_risk'].update(shared_c3_account=True,margin_allocation_mode='SHARED_POOL')
    conf['risk_and_exit']['engaged_capital_pct']=.01;system.config.write(conf)
    path,store=P.paths();sl=P.Sleeve(pcfg(symbols=[SYM]),store,system.data,shared_account=system.shared_paper_account)
    order=dict(side='long',level=100.,stop=99.,signal_ts=0,policy_variant=P.SOFT_VARIANT,risk_weight=1/P.FUZZY_NORMALIZER)
    assert sl.open(SYM,order,2.)
    snap=system.shared_paper_account().snapshot()
    assert snap['reserved_margin_usd']<=snap['allowed_margin_usd']+1e-6
    assert store.positions()[0]['qty']*100 < 1000  # desired notional exceeds 6,000; shared margin clips it

def test_dashboard_reports_effective_range_and_multiplier(tmp_path):
    sl,store,rows=soft_sleeve(tmp_path)
    result=P.summary(store,sl.c,sl.data.price,10000.)
    assert result['volume_multiplier']==1.5 and result['strategy_variant']==P.SOFT_VARIANT
    assert result['planned_risk_min']==pytest.approx(.004*1.5*.875/P.FUZZY_NORMALIZER)
    assert result['planned_risk_max']==pytest.approx(.007736874625021267)
