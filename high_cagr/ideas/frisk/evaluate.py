"""F risk manager (branch claude/optimistic-newton-ovy9ap: risk_overlay.py / risk_gate.py, research dd_lab9.py 'F balanced')
on the three bots WITH the win-rate rules (Shahin late-entry gate, Mojsavar profit lock + half at 2R).

F as deployed: AI regime score (percentile p; p < 0.30 -> x0, p > 0.70 -> x1.4, else x1; applied from the next day; open
positions cut when it falls), volatility target 1 %/day over 20 days (x0.3..1.5), drawdown brake 8 % -> 14 % (floor x0.2, new
and open positions), per-bot streak (last 20 closed trades < -4R -> x0.5), global scale x1.41. Replayed with dd_engine.py
(copied unchanged; equals five_year_report.replay without controls).

AI score, two versions:
  prod  = the shipped model models/risk_ai_r20.json (trained on ALL days up to 2026-10-04 -> in-sample, an upper bound)
  wf    = the same recipe (GBM depth 3, 250 trees, lr 0.03, min leaf 60, target = next-20-day return of the reference account)
          trained walk-forward: 2023 / 2024 / 2025-26 only on days whose 20-day target ended before the test year; 2022 on
          2023-26 with a 30-day purge (no past exists; labelled). Reference account = the new-rule legs at constant risk.
Features as dd_ai.py: 35-coin market block (Binance closes), 3-day funding, Fear & Greed (alternative.me), stablecoin supply
(DefiLlama), reference-account returns / drawdown / vol and open-position counts / open R.
"""
from pathlib import Path
import sys,json,urllib.request
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.frisk import dd_engine as E
from high_cagr.ideas import three_bots_replay as TB, pa_bot as PBOT, xuni as X, holdout_test as H
from high_cagr.ideas.winrate import ledger as LG, exits as EX, run_rules as RR
from high_cagr import run_suite as rs
HERE=Path(__file__).resolve().parent;OUT=ROOT/'high_cagr/output/ideas/frisk';D=E.DAYS;START=pd.Timestamp('2021-10-05')
COINS=list(rs.SYMBOLS)+X.NEW+H.H10+H.H2
CTRL=dict(vt=(.01,20,.3,1.5),gopen=True,ddopen=(.08,.14,.2),botdd=(20,-4.,.5),scale=1.41)
def day(s):return (pd.Timestamp(s)-START).days
FOLDS={'2022':(day('2022-01-01'),day('2023-01-01')),'2023':(day('2023-01-01'),day('2024-01-01')),'2024':(day('2024-01-01'),day('2025-01-01')),'2025-26':(day('2025-01-01'),D)}

def new_legs():
    df=LG.build();legs=LG.raw_legs();keep=RR.keep_mask(df,['main_late'],RR.thresholds(df));c3x,_=EX.modified_legs(legs,**RR.C3EXIT)
    return [l for l,k in zip(c3x,keep) if k]

def sentiment():
    p=OUT/'sentiment.json'
    if p.exists():return json.loads(p.read_text())
    get=lambda u:json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'research'}),timeout=60))
    fng={str(pd.Timestamp(int(x['timestamp']),unit='s').date()):float(x['value']) for x in get('https://api.alternative.me/fng/?limit=0')['data']}
    st={str(pd.Timestamp(int(x['date']),unit='s').date()):float(x['totalCirculatingUSD']['peggedUSD']) for x in get('https://stablecoins.llama.fi/stablecoincharts/all')}
    OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(dict(fng=fng,stable=st)));return dict(fng=fng,stable=st)

def features(legs):
    ref=E.replay(legs)['daily'];rr=np.r_[0,ref[1:]/ref[:-1]-1];ends=(np.arange(D)+1)*1440-1
    cl={s:TB.closes(s)[np.minimum(ends,len(TB.closes(s))-1)] for s in COINS};P=pd.DataFrame(cl);R=P.pct_change();b=P['BTCUSDT'];f=pd.DataFrame(index=range(D))
    for k in (1,3,7,14,30):f[f'btc_r{k}']=b.pct_change(k)
    br=b.pct_change();f['btc_v7']=br.rolling(7).std();f['btc_v30']=br.rolling(30).std();f['btc_m50']=b/b.rolling(50).mean()-1;f['btc_m200']=b/b.rolling(200,min_periods=100).mean()-1
    f['above20']=(P>P.rolling(20).mean()).mean(1);f['above50']=(P>P.rolling(50).mean()).mean(1);r7=P.pct_change(7);f['r7_mean']=r7.mean(1);f['r7_disp']=r7.std(1)
    idx=R.mean(1);f['corr30']=pd.concat([R[c].rolling(30).corr(idx) for c in R],axis=1).mean(1)
    fu=[]
    for s in COINS:
        _,fc=PBOT.load_coin(s);m=np.minimum(ends,len(fc)-1);fu.append(fc[m]-fc[np.maximum(m-3*1440,0)])
    f['fund3']=np.nanmean(np.array(fu),0)
    S=sentiment();dates=pd.date_range(START,periods=D)
    fng=pd.Series(S['fng']);fng.index=pd.to_datetime(fng.index);fng=fng.sort_index().reindex(dates,method='ffill')
    st=pd.Series(S['stable']);st.index=pd.to_datetime(st.index);st=st.sort_index().reindex(dates,method='ffill')
    f['fng']=fng.to_numpy();f['fng_chg7']=(fng-fng.shift(7)).to_numpy();f['stable_g30']=(st/st.shift(30)-1).to_numpy()
    s=pd.Series(rr);f['sys_r5']=s.rolling(5).sum();f['sys_r10']=s.rolling(10).sum();f['sys_r30']=s.rolling(30).sum();f['sys_dd']=ref/np.maximum.accumulate(ref)-1;f['sys_v20']=s.rolling(20).std()
    nl=np.zeros(D);ns=np.zeros(D);oR=np.zeros(D)
    for l in legs:
        d0=l['em']//1440;d1=min(l['xm']//1440,D)
        if d1<=d0:continue
        dd=np.arange(d0,d1);(nl if l['side']>0 else ns)[dd]+=1;oR[dd]+=l['side']*(cl[l['coin']][dd]-l['entry'])/(l['entry']*l['stop_frac']) if l['coin'] in cl else 0.
    f['open_long']=nl;f['open_short']=ns;f['open_R']=oR;f['open_R_chg5']=pd.Series(oR).diff(5)
    y=s.rolling(20).sum().shift(-20).to_numpy();return f.replace([np.inf,-np.inf],np.nan),y

