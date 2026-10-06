from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np,pytest
from high_cagr.kernel import simulate
from portfolio.kernel import simulate as old

def data(ns=2,minutes=481):
 p=np.full((ns,minutes,4),100.);p[:,:,1]=101.;p[:,:,2]=99.;f=np.full((ns,minutes),np.nan)
 s=np.zeros((ns,minutes//60+2,4));s[:,:,3]=-np.inf
 for j in range(ns):s[j,0]=[1,100,90,.01*(j+1)]
 b=np.full((ns,minutes//60+2,4),100.);b[:,:,0]=90.;b[:,:,3]=110.
 return p,f,s,b

def test_frozen_kernel_parity():
 p,f,s,b=data(3);s=s[:,::4];b=b[:,::4];f[:,1]=.001
 a,t,c=simulate(p,f,s,b,0,0,len(p[0]),.01,2,240,False,False,False,.0001,1.,0.,1.25)
 a0,t0,c0=old(p,f,s,b,0,0,len(p[0]),.01,1.25,2,False)
 np.testing.assert_allclose(a[:9],a0);np.testing.assert_allclose(t[:,:17],t0);np.testing.assert_allclose(c,c0,equal_nan=True)

def test_margin_and_cost_reconciliation():
 p,f,s,b=data(5);s[:,0,2]=98.;f[:,1]=.01
 a,t,c=simulate(p,f,s,b,0,0,len(p[0]),.05,4,60)
 assert a[6]==4 and a[7]<=.6+1e-10
 assert np.all(t[:,11]<0)
 assert a[0]-10000==pytest.approx(t[:,12].sum())
 np.testing.assert_allclose(t[:,12],t[:,9]-t[:,10]+t[:,11])
 assert np.all(t[:,15]<=t[:,14]*.05+1e-9)

@pytest.mark.parametrize('side',[1,-1])
def test_single_free_ride_add_and_shared_stop(side):
 p,f,s,b=data(1,181)
 p[:,:,:]=100.;p[:,:,1]=100.1;p[:,:,2]=99.9
 s[0,0]=[side,100,100-side*3,.1]
 for i in range(30,181):
  v=110 if side==1 else 90;p[0,i]=[v,v+.1,v-.1,v]
 for j in range(1,4):
  v=110 if side==1 else 90;line=106 if side==1 else 94
  b[0,j]=[line,2,v,line];s[0,j]=[side,v,v-side*4,.1]
 a,t,c=simulate(p,f,s,b,0,0,181,.01,1,60,True)
 assert a[9]==1 and len(t)==2
 assert t[1,18]==1 and t[1,17]==0
 assert t[1,1]==120*60000+3000  # next breakout after favorable stop is armed
 assert t[1,15]<=t[1,14]*.005+1e-8
 assert t[0,2]==t[1,2]

def test_no_add_without_favorable_stop():
 p,f,s,b=data(1,181);p[:,1:]=[110,111,109,110]
 s[0,1:]=[1,110,100,.1]
 a,t,c=simulate(p,f,s,b,0,0,181,.01,1,60,True,True)
 assert a[9]==0
