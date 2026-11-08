"""Fourth bot (1h), pre-declared before any result was seen: rule-based trend candidates scored by machine learning and a light
computer-vision model, traded on the same 35 coins and the same shared paper account as the three bots.
CANDIDATES (closed 1h bars): long when the close breaks above the highest high of the previous 48 hours AND the last closed 4h
close is above its EMA50 AND the last closed daily close is above its EMA50 (short: mirror). One position per coin.
ENTRY at the next 1h open (+2 bps slippage); stop 2 x ATR14(1h) (at least 0.4%); after every 1h close the stop trails to
best close - 3 x ATR (long; mirror for short), never looser; time stop at the close of the 120th hour; stop fills at the stop or
the open if gapped; 0.06% fee per side, 2 bps slippage per fill, funding.
SCORES (trained on candidates whose trade EXITED before the test year; walk-forward 2023 / 2024 / 2025-26):
  gbm    gradient boosting classifier for 'trade ends >= 2 R' on ~120 features: 1h features (ml_short set), the 48 4h criteria,
         15 sentiment criteria, 30-day momentum rank, breakout quality ((close - level)/ATR, ATR/close)
  vision small 2-D CNN on the rendered 2 x 32 x 64 candlestick image of the last 64 hours (mirrored for shorts) + volume and taker
         rows, same target (Jiang-Kelly-Xiu style, image only)
  ens    average of the two training percentiles
POLICIES: raw (every candidate), skip30 / skip50 (no trade below the 30th / 50th training percentile), skip50+size (risk x
(0.5 + pct) on the rest). Risk 0.4% per trade (the bot's own risk), sizing / margin cap / costs as the shared-account replay.
PASS: stand-alone net profit > 0 in every fold AND, added to the three bots, Calmar above the three bots alone with max DD not
worse by more than 2 pp, in every fold.
"""
import sys,json,time,warnings
import numpy as np,pandas as pd
from pathlib import Path
from numba import njit
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import torch,torch.nn as nn
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, win_prob_model as W, five_year_report as FY, three_bots_replay as TB, ml_nn as NN, ml_short as MS, criteria_lib as C, sentiment_lib as SL, live_monitor_study as LM, pabench as PB
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
OUT=ROOT/'high_cagr/output/ideas/h1_bot';RISK=.004;FEE=.0006;SLIP=.0002
TB.DEFAULT['h1']=RISK
torch.set_num_threads(4);torch.manual_seed(0)

def atr14(h,l,c):
    tr=np.maximum(h-l,np.maximum(np.abs(h-np.roll(c,1)),np.abs(l-np.roll(c,1))));tr[0]=h[0]-l[0];a=np.full(len(c),np.nan);a[13]=tr[:14].mean()
    for i in range(14,len(c)):a[i]=(a[i-1]*13+tr[i])/14
    return a

@njit(cache=True)
def engine(o,h,l,c,atr,sig,minstop):
    n=len(c);out=np.zeros((n,8));k=0;t=50
    while t<n-2:
        s=sig[t]
        if s==0 or not atr[t]>0:t+=1;continue
        e=o[t+1]*(1+s*2e-4);dist=max(2*atr[t],minstop*e);stop=e-s*dist;best=e;x=-1;xp=0.;why=0
        for k2 in range(t+1,min(t+1+120,n)):
            if (s==1 and l[k2]<=stop) or (s==-1 and h[k2]>=stop):
                op=o[k2] if k2>t+1 else e
                xr=min(op,stop) if s==1 else max(op,stop);x=k2;xp=xr*(1-s*2e-4);why=1;break
            best=max(best,c[k2]) if s==1 else min(best,c[k2]);ns=best-s*3*atr[k2]
            if s*(ns-stop)>0:stop=ns
            if k2-t>=120:x=k2;xp=c[k2]*(1-s*2e-4);why=2;break
        if x<0:x=n-1;xp=c[n-1];why=3
        out[k,0]=t;out[k,1]=x;out[k,2]=s;out[k,3]=e;out[k,4]=xp;out[k,5]=dist/e;out[k,6]=why;k+=1;t=x+1
    return out[:k]

