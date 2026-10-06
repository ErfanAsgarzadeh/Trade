"""Failure cohorts reconcile with ledgers; categories avoid overlapping counts."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd,pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr.diagnose_failures import classify

@pytest.mark.parametrize('args,expected',[
 ((1.,-1.,0.,1.),'WIN'),((0.,0.,0.,1.),'FLAT'),
 ((-1.,2.,.1,1.),'COST_FLIP'),((-1.,-2.,.4,1.),'NO_FOLLOW_THROUGH'),
 ((-1.,-2.,.7,8.),'FAST_REVERSAL'),((-1.,-2.,1.,1.),'GIVEBACK_GE1R'),
 ((-1.,-2.,.7,9.),'SLOW_FAILURE')])
def test_precedence(args,expected):assert classify(*args)==expected

@pytest.mark.parametrize('period',['full','train','oos'])
def test_position_unit_and_category_reconciliation(period):
 out=ROOT/'high_cagr/output';diagnostic=json.loads((out/'failure_diagnostics.json').read_text())['periods'][period]
 p=pd.read_csv(out/f'failure_positions_{period}.csv');u=pd.read_csv(out/f'failure_units_{period}.csv');m=json.loads((out/'matrix.json').read_text())['winner'][period]
 assert len(p)==m['root_entries'] and len(u)==m['trades']
 assert p.net_pnl.sum()==pytest.approx(m['net_profit'],abs=1e-6)
 np.testing.assert_allclose(p.root_net_pnl+p.add_net_pnl,p.net_pnl)
 assert sum(v['positions'] for v in diagnostic['category_totals'].values())==diagnostic['negative_positions']
 assert sum(v['net_pnl'] for v in diagnostic['category_totals'].values())==pytest.approx(p[p.net_pnl<0].net_pnl.sum())
 np.testing.assert_allclose(u.ideal_gross_before_slippage-u.slippage_drag-u.fees+u.funding_pnl,u.net_pnl,atol=1e-8)
 assert (u.slippage_drag>=-1e-8).all() and (p.mfe_upper_bound_r+1e-9>=p.mfe_r).all()
 assert (p.mfe_r>=0).all() and (p.mae_r>=0).all()
 assert p.entry_adx14.between(0,100).all()
 loss=p[p.net_pnl<0]
 for _,row in loss.iterrows():assert classify(row.net_pnl,row.ideal_gross_before_slippage,row.mfe_r,row.hours)==row.category
 assert set(p.position_id)==set(u[u.leg=='ROOT'].unit_id)
