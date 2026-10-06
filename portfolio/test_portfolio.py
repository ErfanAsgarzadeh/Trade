import sys
from pathlib import Path
import numpy as np,pandas as pd,pytest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from portfolio.kernel import simulate
from lbank_project import strategy_archetypes as shared

def data(ns=6,minutes=241):
 p=np.full((ns,minutes,4),100.);p[:,:,1]=101.;p[:,:,2]=99.;f=np.full((ns,minutes),np.nan)
 s=np.zeros((ns,3,4));s[:,:,3]=-np.inf
 for j in range(ns):s[j,0]=[1,100,90,.01*(j+1)]
 b=np.full((ns,3,4),100.);b[:,:,0]=90.;b[:,:,3]=110.
 return p,f,s,b

def test_rank_slots_fees_funding_and_single_pool():
 p,f,s,b=data();f[:,1]=.001
 a,t,c=simulate(p,f,s,b,0,0,241,.01,1.25,3,False)
 assert t[:,0].tolist()==[5,4,3] and a[6]==3 and a[3]==3
 assert np.all(t[:,11]<0) and np.allclose(t[:,9]-t[:,10]+t[:,11],t[:,12])
 assert abs(a[0]-10000-t[:,12].sum())<1e-8

def test_funding_before_entry_not_charged():
 p,f,s,b=data(1);f[:,0]=.005;a,t,c=simulate(p,f,s,b,0,0,241,.01,1.25,1,False);assert t[0,11]==0

def test_fourth_margin_is_clamped_to_remaining_pool():
 p,f,s,b=data();s[:,0,2]=98.;a,t,c=simulate(p,f,s,b,0,0,241,.05,1.25,4,False)
 assert len(t)==4 and a[7]<=1+1e-10 and t[3,5]*t[3,4]<1.25*t[3,14]

def test_actual_fill_gap_minimum_stop_rejection():
 p,f,s,b=data(1);s[0,0,2]=98.;p[0,0,0]=99.;a,t,c=simulate(p,f,s,b,0,0,241,.01,1.25,1,False);assert len(t)==0 and a[2]==1

def test_kijun_closed_bar_exit_time():
 p,f,s,b=data(1,481);b[0,1]=[105,2,104,105];a,t,c=simulate(p,f,s,b,0,0,481,.01,1.25,1,True);assert t[0,13]==7 and t[0,2]==240*60000+3000

@pytest.mark.parametrize('side',['long','short'])
def test_normalized_rank_combines_kumo_and_channel(side):
 b=pd.Series(dict(close=110 if side=='long' else 90,kumo_top=105,kumo_bottom=95,donchian_high_20=103,donchian_low_20=97));assert shared.breakout_strength(b,side)==pytest.approx(5/(110 if side=='long' else 90))