def candidates():
    legs=[];daily={s:PB._px(s)[1439::1440,3] for s in C.COINS}
    for s in C.COINS:
        H=NN.hourly(s);o,h,l,c=H[0],H[1],H[2],H[3];n=len(c);a=atr14(h,l,c)
        hi48=pd.Series(h).shift(1).rolling(48).max().to_numpy();lo48=pd.Series(l).shift(1).rolling(48).min().to_numpy()
        B=PB._bars(s);b4=np.minimum(((np.arange(n)+1)*60)//240-1,len(B['c'])-1);up4=B['c'][b4]>B['e50'][b4];dn4=B['c'][b4]<B['e50'][b4]
        dc=daily[s];de=pd.Series(dc).ewm(span=50,adjust=False).mean().to_numpy();d=np.clip((np.arange(n)+1)//24-1,0,len(dc)-1);upd=dc[d]>de[d];dnd=dc[d]<de[d]
        sig=np.where((c>hi48)&up4&upd,1,np.where((c<lo48)&dn4&dnd,-1,0)).astype(np.int64);sig[:300]=0
        T=engine(o,h,l,c,a,sig,.004);fc=LM.fc(s)
        for i,r in enumerate(T):
            t,x,sd,e,xp,sf=int(r[0]),int(r[1]),int(r[2]),r[3],r[4],r[5];em=(t+1)*60;xm=x*60+59
            unit=sd*(xp-e)-(e+xp)*FEE-sd*e*(fc[min(xm+1,len(fc)-1)]-fc[em])
            legs.append(dict(bot='h1',coin=s,side=sd,em=em,xm=xm,entry=float(e),unit=float(unit),stop_frac=float(sf),risk_scale=1.,root=('h1',s,i),is_add=False,t=t,
                             brk=float(((c[t]-(hi48[t] if sd>0 else lo48[t]))*sd)/a[t]),atrc=float(a[t]/c[t])))
    return legs

def features(legs):
    by={}
    for j,l in enumerate(legs):by.setdefault(l['coin'],[]).append(j)
    rows=[None]*len(legs);xs,_,_,_=__import__('high_cagr.ideas.ml_xsec',fromlist=['x']).build();mom=xs.pivot(index='day',columns='coin',values='r30')
    btc,_=MS.feats_btc(4)
    for s,js in by.items():
        F,_=MS.feats(s,4,btc,np.full(len(NN.hourly(s)[3]),np.nan));F=F.drop(columns=['y','fng'])
        for j in js:
            l=legs[j];t=l['t'];sd=l['side'];r=F.iloc[t].to_dict();r={k:(v*sd if k.startswith(('r','tb','ema','btc','lsg','lst','tls','fund')) and k not in ('range','relvol') else v) for k,v in r.items()}
            b4=(l['em']//240)-1;r.update({f'c4_{k}':v for k,v in C.at(s,b4,sd,l['stop_frac'],'pa').items() if not k.startswith('bot')});r.update(SL.at(s,b4,sd))
            dd=l['em']//1440-1;m=mom.loc[dd,s] if dd in mom.index else np.nan;r['mom30']=m if sd>0 else (1-m if np.isfinite(m) else np.nan)
            r['brk']=l['brk'];r['atrc']=l['atrc'];r['side']=sd;rows[j]=r
    return pd.DataFrame(rows).astype(float).replace([np.inf,-np.inf],np.nan)

def images(legs):
    X=np.zeros((len(legs),2,32,64),np.float32);V=np.zeros((len(legs),2,64),np.float32)
    for j,l in enumerate(legs):
        H=NN.hourly(l['coin']);t=l['t'];a=t-63
        if a<1:continue
        o,h,lo,c,v,tb=H[:,a:t+1];s=l['side'];cl=c[-1]
        tr=lambda x:s*np.log(x/cl);hh,ll=(tr(h),tr(lo)) if s>0 else (tr(lo),tr(h));oo,cc=tr(o),tr(c)
        seq=torch.from_numpy(np.stack([oo,hh,ll,cc]+[np.zeros(64)]*4)[None].astype(np.float32));X[j]=NN.render(seq)[0].numpy()
        V[j,0]=np.log((v+1)/(v.mean()+1));V[j,1]=s*(np.where(v>0,tb/np.maximum(v,1e-12),.5)-.5)*4
    return X,V

class Vision(nn.Module):
    def __init__(self):
        super().__init__()
        self.f=nn.Sequential(nn.Conv2d(2,16,(5,3),padding=(2,1)),nn.BatchNorm2d(16),nn.LeakyReLU(),nn.MaxPool2d((2,1)),nn.Conv2d(16,32,(5,3),padding=(2,1)),nn.BatchNorm2d(32),nn.LeakyReLU(),nn.MaxPool2d((2,1)),
                             nn.Conv2d(32,64,(5,3),padding=(2,1)),nn.BatchNorm2d(64),nn.LeakyReLU())
        self.v=nn.Sequential(nn.Conv1d(2,16,5,padding=2),nn.ReLU())
        self.h=nn.Sequential(nn.Dropout(.3),nn.Linear(64*2+16*2,32),nn.ReLU(),nn.Linear(32,1))
    def forward(self,x,v):
        f=self.f(x);g=self.v(v);return self.h(torch.cat([f.mean((2,3)),f.amax((2,3)),g.mean(2),g.amax(2)],1)).squeeze(1)

def fit_vision(X,V,y,val):
    net=Vision();opt=torch.optim.Adam(net.parameters(),1e-3,weight_decay=1e-4);lf=nn.BCEWithLogitsLoss(pos_weight=torch.tensor((1-y.mean())/max(y.mean(),1e-3)))
    tr=np.where(~val)[0];va=np.where(val)[0];best=(1e9,None);T=torch.from_numpy
    for ep in range(8):
        net.train();np.random.RandomState(ep).shuffle(tr)
        for i in range(0,len(tr),256):
            b=tr[i:i+256];opt.zero_grad();loss=lf(net(T(X[b]),T(V[b])),T(y[b].astype(np.float32)));loss.backward();opt.step()
        net.eval()
        with torch.no_grad():vl=float(lf(net(T(X[va]),T(V[va])),T(y[va].astype(np.float32))).item())
        if vl<best[0]:best=(vl,{k:v.clone() for k,v in net.state_dict().items()})
    net.load_state_dict(best[1]);net.eval();return net
def pred_vision(net,X,V):
    with torch.no_grad():return np.concatenate([torch.sigmoid(net(torch.from_numpy(X[i:i+2048]),torch.from_numpy(V[i:i+2048]))).numpy() for i in range(0,len(X),2048)])

def pct_of(ref,p):s=np.sort(ref);return np.searchsorted(s,p,side='right')/len(s)
def stats_only(legs,a,b):
    if not legs:return dict(final=10000.,cagr=0.,dd=0.,calmar=0.,trades=0,win=0.,pf=0.)
    r=W.run_period(legs,[1.]*len(legs),a,b);r.pop('daily');return r

def main():
    OUT.mkdir(parents=True,exist_ok=True);t0=time.time();H1=candidates()
    R=np.array([l['unit']/(l['entry']*l['stop_frac']) for l in H1]);y=(R>=2).astype(int);em=np.array([l['em'] for l in H1]);xm=np.array([l['xm'] for l in H1])
    print('candidates',len(H1),'mean R',round(R.mean(),3),'win',round((R>0).mean(),3),'big share',round(y.mean(),3),f'({time.time()-t0:.0f}s)',flush=True)
    X=features(H1);print('features',X.shape,f'({time.time()-t0:.0f}s)',flush=True);IM,VV=images(H1);print('images built',f'({time.time()-t0:.0f}s)',flush=True)
    L=MD.all_legs();dep=[l for l in L if not l['aug']];res={}
    for fn,(a,b) in WF.FOLDS.items():
        tr=xm<a;te=(em>=a)&((em<b) if b else True);base3=WF.replay(dep,a,b);out={'bots_only':base3}
        Xf=X.fillna(X[tr].median()).to_numpy()
        g=HistGradientBoostingClassifier(max_depth=4,max_iter=300,learning_rate=.03,min_samples_leaf=50,random_state=0).fit(Xf[tr],y[tr]);pg=g.predict_proba(Xf)[:,1]
        cut=np.quantile(em[tr],.85);val=em[tr]>=cut;net=fit_vision(IM[tr],VV[tr],y[tr],val);pv=pred_vision(net,IM,VV)
        scores={'gbm':pct_of(pg[tr],pg),'vision':pct_of(pv[tr],pv)};scores['ens']=(scores['gbm']+scores['vision'])/2;scores['ens']=pct_of(scores['ens'][tr],scores['ens'])
        aucs={k:float(roc_auc_score(y[te],v[te])) for k,v in scores.items()};out['auc']=aucs
        tl=[H1[i] for i in np.where(te)[0]];raw=stats_only(tl,a,b);both=WF.replay(dep+tl,a,b);out['raw']=dict(alone=raw,with_bots=both)
        print(f'fold {fn}: candidates train {tr.sum()} test {te.sum()} | AUC gbm {aucs["gbm"]:.3f} vision {aucs["vision"]:.3f} ens {aucs["ens"]:.3f} | bots only {base3["final"]:,.0f} / {base3["dd"]:.1f} / {base3["calmar"]:.2f}',flush=True)
        print(f'  raw          alone {raw["final"]:>9,.0f} DD {raw["dd"]:6.1f} trades {raw["trades"]:5d} win {raw["win"]:4.1f}% | +bots {both["final"]:>9,.0f} / {both["dd"]:.1f} / {both["calmar"]:.2f}',flush=True)
        for sk,p in scores.items():
            for pol in ('skip30','skip50','skip50+size'):
                q=.3 if pol=='skip30' else .5;keep=[i for i in np.where(te)[0] if p[i]>=q]
                legs=[dict(H1[i],risk_scale=(.5+p[i]) if pol=='skip50+size' else 1.) for i in keep]
                al=stats_only(legs,a,b);wb=WF.replay(dep+legs,a,b);ok=al['final']>10000 and WF.judge(wb,base3);out[f'{sk}|{pol}']=dict(alone=al,with_bots=wb,passed=ok)
                print(f'  {sk:6s} {pol:11s} alone {al["final"]:>9,.0f} DD {al["dd"]:6.1f} trades {al["trades"]:5d} win {al["win"]:4.1f}% | +bots {wb["final"]:>9,.0f} / {wb["dd"]:.1f} / {wb["calmar"]:.2f} {"PASS" if ok else ""}',flush=True)
        res[fn]=out;(OUT/'result.json').write_text(json.dumps(res,indent=1,default=float))
    print('time',round(time.time()-t0),'s')
if __name__=='__main__':main()