def prod_score(X):
    m=json.loads((HERE/'risk_ai_r20.json').read_text());q=np.asarray(m['quantiles']);out=np.full(D,np.nan)
    A=X[m['features']].to_numpy()
    for d in range(D):
        x=[v if np.isfinite(v) else med for v,med in zip(A[d],m['medians'])];s=m['baseline']
        for t in m['trees']:
            i=0
            while not t['leaf'][i]:i=t['l'][i] if x[t['f'][i]]<=t['t'][i] else t['r'][i]
            s+=t['v'][i]
        out[d]=float(np.clip(np.interp(s,q,np.linspace(0,1,len(q))),0,1))
    return out

def wf_score(X,y):
    from sklearn.ensemble import HistGradientBoostingRegressor
    days=np.arange(D);p=np.full(D,np.nan);diag={}
    for fn,(a,b) in FOLDS.items():
        te=(days>=a)&(days<b);tr=((days>b+30)|(days+20<a-30)) if fn=='2022' else (days+20<a);tr&=(days>=60)&np.isfinite(y)
        med=X[tr].median();A=X.fillna(med).to_numpy()
        m=HistGradientBoostingRegressor(max_depth=3,max_iter=250,learning_rate=.03,min_samples_leaf=60,random_state=0).fit(A[tr],y[tr])
        ptr=np.sort(m.predict(A[tr]));p[te]=np.searchsorted(ptr,m.predict(A[te]),side='right')/len(ptr)
        ok=te&np.isfinite(y);diag[fn]=dict(train_days=int(tr.sum()),corr_with_next20=float(np.corrcoef(p[ok],y[ok])[0,1]))
    return p,diag

def gmap(p):
    v=np.where(~np.isfinite(p),1.,np.where(p<.3,0.,np.where(p>.7,1.4,1.)));g=np.ones(D);g[1:]=v[:-1];return g

def run(legs,ctrl,a):
    r=E.period(legs,np.ones(len(legs)),a*1440,None,ctrl);t=r.get('trades');r.pop('daily',None);return r

def main():
    OUT.mkdir(parents=True,exist_ok=True);legs=new_legs();X,y=features(legs)
    pp=prod_score(X);pw,diag=wf_score(X,y);ok=np.isfinite(y)
    diag['prod_corr_with_next20_in_sample']={fn:float(np.corrcoef(pp[(np.arange(D)>=a)&(np.arange(D)<b)&ok],y[(np.arange(D)>=a)&(np.arange(D)<b)&ok])[0,1]) for fn,(a,b) in FOLDS.items()}
    print('AI diagnostics',json.dumps(diag),flush=True)
    variants={'no F':{},'F (shipped AI model, in-sample)':dict(CTRL,g=gmap(pp)),'F (walk-forward AI)':dict(CTRL,g=gmap(pw)),
              'F without AI (vol target + brake + streak)':dict(CTRL),'no F, scale x1.41 only':dict(scale=1.41)}
    res=dict(ai=diag,runs={})
    for start,lab in ((FOLDS['2022'][0],'from 2022-01-01'),(0,'from 2021-10-05')):
        for nm,c in variants.items():
            r=run(legs,c,start);res['runs'][f'{lab} | {nm}']=r
            print(f"{lab} | {nm:44s} final {r['final']:>12,.0f} CAGR {r['cagr']:6.1f}% DD {r['dd']:6.1f}% Calmar {r['calmar']:5.2f} months+ {r['mpos']:3.0f}% worst month {r['mworst']:+5.1f}% trades {r['trades']} | "+' '.join(f"{yy}:{v['ret']:+.0f}%/{v['dd']:.1f}" for yy,v in r['years'].items()),flush=True)
    (OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
