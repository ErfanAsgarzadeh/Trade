"""Neural in-trade decision models (pre-declared before running), same walk-forward folds, labels, policies and pass rule as
ml_walkforward.py. Inputs per state (every 4th hour of a position, from hour 4):
  sequence: the last 64 closed 1h bars of the coin, mirrored for shorts (side x log price), scaled by the window's 1h return std:
            open/high/low/close relative to the last close, log relative volume, taker buy share - 0.5 (signed), in-position
            flag, unrealised R of the position at each bar (0 before entry)
  tabular : the same 81 features as the tree/linear models (standardised with TRAIN statistics)
MODELS
  mlp   : tabular only (control: what the network adds without seeing the chart)
  cnn1d : dilated 1-D CNN over the sequence + tabular head
  image : 'computer vision' - every sequence is rendered on the fly as a 2 x 32 x 64 candlestick image (channel 0 = high-low
          wick, channel 1 = open-close body), 2-D CNN in the style of Jiang, Kelly & Xiu (2023, 'Re-)Imag(in)ing Price Trends'),
          + tabular head
Targets v_hold and v_tight (clipped [-3, 10]), Huber loss, Adam 1e-3, batch 512, up to 4 epochs, the epoch with the lowest
validation loss (last 10% of the training legs by entry time) is kept. Training rows capped at 300k (random, seed 0).
"""
import sys,json,time,warnings,functools
import numpy as np,pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import torch,torch.nn as nn
from high_cagr.ideas import ml_data as MD, ml_walkforward as WF, live_monitor_study as LM, pabench as PB
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
torch.set_num_threads(4);torch.manual_seed(0);np.random.seed(0)
OUT=MD.OUT;WIN=64;NCH=8

@functools.lru_cache(None)
def hourly(s):
    P=PB._px(s);n=len(P)//60;Q=P[:n*60].reshape(n,60,4);o=Q[:,0,0];h=Q[:,:,1].max(1);l=Q[:,:,2].min(1);c=Q[:,-1,3]
    tk=MD.taker1h(s);v=tk[1][:n];tb=np.where(v>0,tk[0][:n]/np.maximum(v,1e-12),.5)
    return np.stack([o,h,l,c,v,tb]).astype(np.float64)

