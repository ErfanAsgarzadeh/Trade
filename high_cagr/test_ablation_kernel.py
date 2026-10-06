"""kernel_fixes must equal kernel when every new switch is off, and each switch must bind when on."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np,pytest
from high_cagr.kernel import simulate as old
from high_cagr.kernel_fixes import simulate as new

def market(ns=4,bars=40):
 minutes=bars*240;rng=np.random.default_rng(7);p=np.zeros((ns,minutes,4))
 for s in range(ns):
  c=100*np.exp(np.cumsum(rng.normal(.00006,.0009,minutes)));o=np.r_[100,c[:-1]]
  p[s]=np.column_stack([o,np.maximum(o,c)*1.0004,np.minimum(o,c)*.9996,c])
 f=np.full((ns,minutes),np.nan);sig=np.zeros((ns,bars+2,4));sig[:,:,3]=-np.inf;bar=np.zeros((ns,bars+2,8))
 for s in range(ns):
  for b in range(1,bars,3):
   price=p[s,b*240-1,3];sig[s,b]=[1 if (b+s)%2 else -1,price,price*(1-(1 if (b+s)%2 else -1)*.03),.01*(s+1)]
  for b in range(bars+2):
   ref=p[s,max(0,min(b*240-1,minutes-1)),3];bar[s,b]=[ref*.97,1.,ref,ref*1.03,ref*.985,ref*1.015,ref*.98,ref*1.02]
 return p,f,sig,bar,minutes

def run(fn,p,f,sig,bar,minutes,**kw):
 return fn(p,f,sig,bar[:,:,:4] if fn is old else bar,0,0,minutes,.0075,4,240,True,**kw)

def test_all_switches_off_is_bit_identical():
 p,f,sig,bar,m=market();a0,t0,c0=run(old,p,f,sig,bar,m);a1,t1,c1=run(new,p,f,sig,bar,m)
 assert len(t0)>5;np.testing.assert_array_equal(a0,a1[:13]);np.testing.assert_array_equal(t0,t1[:,:19]);np.testing.assert_array_equal(c0,c1)

def test_cluster_cap_binds_and_counts():
 p,f,sig,bar,m=market();base=run(new,p,f,sig,bar,m)
 sig[:,1:,0]=np.where(sig[:,1:,0]!=0,1,0);capped=run(new,p,f,sig,bar,m,same_side_cap=2,max_new_per_bar=1)
 roots=capped[1][capped[1][:,18]==0];assert np.unique(roots[:,1],return_counts=True)[1].max()<=1 and capped[0][13]>0
 assert base[0][13]==0

def test_floor_binds_and_add_risk_fraction_is_capped():
 p,f,sig,bar,m=market(bars=120);floor=run(new,p,f,sig,bar,m,floor_on=True)
 assert floor[0][16]>0   # the floor actually fired on this fixture
 roots=floor[1][floor[1][:,18]==0];hit=roots[(roots[:,19]>=2.)&(roots[:,13]==3)];sign=hit[:,3]
 floor_price=hit[:,4]+sign*.25*hit[:,7];assert (sign*(hit[:,8]/(1-sign*.0002)-floor_price)>=-1e-6*hit[:,4]).all()
 safe=run(new,p,f,sig,bar,m,floor_on=True,pyr_risk_mult=.35,pyr_safe=True);adds=safe[1][safe[1][:,18]==1]
 assert len(adds)>0 and (adds[:,15]/adds[:,14]<=.35*.0075+1e-9).all()
 # The safe-pyramid rejection path is exercised by lbank_project/tests/test_profit_floor.py and by the
 # real-data ledger invariant in high_cagr/ablation_fixes.py::validate (this fixture never triggers it).
