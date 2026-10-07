"""A6 loss-anatomy: block entries when BTC's own state is weak/against the trade (rules pre-declared in r3_a6_rules_declared.txt)."""
import sys,numpy as np
sys.path.insert(0,'/home/user/Trade')
from high_cagr import r3_harness as h
VARIANTS={'A':{'r1':True,'r2':False},'B':{'r1':False,'r2':True},'C':{'r1':True,'r2':True}}
def build_fn(U,v):
    sig=U['sig'].copy();bf=U['frames']['BTCUSDT'];nb=sig.shape[1];br=np.asarray(U['ix']['BTCUSDT'])
    ok=br>=30;r=np.where(ok,br,30)
    c=bf['close'].to_numpy();atr=bf['atr'].to_numpy();kt=bf['kumo_top'].to_numpy();kb=bf['kumo_bottom'].to_numpy()
    for k in range(sig.shape[0]):
        side=sig[k,:,0]
        d30=side*(c[r]-c[r-30])/atr[r];edge=np.where(side>0,kt[r],kb[r]);dk=side*(c[r]-edge)/atr[r]
        bad=np.zeros(nb,bool)
        if v['r1']:bad|=(d30<0)
        if v['r2']:bad|=(dk<0.5)
        bad&=(side!=0)&ok;sig[k,bad,0]=0
    return {'sig':sig}
if __name__=='__main__':
    h.run_method('r3_a6_btcstate','both',VARIANTS,build_fn,notes='A6: BTC-state rules from H1 discovery on OLD5+NEW10 (overlaps bench).')
