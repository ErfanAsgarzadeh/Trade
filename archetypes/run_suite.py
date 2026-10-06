"""Predeclared four-family grid. No parameter changes based on the results."""
from pathlib import Path
import sys,json,copy,itertools,hashlib
import numpy as np
import pandas as pd
from numba import njit
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT.parent/'lbank_project'))
import strategy_archetypes as shared
from kernel import simulate
START=int(pd.Timestamp('2021-10-05',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-10-05',tz='UTC').timestamp()*1000)
SPLIT=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
BASE=json.loads((ROOT.parent/'optimization/baseline/config.json').read_text())
SETTINGS={'standard':(9,26,52,26),'crypto':(20,60,120,30)}

@njit(cache=True)
def rolling_ema(close,period,window=199):
    out=np.full(len(close),np.nan);alpha=2/(period+1)
    for end in range(window-1,len(close)):
        start=end-window+1;value=0.
        for j in range(start,start+period):value+=close[j]/period
        for j in range(start+period,end+1):value=alpha*close[j]+(1-alpha)*value
        out[end]=value
    return out

def load_features():
    file=ROOT.parent/'optimization/features.npz'
    manifest=json.loads((ROOT.parent/'optimization/features_manifest.json').read_text())
    assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest['features_sha256']
    cache=np.load(file);frames={}
    for mode,name in [('MTF','hourly'),('SINGLE','fourhour')]:
        raw=pd.DataFrame(cache[name],columns=json.loads(str(cache[name+'_columns'])))
        for name,params in SETTINGS.items():
            frame=shared.add_features(raw)
            tenkan,kijun,b,disp=params
            for col,n in [('tenkan',tenkan),('kijun',kijun),('senkou_b_future',b)]:
                frame[col]=(frame.high.rolling(n).max()+frame.low.rolling(n).min())/2
            frame['senkou_a_future']=(frame.tenkan+frame.kijun)/2
            frame['senkou_a_curr']=frame.senkou_a_future.shift(disp)
            frame['senkou_b_curr']=frame.senkou_b_future.shift(disp)
            frame['kumo_top']=frame[['senkou_a_curr','senkou_b_curr']].max(axis=1,skipna=False)
            frame['kumo_bottom']=frame[['senkou_a_curr','senkou_b_curr']].min(axis=1,skipna=False)
            for n in [20,50]:frame[f'ema{n}']=rolling_ema(frame.close.to_numpy(),n)
            frames[mode,name]=frame
    return cache['prices'],cache['funding'],frames

def grid():
    cases=[]
    def add(family,mode,setting,entry,exit_name,stop='KIJUN',trail='KIJUN',h2=False,lookback=20):
        name=f'{family}__{mode}__{setting}__{entry}__{exit_name}__{stop}__{trail}'+(f'__H2{int(h2)}' if family=='EMA_PULLBACK' else '')+(f'__N{lookback}' if family=='DONCHIAN' else '')
        cases.append(dict(id=name,family=family,mode=mode,setting=setting,entry=entry,exit=exit_name,stop=stop,trail=trail,h2=h2,lookback=lookback))
    for mode,setting,entry,ex in itertools.product(['SINGLE','MTF'],SETTINGS,['KUMO_CROSS','TENKAN_RECLAIM'],['CLOSE_TRAIL','HARD3','HARD4']):add('ICHI_BREAKOUT',mode,setting,entry,ex)
    for mode,setting,entry,ex in itertools.product(['SINGLE','MTF'],SETTINGS,['MARKET','SIGNAL_BREAKOUT'],['CLOSE_TRAIL','HARD3','HARD4','BE2_TRAIL']):add('ICHI_PULLBACK',mode,setting,entry,ex)
    for mode,h2,ex,trail_setting in itertools.product(['SINGLE','MTF'],[False,True],['PARTIAL15','BE2_TRAIL'],[('EMA20','crypto'),('KIJUN','standard'),('KIJUN','crypto')]):
        trail,setting=trail_setting;add('EMA_PULLBACK',mode,setting,'SIGNAL_BREAKOUT',ex,'SIGNAL_BAR',trail,h2)
    for mode,setting,n,stop,trail in itertools.product(['SINGLE','MTF'],SETTINGS,[10,20],['KIJUN','ATR2'],['KIJUN','DONCHIAN10']):add('DONCHIAN',mode,setting,'MARKET','CLOSE_TRAIL' if trail=='KIJUN' else 'STOP_TRAIL',stop,trail,lookback=n)
    assert len(cases)==112
    return cases

def config_for(case):
    c=copy.deepcopy(BASE);c['symbols']=['BTC/USDT:USDT'];c['strategy_mode']['mode']=case['mode']
    i=c['ichimoku_params'];i.update(zip(['tenkan','kijun','senkou_b','displacement'],SETTINGS[case['setting']]))
    c['structural_filters']=dict(enable_htf_slope_filter=False,adx_period=14,min_htf_adx=0.)
    c['archetype_strategy']=dict(family=case['family'],entry_variant=case['entry'],donchian_lookback=case['lookback'],stop_source=case['stop'],trail_source=case['trail'],require_h2_l2=case['h2'],trail_close_only=case['exit']=='CLOSE_TRAIL',pending_policy='GTC_REGIME')
    breakout=case['entry']=='SIGNAL_BREAKOUT'
    c['al_brooks_filters'].update(enable_barb_wire_filter=False,require_h2_l2_pullback=False,require_signal_bar_breakout=breakout,stop_entry_atr_buffer=0.)
    c['filters_and_triggers'].update(long_rsi_min=38.,long_rsi_max=65.,short_rsi_min=35.,short_rsi_max=62.)
    r=c['risk_and_exit'];ex=case['exit']
    scheme='LEGACY' if ex=='PARTIAL15' else 'PURE_RUNNER' if ex=='BE2_TRAIL' else 'HARD_TARGET' if ex.startswith('HARD') else 'PURE_KIJUN'
    r.update(min_stop_distance_pct=.012,min_stop_policy='REJECT',sl_atr_buffer=0. if case['family']=='DONCHIAN' else .5,
       exit_scheme=scheme,breakeven_policy='ENTRY' if scheme=='LEGACY' else 'MILESTONE' if scheme=='PURE_RUNNER' else 'NONE',
       breakeven_trigger_rr=2.,tp1_rr_ratio=1.5 if scheme=='LEGACY' else 2.,tp1_close_pct=.5 if scheme=='LEGACY' else 0.,
       trail_atr_buffer=.2 if scheme=='LEGACY' else .5 if scheme=='PURE_RUNNER' else 0.,trail_timeframe='ENTRY',hard_tp_rr=float(ex[-1]) if scheme=='HARD_TARGET' else 0.)
    # Common cost/risk inputs stay frozen.
    return c

def engine_cfg(c):
    r=c['risk_and_exit'];scheme=r['exit_scheme'];minutes=60 if c['strategy_mode']['mode']=='MTF' else 240
    kind={'LEGACY':0,'PURE_RUNNER':3,'PURE_KIJUN':4,'HARD_TARGET':5}[scheme]
    return np.array([r['tp1_rr_ratio'],r['tp1_close_pct'],kind,r['trail_atr_buffer'],minutes,r['hard_tp_rr'],.012,2.,1.,float(c['archetype_strategy']['trail_close_only'])])

def signals(case,c,frames):
    low=frames[case['mode'],case['setting']];high=frames['SINGLE',case['setting']];minutes=60 if case['mode']=='MTF' else 240
    times=low.timestamp.to_numpy(dtype=np.int64)+minutes*60000
    hidx=np.searchsorted(high.timestamp.to_numpy(dtype=np.int64)+14400000,times,side='right')-1
    longs,shorts=shared.regime_masks(high,c);reg=(longs.to_numpy(dtype=np.int64)+2*shorts.to_numpy(dtype=np.int64))
    matched=np.maximum(hidx,0);directions=reg[matched];directions[hidx<198]=0
    if case['family']=='DONCHIAN':longs,shorts=shared.entry_masks(high,c);long=longs.to_numpy()[matched];short=shorts.to_numpy()[matched]
    else:longs,shorts=shared.entry_masks(low,c);long=longs.to_numpy();short=shorts.to_numpy()
    mask=((long&((directions&1)>0))|(short&((directions&2)>0)))&(times>=START)&(times<END)&(np.arange(len(low))>=198)
    if case['family']=='DONCHIAN':mask&=times%14400000==0
    ix=np.flatnonzero(mask);sides=np.where(long[ix],1.,-1.)
    source=high.iloc[matched[ix]] if case['family']=='DONCHIAN' else low.iloc[ix]
    breakout=case['entry']=='SIGNAL_BREAKOUT'
    trigger=np.where(sides==1,source.high,source.low) if breakout else source.close.to_numpy()
    if case['stop']=='KIJUN':stop=source.kijun.to_numpy()-sides*c['risk_and_exit']['sl_atr_buffer']*source.atr.to_numpy()
    elif case['stop']=='ATR2':stop=source.close.to_numpy()-sides*2*source.atr.to_numpy()
    else:stop=np.where(sides==1,source.low-.5*source.atr,source.high+.5*source.atr)
    sigidx=(times[ix]-START)//60000
    values=np.column_stack([sides,trigger,stop,np.full(len(ix),float(breakout))])
    # Pending setup validity at each CLOSED entry timeframe boundary.
    boundaries=START+np.arange((END-START)//(minutes*60000)+1)*minutes*60000
    jj=np.searchsorted(high.timestamp.to_numpy(dtype=np.int64)+14400000,boundaries,side='right')-1
    valid=reg[np.maximum(jj,0)].astype(np.int64)
    return sigidx.astype(np.int64),values,valid

def bars(frame,minutes,trail):
    times=START+np.arange((END-START)//(minutes*60000)+1)*minutes*60000
    indices=np.searchsorted(frame.timestamp.to_numpy(dtype=np.int64)+minutes*60000,times,side='right')-1
    selected=frame.iloc[indices]
    line=selected.ema20.to_numpy() if trail=='EMA20' else selected.kijun.to_numpy()
    # Two directional channel lines; kernel picks the appropriate side.
    if trail=='DONCHIAN10':return selected[['opposite_low_10','atr','close','opposite_high_10']].to_numpy()
    return np.column_stack([line,selected.atr,selected.close,line])

def summarize(a,t,f):
    pnls=t[:,10];wins=pnls[pnls>0];losses=pnls[pnls<0]
    assert abs(a[0]-10000-pnls.sum())<1e-6
    assert np.allclose(t[:,7]-t[:,8]+t[:,9],pnls,atol=1e-8)
    return dict(trades=len(t),long_trades=int((t[:,2]==1).sum()),short_trades=int((t[:,2]==-1).sum()),win_rate_pct=float(len(wins)/len(t)*100) if len(t) else 0.,avg_win=float(wins.mean()) if len(wins) else 0.,avg_loss=float(losses.mean()) if len(losses) else 0.,fees=float(t[:,8].sum()),funding_pnl=float(t[:,9].sum()),gross_pnl=float(t[:,7].sum()),net_profit=float(a[0]-10000),profit_factor=float(wins.sum()/-losses.sum()) if len(losses) else None,max_dd_pct=float(a[2]*100),return_pct=float(a[0]/100-100),final_equity=float(a[0]),setups=int(a[8]),cancelled=int(a[9]),min_stop_rejections=int(a[10]),missing_funding_proxy_events=int(a[11]))

def main():
    cases=grid();(ROOT/'output/predeclared_grid.json').write_text(json.dumps(cases,indent=2))
    prices,funding,frames=load_features();periods=dict(full=(0,len(prices)),train=(0,(SPLIT-START)//60000),oos=((SPLIT-START)//60000,len(prices)))
    for index,case in enumerate(cases):
        c=config_for(case);si,sv,valid=signals(case,c,frames);minutes=60 if case['mode']=='MTF' else 240
        eb=bars(frames[case['mode'],case['setting']],minutes,case['trail']);hb=bars(frames['SINGLE',case['setting']],240,case['trail'])
        for name,(begin,end) in periods.items():
            a,t,f,curve=simulate(prices,START,begin,end,si,sv,eb,hb,funding,engine_cfg(c),minutes,validity=valid)
            case[name]=summarize(a,t,f)
        case['eligible']=case['full']['trades']>=40 and case['train']['net_profit']>0 and case['oos']['net_profit']>0
        print(index+1,case['id'],case['full']['trades'],round(case['full']['net_profit'],2),'eligible',case['eligible'],flush=True)
    cases.sort(key=lambda x:(x['full']['net_profit'],x['full']['profit_factor'] or 0),reverse=True)
    eligible=[x for x in cases if x['eligible']];winner=eligible[0] if eligible else None
    result=dict(start_utc='2021-10-05T00:00:00Z',end_exclusive_utc='2026-10-05T00:00:00Z',split_utc='2025-01-01T00:00:00Z',cases=len(cases),eligible_count=len(eligible),winner=winner,matrix=cases)
    (ROOT/'output/matrix.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    chosen=[('winner',winner)] if winner else []
    for family in ['ICHI_BREAKOUT','ICHI_PULLBACK','EMA_PULLBACK','DONCHIAN']:
        group=[x for x in cases if x['family']==family];clean=[x for x in group if x['eligible']]
        chosen.append((family+'_leader',(clean or group)[0]))
    for label,case in chosen:
        c=config_for(case);si,sv,valid=signals(case,c,frames);minutes=60 if case['mode']=='MTF' else 240
        a,t,f,curve=simulate(prices,START,0,len(prices),si,sv,bars(frames[case['mode'],case['setting']],minutes,case['trail']),bars(frames['SINGLE',case['setting']],240,case['trail']),funding,engine_cfg(c),minutes,trace=True,validity=valid)
        np.savez_compressed(ROOT/'output'/f'{label}_ledger.npz',trades=t,fills=f,equity=curve)
    if winner:(ROOT/'output/winning_config.json').write_text(json.dumps(config_for(winner),indent=2)+'\n')
    print('ELIGIBLE',len(eligible),'WINNER',winner,flush=True)

if __name__=='__main__':main()
