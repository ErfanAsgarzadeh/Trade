"""Exhaustive structural ablation suite; primary selection is full-period net PnL."""
from pathlib import Path
import sys, json, math, itertools, copy, importlib.util
import numpy as np
import pandas as pd
from numba import njit
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT.parent/'btc_backtest'))
import backtest as bt
from kernel import simulate
spec=importlib.util.spec_from_file_location('frozen_engine',ROOT/'baseline/lbank_bot.py')
frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)
BASE=json.loads((ROOT/'baseline/config.json').read_text());BASE['symbols']=[bt.SYMBOL]
bt.CONFIG=copy.deepcopy(BASE)

@njit(cache=True)
def rolling_adx(high,low,close,period=14,window=199):
    out=np.full(len(high),np.nan)
    for end in range(window-1,len(high)):
        start=end-window+1;plus=0.;minus=0.;tr=0.;adx=0.;dxsum=0.;dxcount=0
        for j in range(start+1,end+1):
            up=high[j]-high[j-1];down=low[j-1]-low[j]
            pdm=up if up>down and up>0 else 0.
            mdm=down if down>up and down>0 else 0.
            true=max(high[j]-low[j],abs(high[j]-close[j-1]),abs(low[j]-close[j-1]))
            offset=j-start
            if offset<period:plus+=pdm;minus+=mdm;tr+=true;continue
            plus=plus-plus/period+pdm;minus=minus-minus/period+mdm;tr=tr-tr/period+true
            dx=100*abs(plus-minus)/(plus+minus) if plus+minus>0 else 0.
            if dxcount<period:
                dxsum+=dx;dxcount+=1
                if dxcount==period:adx=dxsum/period
            else:adx=(adx*(period-1)+dx)/period
        out[end]=adx
    return out


def build_features():
    output=ROOT/'features.npz'
    if output.exists():
        data=np.load(output)
        frames={}
        for name in ['hourly','fourhour']:
            frames[name]=pd.DataFrame(data[name],columns=json.loads(str(data[name+'_columns'])))
        return data['prices'],data['funding'],frames['hourly'],frames['fourhour']
    minutes=bt.load_minutes();h=bt.prepare_indicators(bt.aggregate(minutes,'1h'));q=bt.prepare_indicators(bt.aggregate(minutes,'4h'))
    q['adx']=rolling_adx(q.high.to_numpy(),q.low.to_numpy(),q.close.to_numpy())
    selected=minutes[(minutes.timestamp>=bt.START)&(minutes.timestamp<bt.END)]
    prices=selected[['open','high','low','close']].to_numpy(dtype=float)
    funding=np.full(len(prices),np.nan)
    for timestamp,rate in bt.load_funding().items():
        index=(timestamp-bt.START)//60000
        if 0<=index<len(funding):funding[index]=rate
    np.savez_compressed(output,prices=prices,funding=funding,hourly=h.to_numpy(),fourhour=q.to_numpy(),
                        hourly_columns=json.dumps(list(h.columns)),fourhour_columns=json.dumps(list(q.columns)))
    print('Prepared cached minute data and exact 199-bar indicators.',flush=True)
    return prices,funding,h,q


