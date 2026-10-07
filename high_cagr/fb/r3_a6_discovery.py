"""A6 discovery: features of root entries on OLD5+NEW10 H1 (overlaps bench; disclosed)."""
import sys,numpy as np,pandas as pd
sys.path.insert(0,'/home/user/Trade')
from high_cagr import r3_harness as h, run_suite as rs, fb_harness as fh

def features(U,sym,b):
    f=U['frames'][sym];r=int(U['ix'][sym][b])
    if r<60:return None
    g=lambda c,k=0:float(f[c].iat[r-k]);atr=g('atr');c=g('close');side=int(U['side'][sym][b]) or int(U['sig'][U['symbols'].index(sym),b,0])
    kt,kb=g('kumo_top'),g('kumo_bottom');edge=kt if side>0 else kb
    lvl=U['bb'][U['symbols'].index(sym),b,8 if side>0 else 9]
    hi=f['high'].to_numpy()[r-20:r+1];lo=f['low'].to_numpy()[r-20:r+1];cl=f['close'].to_numpy()
    d={}
    d['side']=side
    d['dist_lvl_atr']=side*(c-lvl)/atr
    d['dist_kumo_atr']=side*(c-edge)/atr
    d['atr_pct']=atr/c*100
    d['range20_atr']=(hi.max()-lo.min())/atr
    d['kumo_thick_atr']=(kt-kb)/atr
    d['tk_kj_atr']=side*(g('tenkan')-g('kijun'))/atr
    d['c_vs_kijun_atr']=side*(c-g('kijun'))/atr
    d['rsi']=g('rsi') if side>0 else 100-g('rsi')
    d['ema_spread_atr']=side*(g('ema20')-g('ema50'))/atr
    d['ema20_slope_atr']=side*(g('ema20')-g('ema20',6))/atr
    d['ema50_slope_atr']=side*(g('ema50')-g('ema50',12))/atr
    d['ret6_atr']=side*(c-cl[r-6])/atr
    d['ret30_atr']=side*(c-cl[r-30])/atr
    d['bar_range_atr']=(g('high')-g('low'))/atr
    d['bar_body_atr']=side*(c-g('open'))/atr
    # bars since price crossed kumo edge
    kts=f['kumo_top'].to_numpy()[:r+1];kbs=f['kumo_bottom'].to_numpy()[:r+1]
    inside=(cl[:r+1]<=kts)&(cl[:r+1]>=kbs) if True else None
    out=(cl[:r+1]>kts) if side>0 else (cl[:r+1]<kbs)
    n=0
    while n<60 and out[r-n]:n+=1
    d['bars_out_kumo']=n
    # signals on this symbol in last 30 days (180 bars), same side
    k=U['symbols'].index(sym);s=U['sig'][k,max(0,b-180):b,0]
    d['nsig_30d']=int((s!=0).sum());d['nsig_same_30d']=int((s==side).sum())
    # BTC state
    bf=U['frames']['BTCUSDT'];br=int(U['ix']['BTCUSDT'][b]);bc=float(bf['close'].iat[br]);bat=float(bf['atr'].iat[br])
    bedge=float(bf['kumo_top'].iat[br]) if side>0 else float(bf['kumo_bottom'].iat[br])
    d['btc_dist_kumo_atr']=side*(bc-bedge)/bat
    d['btc_ema_spread_atr']=side*(float(bf['ema20'].iat[br])-float(bf['ema50'].iat[br]))/bat
    d['btc_ret30_atr']=side*(bc-float(bf['close'].iat[br-30]))/bat
    d['rel_ret30_btc']=d['ret30_atr']*atr/c-side*0 - (bc-float(bf['close'].iat[br-30]))/bc*side
    d['hour']=int((f['timestamp'].iat[r]//3600000)%24)
    return d

def ledger(U,period='H1'):
    a,t,_=h._sim(U,{},period,2);rows=[]
    for r in t[t[:,18]==0]:
        legs=t[t[:,17]==r[17]];net=legs[:,12].sum();pct=net/r[14]*100
        b=int(round((r[1]-3000-rs.START)/(U['step']*60000)));sym=U['symbols'][int(r[0])]
        f=features(U,sym,b)
        if f is None:continue
        cat='WIN3' if r[19]>=3 else ('FB' if net<0 and r[19]<.3 else 'CHOP' if net<0 and r[19]<1 else 'LOSEOTHER' if net<0 else 'WIN')
        rows.append(dict(u=U['name'],sym=sym,b=b,pct=pct,mfe=r[19],cat=cat,**f))
    return pd.DataFrame(rows)
if __name__=='__main__':
    df=pd.concat([ledger(h.universe(n)) for n in ('OLD5','NEW10')]);df.to_pickle('/tmp/claude-0/-home-user-Trade/650e644f-f35a-590b-9d7c-c9061437cf5f/scratchpad/a6/disc.pkl')
    print(df.cat.value_counts());print(df.groupby('cat').pct.sum())