def sequences(S,L):
    X=np.zeros((len(S),NCH,WIN),np.float32)
    for k,(j,m) in enumerate(zip(S.leg.to_numpy(),S.m.to_numpy())):
        l=L[j];s=l['side'];H=hourly(l['coin']);hb=(m+1)//60-1;a=hb-WIN+1
        if a<1:continue
        o,h,lo,c,v,tb=H[:,a:hb+1];cl=c[-1];lr=lambda x:s*np.log(x/cl)
        if s>0:hh,ll=lr(h),lr(lo)
        else:hh,ll=lr(lo),lr(h)
        r=np.diff(np.log(H[3,a-1:hb+1]));sd=r.std()+1e-9
        eh=(l['em']//60);inpos=(np.arange(a,hb+1)>=eh).astype(np.float32)
        unr=inpos*s*(c-l['entry'])/(l['entry']*l['stop_frac'])
        X[k]=np.stack([lr(o)/sd,hh/sd,ll/sd,lr(c)/sd,np.log((v+1)/(v.mean()+1)),s*(tb-.5)*4,inpos,np.clip(unr,-5,20)/5])
    return X

def render(seq):
    """seq (B,8,64) -> (B,2,32,64) candlestick image, rows scaled to the window's low..high."""
    o,h,l,c=seq[:,0],seq[:,1],seq[:,2],seq[:,3];lo=l.min(1,keepdim=True)[0];hi=h.max(1,keepdim=True)[0];sc=(hi-lo).clamp_min(1e-6)
    q=lambda x:((x-lo)/sc*31).round()
    rows=torch.arange(32,dtype=torch.float32).view(1,32,1);hq,lq,oq,cq=q(h).unsqueeze(1),q(l).unsqueeze(1),q(o).unsqueeze(1),q(c).unsqueeze(1)
    wick=((rows>=lq)&(rows<=hq)).float();body=((rows>=torch.minimum(oq,cq))&(rows<=torch.maximum(oq,cq))).float()
    return torch.stack([wick,body],1).flip(2)

class Net(nn.Module):
    def __init__(self,kind,nt):
        super().__init__();self.kind=kind;w=0
        if kind=='cnn1d':
            self.f=nn.Sequential(nn.Conv1d(NCH,32,5,padding=2),nn.ReLU(),nn.Conv1d(32,32,5,padding=4,dilation=2),nn.ReLU(),nn.Conv1d(32,64,5,padding=8,dilation=4),nn.ReLU());w=128
        if kind=='image':
            self.f=nn.Sequential(nn.Conv2d(2,16,(5,3),padding=(2,1)),nn.BatchNorm2d(16),nn.LeakyReLU(),nn.MaxPool2d((2,1)),
                                 nn.Conv2d(16,32,(5,3),padding=(2,1)),nn.BatchNorm2d(32),nn.LeakyReLU(),nn.MaxPool2d((2,1)),
                                 nn.Conv2d(32,64,(5,3),padding=(2,1)),nn.BatchNorm2d(64),nn.LeakyReLU());w=128+4   # + position channels summary
        self.h=nn.Sequential(nn.Linear(nt+w,128),nn.ReLU(),nn.Dropout(.1),nn.Linear(128,64),nn.ReLU(),nn.Linear(64,2))
    def forward(self,seq,tab):
        if self.kind=='mlp':z=tab
        elif self.kind=='cnn1d':
            f=self.f(seq);z=torch.cat([f.mean(2),f.amax(2),tab],1)
        else:
            f=self.f(render(seq));pos=seq[:,6:8];z=torch.cat([f.mean((2,3)),f.amax((2,3)),pos.mean(2),pos[:,:,-1],tab],1)
        return self.h(z)

def fit(kind,Xs,Xt,Y,val):
    net=Net(kind,Xt.shape[1]);opt=torch.optim.Adam(net.parameters(),1e-3);lf=nn.HuberLoss(delta=1.)
    tr=np.where(~val)[0];va=np.where(val)[0];best=(1e9,None);T=lambda a:torch.from_numpy(a)
    for ep in range(4):
        net.train();np.random.shuffle(tr);t0=time.time()
        for i in range(0,len(tr),512):
            b=tr[i:i+512];opt.zero_grad();loss=lf(net(T(Xs[b]),T(Xt[b])),T(Y[b]));loss.backward();opt.step()
        net.eval()
        with torch.no_grad():vl=float(np.mean([lf(net(T(Xs[va[i:i+4096]]),T(Xt[va[i:i+4096]])),T(Y[va[i:i+4096]])).item() for i in range(0,len(va),4096)]))
        print(f'    {kind} epoch {ep} val loss {vl:.4f} ({time.time()-t0:.0f}s)',flush=True)
        if vl<best[0]:best=(vl,{k:v.clone() for k,v in net.state_dict().items()})
    net.load_state_dict(best[1]);net.eval();return net

def predict(net,Xs,Xt):
    with torch.no_grad():return np.concatenate([net(torch.from_numpy(Xs[i:i+4096]),torch.from_numpy(Xt[i:i+4096])).numpy() for i in range(0,len(Xs),4096)])

def main(kinds=('mlp','cnn1d','image')):
    L=MD.all_legs();dep_n=sum(1 for l in L if not l['aug']);dep=L[:dep_n]
    S=pd.read_parquet(OUT/'states.parquet');feats=[f for f in MD.FEATS if f in S.columns]
    em=np.array([l['em'] for l in L]);xm=np.array([l['xm'] for l in L]);S['em']=em[S.leg];S['xm']=xm[S.leg]
    S=S[S.hours>=4].reset_index(drop=True);S=S[(S.groupby('leg').cumcount()%4)==0].reset_index(drop=True);print('states (every 4h)',len(S),flush=True)
    P=lambda j,m:LM.px(L[j]['coin'])[m,3];res={}
    for fn,(a,b) in WF.FOLDS.items():
        trm=(S.xm<a).to_numpy();te=((S.em>=a)&((S.em<b) if b else True)&(S.leg<dep_n)).to_numpy()
        tri=np.where(trm)[0]
        if len(tri)>300000:tri=np.sort(np.random.RandomState(0).choice(tri,300000,replace=False))
        Str=S.iloc[tri];Ste=S[te];cut=np.quantile(Str.em,.9);val=(Str.em>=cut).to_numpy()
        Xt=S[feats].astype(np.float32).replace([np.inf,-np.inf],np.nan);med=Xt.iloc[tri].median();mu=Xt.iloc[tri].fillna(med).mean();sd=Xt.iloc[tri].fillna(med).std()+1e-6
        tab=lambda idx:((Xt.iloc[idx].fillna(med)-mu)/sd).clip(-8,8).to_numpy(np.float32)
        t0=time.time();Xs_tr=sequences(Str,L);Xs_te=sequences(Ste,L);print(f'fold {fn}: train {len(tri)} test {te.sum()} sequences built {time.time()-t0:.0f}s',flush=True)
        Ttr=tab(tri);Tte=tab(np.where(te)[0]);Y=np.stack([Str.v_hold.clip(-3,10),Str.v_tight.clip(-3,10)],1).astype(np.float32)
        base=WF.replay(dep,a,b);out=dict(base=base,models={})
        for kind in kinds:
            net=fit(kind,Xs_tr,Ttr,Y,val);pr=predict(net,Xs_te,Tte);ph,pt=pr[:,0],pr[:,1];ph_tr=predict(net,Xs_tr[:50000],Ttr[:50000])[:,0]
            yh=Ste.v_hold.to_numpy();yt=Ste.v_tight.to_numpy();auc=float(roc_auc_score(yh>0,ph));ich=float(spearmanr(ph,yh)[0]);ict=float(spearmanr(pt-ph,yt-yh)[0])
            St=Ste.copy();St['ph']=ph;St['pt']=pt;rs_={}
            for pol in ('decide','tighten30'):
                if pol=='decide':act=(np.maximum(pt,0)-ph)>.10;St['kind']=np.where(pt>=0,'TIGHTEN','EXIT')
                else:act=ph<np.quantile(ph_tr,.3);St['kind']='TIGHTEN'
                trig=WF.triggers(St,act,dep_n,P);r=WF.replay(WF.apply(dep,trig),a,b);r['acted']=len(trig);r['pass']=WF.judge(r,base);rs_[pol]=r
                print(f'  {kind:6s} {pol:9s} AUC(hold>0) {auc:.3f} IC hold {ich:+.3f} IC tight-hold {ict:+.3f} | final {r["final"]:>9,.0f} DD {r["dd"]:6.1f} Calmar {r["calmar"]:5.2f} acted {len(trig):4d} {"PASS" if r["pass"] else ""} (base Calmar {base["calmar"]:.2f} DD {base["dd"]:.1f})',flush=True)
            out['models'][kind]=dict(auc_hold=auc,ic_hold=ich,ic_tight_minus_hold=ict,policies=rs_)
        res[fn]=out;(OUT/'nn_walkforward.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