def signals_for(mode,slope,adx,h,q):
    entry=h if mode=='MTF' else q;tfms=3600000 if mode=='MTF' else 14400000
    regimes=[]
    for i in range(len(q)):
        side=frozen.regime(q.iloc[max(0,i-30):i+1],BASE)
        if side and slope:
            b=q.iloc[i]
            if i<3:side=None
            elif side=='long' and not (b.kijun>=q.iloc[i-3].kijun and b.tenkan>q.iloc[i-2].tenkan):side=None
            elif side=='short' and not (b.kijun<=q.iloc[i-3].kijun and b.tenkan<q.iloc[i-2].tenkan):side=None
        if side and adx and (not math.isfinite(q.iloc[i].adx) or q.iloc[i].adx<adx):side=None
        regimes.append(side)
    close_times=entry.timestamp.to_numpy(dtype='int64')+tfms
    matched=np.searchsorted(q.timestamp.to_numpy(dtype='int64')+14400000,close_times,side='right')-1
    indices=[];values=[];f=BASE['filters_and_triggers']
    for i in range(198,len(entry)):
        timestamp=int(close_times[i])
        if not bt.START<=timestamp<bt.END or matched[i]<0:continue
        side=regimes[matched[i]]
        if side is None:continue
        b=entry.iloc[i]
        if abs(b.close-b.kijun)>f['max_kijun_extension_atr']*b.atr:continue
        if not f[f'{side}_rsi_min']<=b.rsi<=f[f'{side}_rsi_max']:continue
        if side=='long' and not (b.low<=b.kijun+f['kijun_touch_atr_tolerance']*b.atr and b.close>b.kijun):continue
        if side=='short' and not (b.high>=b.kijun-f['kijun_touch_atr_tolerance']*b.atr and b.close<b.kijun):continue
        if not frozen.entry_signal(entry.iloc[max(0,i-10):i+1].reset_index(drop=True),side,BASE):continue
        sign=1 if side=='long' else -1
        trigger=b.high+.05*b.atr if sign==1 else b.low-.05*b.atr
        stop=min(b.low,b.kijun)-.8*b.atr if sign==1 else max(b.high,b.kijun)+.8*b.atr
        indices.append((timestamp-bt.START)//60000);values.append([sign,trigger,stop])
    return np.asarray(indices,dtype=np.int64),np.asarray(values,dtype=float).reshape(-1,3)


def bars_for_engine(frame,minutes):
    # Each engine row references the bar that CLOSED at that boundary.
    total=(bt.END-bt.START)//(minutes*60000)+1
    times=bt.START+np.arange(total)*(minutes*60000)
    indices=np.searchsorted(frame.timestamp.to_numpy(dtype=np.int64)+minutes*60000,times,side='right')-1
    assert (indices>=0).all()
    return frame.iloc[indices][['kijun','atr','close']].to_numpy()

EXITS=[
 ('baseline',1.5,.5,0,.2,'entry',0),
 ('A2_quarter_entry',2.,.35,1,.6,'entry',0),('A25_quarter_entry',2.5,.35,1,.6,'entry',0),
 ('A2_confirm_entry',2.,.35,2,.6,'entry',0),('A25_confirm_entry',2.5,.35,2,.6,'entry',0),
 ('A2_quarter_4h',2.,.35,1,.6,'4h',0),('A25_quarter_4h',2.5,.35,1,.6,'4h',0),
 ('A2_confirm_4h',2.,.35,2,.6,'4h',0),('A25_confirm_4h',2.5,.35,2,.6,'4h',0),
 ('B_runner_entry',2.,0.,3,.5,'entry',0),('B_runner_hard3',2.,0.,3,.5,'entry',3),
 ('B_runner_hard4',2.,0.,3,.5,'entry',4),('B_runner_4h',2.,0.,3,.5,'4h',0),
 ('B_pure_kijun_entry',2.,0.,4,.5,'entry',0),('B_pure_kijun_4h',2.,0.,4,.5,'4h',0)]
MOMENTUM=[('none',False,0),('slope',True,0),('ADX20',False,20),('ADX25',False,25),('slope_ADX20',True,20),('slope_ADX25',True,25)]


def configuration(mode,exit_spec,stop,momentum):
    name,rr,pct,kind,buffer,trail,hard=exit_spec
    tf=60 if mode=='MTF' else 240
    return np.array([rr,pct,kind,buffer,tf if trail=='entry' else 240,hard,0 if stop=='none' else .012,
                     {'none':0,'widen':1,'reject':2}[stop]],dtype=float)


def summarize(a,trades,fills):
    pnls=trades[:,10];wins=pnls[pnls>0];losses=pnls[pnls<0]
    assert abs(a[0]-10000-pnls.sum())<1e-6
    return {'trades':len(trades),'win_rate_pct':float(len(wins)/len(pnls)*100) if len(pnls) else 0,
            'avg_win':float(wins.mean()) if len(wins) else 0,'avg_loss':float(losses.mean()) if len(losses) else 0,
            'fees':float(trades[:,8].sum()),'funding_pnl':float(a[7]),'gross_pnl':float(trades[:,7].sum()),
            'profit_factor':float(wins.sum()/-losses.sum()) if len(losses) else None,
            'max_dd_pct':float(a[2]*100),'net_profit':float(a[0]-10000),'return_pct':float((a[0]/10000-1)*100),
            'final_equity':float(a[0]),'kijun_break_exits':int((trades[:,11]==7).sum()),
            'runner_stop_exits':int(((trades[:,11]==3)&(trades[:,12]==3)).sum()),
            'setups':int(a[8]),'cancelled_setups':int(a[9]),'min_stop_rejections':int(a[10]),
            'missing_funding_proxy_events':int(a[11])}


def main():
    prices,funding,h,q=build_features();eb={'MTF':bars_for_engine(h,60),'SINGLE':bars_for_engine(q,240)}
    signals={}
    for mode,momentum in itertools.product(['MTF','SINGLE'],MOMENTUM):
        signals[(mode,momentum[0])]=signals_for(mode,momentum[1],momentum[2],h,q)
        print('Signals',mode,momentum[0],len(signals[(mode,momentum[0])][0]),flush=True)
    split=(int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)-bt.START)//60000
    periods={'full':(0,len(prices)),'train':(0,split),'validation':(split,len(prices))}
    baseline_cfg=configuration('MTF',EXITS[0],'none',MOMENTUM[0]);si,sv=signals[('MTF','none')]
    a,t,f,c=simulate(prices,bt.START,0,len(prices),si,sv,eb['MTF'],eb['SINGLE'],funding,baseline_cfg,60)
    baseline=summarize(a,t,f)
    expected=json.loads((ROOT.parent/'btc_backtest/output/summary.json').read_text())['scenarios'][1]
    assert baseline['trades']==expected['trades']
    assert abs(baseline['net_profit']-expected['net_profit'])<1e-7,(baseline,expected)
    assert abs(baseline['max_dd_pct']-expected['max_drawdown_pct'])<1e-7
    print('Baseline JIT matches original trade count, net PnL, DD exactly.',flush=True)
    cases=[];seen=set()
    for mode,exit_spec,stop,momentum in itertools.product(['MTF','SINGLE'],EXITS,['none','widen','reject'],MOMENTUM):
        cfg=configuration(mode,exit_spec,stop,momentum)
        key=(mode,tuple(cfg),momentum[0])
        if key in seen:continue
        seen.add(key)
        case={'id':f'{mode}__{exit_spec[0]}__{stop}__{momentum[0]}','mode':mode,'exit':exit_spec[0],
              'stop':stop,'momentum':momentum[0],'params':cfg.tolist()}
        si,sv=signals[(mode,momentum[0])]
        for name,(begin,end) in periods.items():
            a,t,f,c=simulate(prices,bt.START,begin,end,si,sv,eb[mode],eb['SINGLE'],funding,cfg,60 if mode=='MTF' else 240)
            case[name]=summarize(a,t,f)
        cases.append(case)
        if len(cases)%25==0:print('Completed cases:',len(cases),flush=True)
    cases.sort(key=lambda x:(x['full']['net_profit'],x['full']['profit_factor'] or 0),reverse=True)
    profit_winner=cases[0]
    pf_winner=max([x for x in cases if x['full']['profit_factor'] is not None],key=lambda x:x['full']['profit_factor'])
    train_winner=max(cases,key=lambda x:x['train']['net_profit'])
    for label,case in [('winner',profit_winner),('pf_winner',pf_winner),('train_winner',train_winner)]:
        si,sv=signals[(case['mode'],case['momentum'])]
        a,t,f,c=simulate(prices,bt.START,0,len(prices),si,sv,eb[case['mode']],eb['SINGLE'],funding,np.array(case['params']),60 if case['mode']=='MTF' else 240,trace=True)
        np.savez_compressed(ROOT/'output'/f'{label}_ledger.npz',trades=t,fills=f,equity=c)
    result={'start_utc':bt.iso(bt.START),'end_exclusive_utc':bt.iso(bt.END),'cases':len(cases),
            'selection_rule':'Highest full-period net profit; PF breaks ties. PF leader is also shown separately.',
            'baseline_regression_verified':True,'profit_winner':profit_winner,'pf_winner':pf_winner,'train_selected':train_winner,
            'train_end_exclusive':'2025-01-01T00:00:00+00:00','matrix':cases}
    (ROOT/'output/matrix.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    print('WINNER',json.dumps(profit_winner,indent=2),flush=True)
    print('PF WINNER',pf_winner['id'],pf_winner['full'],flush=True)
    print('TRAIN WINNER',train_winner['id'],train_winner['validation'],flush=True)

if __name__=='__main__':main()
