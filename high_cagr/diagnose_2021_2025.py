"""Per-position diagnosis of every losing trade of the 15-symbol bot at R=0.75%, 2bps (2021-10-05..2025-12-31).
Thresholds are fixed round numbers chosen before looking at the output; a tag is only called a cause where it
is more frequent among losers than winners (lift reported)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.backtest_2021_2025 import setup,run,positions,SYMBOLS,END
OUT=ROOT/'high_cagr/output';RISK=.0075;H4=14400000
RULES=dict(gave_back_mfe_r=1.0,whipsaw_after_days=3,whipsaw_reach_r=1.0,late_runup_atr=3.0,late_extension_atr=3.0,false_breakout_mfe_r=0.3,
           crowded_funding=0.0003,volume_climax=2.5,cluster_roots=3,quick_fail_hours=8)
def main():
    ctx=setup();frames,case,sig,bb,step,prices,funding,inside=ctx
    a,t,curve=run(ctx,RISK,2);p=positions(t);p['R']=p.net/p.risk_usd;p['win']=p.net>0
    feats={}
    for i,s in enumerate(SYMBOLS):
        f=frames[s,'4h','standard'].copy();f['vol_ma20']=f.volume.rolling(20).mean().shift(1);f['sma120']=f.close.rolling(120).mean()
        feats[s]=f
    btc=feats['BTCUSDT'];rows=[]
    for r in p.itertuples():
        s=SYMBOLS[r.sym];f=feats[s];bar_ts=r.entry_ts-3000-H4;i=int(np.searchsorted(f.timestamp.to_numpy(np.int64),bar_ts,side='right')-1);b=f.iloc[i]
        j=int(np.searchsorted(btc.timestamp.to_numpy(np.int64),bar_ts,side='right')-1);bb_=btc.iloc[j]
        btc_state='inside' if bb_.kumo_bottom<=bb_.close<=bb_.kumo_top else ('with' if np.sign(bb_.close-bb_.kumo_top if bb_.close>bb_.kumo_top else bb_.close-bb_.kumo_bottom)==r.side else 'against')
        e0=(r.entry_ts-rs.START)//60000;e1=(r.exit_ts-rs.START)//60000;px=prices[r.sym]
        seg=px[e0:e1+1];mae=(r.entry-seg[:,2].min())/r.dist if r.side==1 else (seg[:,1].max()-r.entry)/r.dist
        after=px[e1+1:e1+1+RULES['whipsaw_after_days']*1440]
        later=((after[:,1].max()-r.entry)/r.dist if r.side==1 else (r.entry-after[:,2].min())/r.dist) if len(after) else 0.
        fund=funding[r.sym][max(0,e0-1500):e0+1];fund=fund[np.isfinite(fund)];crowd=float(r.side*fund[-1]) if len(fund) else 0.
        runup=r.side*(b.close-f.close.iloc[i-6])/b.atr;ext=r.side*(b.close-b.kijun)/b.atr
        rows.append(dict(btc=btc_state if s!='BTCUSDT' else 'self',mae_r=float(mae),later_r=float(later),crowd=crowd,runup_atr=float(runup),ext_atr=float(ext),
            vol_ratio=float(b.volume/b.vol_ma20) if b.vol_ma20>0 else np.nan,width_pct=float(2*b.atr/b.close*100),daily_trend=bool(r.side*(b.close-b.sma120)>0)))
    p=pd.concat([p,pd.DataFrame(rows)],axis=1)
    p['symbol']=[SYMBOLS[x] for x in p.sym];p['entry_time']=pd.to_datetime(p.entry_ts,unit='ms');p['exit_time']=pd.to_datetime(p.exit_ts,unit='ms')
    p['hours']=(p.exit_ts-p.entry_ts)/3600000;p['hour_utc']=((p.entry_ts-3000)//3600000%24).astype(int);p['weekday']=p.entry_time.dt.day_name();p['year']=p.entry_time.dt.year
    p['roots_same_bar']=p.groupby('entry_ts').k.transform('count')
    p['open_at_entry']=[int(((p.entry_ts<=x)&(p.exit_ts>x)).sum()) for x in p.entry_ts]
    R=RULES;stop_exit=p.reason==3
    p['tag_crowded']=p.crowd>=R['crowded_funding'];p['tag_volume_climax']=p.vol_ratio>=R['volume_climax'];p['tag_cluster']=p.roots_same_bar>=R['cluster_roots']
    p['tag_weekend']=p.entry_time.dt.dayofweek>=5;p['tag_btc_against']=p.btc=='against';p['tag_counter_daily']=~p.daily_trend;p['tag_quick_fail']=p.hours<R['quick_fail_hours']
    p['tag_late_entry']=(p.runup_atr>=R['late_runup_atr'])|(p.ext_atr>=R['late_extension_atr']);p['tag_whipsaw']=stop_exit&(p.later_r>=R['whipsaw_reach_r'])
    def cause(x):
        if x.net>=0:return 'WIN'
        if x.gross>=0:return 'COSTS'
        if x.mfe_r>=R['gave_back_mfe_r']:return 'GAVE_BACK'
        if x.tag_whipsaw:return 'WHIPSAW'
        if x.tag_late_entry:return 'LATE_ENTRY'
        if x.mfe_r<R['false_breakout_mfe_r']:return 'FALSE_BREAKOUT'
        return 'CHOP'
    p['cause']=p.apply(cause,axis=1);L=p[~p.win]
    tags=[c for c in p.columns if c.startswith('tag_')]
    lift={c:dict(share_losers=float(L[c].mean()*100),share_winners=float(p[p.win][c].mean()*100),loss_rate_with=float((~p[p[c]].win).mean()*100) if p[c].any() else None,
                 loss_rate_without=float((~p[~p[c]].win).mean()*100),avg_r_with=float(p[p[c]].R.mean()) if p[c].any() else None,avg_r_without=float(p[~p[c]].R.mean()),n_with=int(p[c].sum())) for c in tags}
    causes=L.groupby('cause').agg(n=('net','size'),loss_usd=('net','sum'),avg_r=('R','mean'),avg_mfe=('mfe_r','mean'),avg_hours=('hours','mean')).sort_values('loss_usd')
    def grp(col):
        g=p.groupby(col);return pd.DataFrame(dict(n=g.size(),win_rate=g.win.mean()*100,net=g.net.sum(),avg_r=g.R.mean())).reset_index().to_dict('records')
    streaks=[];cur=0
    for x in p.sort_values('exit_ts').win:
        cur=0 if x else cur+1;streaks.append(cur)
    keep=['k','symbol','side','entry_time','exit_time','hours','entry','stop','exit_price','net','R','gross','fees','funding','mfe_r','mae_r','later_r','runup_atr','ext_atr','vol_ratio','crowd','width_pct','btc','daily_trend','roots_same_bar','open_at_entry','hour_utc','weekday','year','added','reason','cause']+tags
    p[keep].to_csv(OUT/'bt2125_positions.csv',index=False)
    res=dict(rules=RULES,n_positions=len(p),n_losers=len(L),loser_loss_usd=float(L.net.sum()),winner_profit_usd=float(p[p.win].net.sum()),
        causes=causes.reset_index().to_dict('records'),tag_lift=lift,by_symbol=grp('symbol'),by_year=grp('year'),by_side=grp('side'),by_hour=grp('hour_utc'),by_weekday=grp('weekday'),
        by_btc=grp('btc'),by_holding=pd.DataFrame(dict(bucket=pd.cut(p.hours,[0,8,24,72,168,1e5],labels=['<8h','8-24h','1-3d','3-7d','>7d']),win=p.win,net=p.net,R=p.R)).groupby('bucket',observed=True).agg(n=('net','size'),win_rate=('win','mean'),net=('net','sum'),avg_r=('R','mean')).reset_index().to_dict('records'),
        longest_losing_streak=int(max(streaks)))
    (OUT/'bt2125_diagnosis.json').write_text(json.dumps(res,indent=1,default=str))
    print('positions',len(p),'losers',len(L),'loss $%.0f'%L.net.sum(),'win $%.0f'%p[p.win].net.sum())
    print(causes.round(2).to_string())
    print('\nTAG LIFT (share among losers vs winners; avg R with vs without)')
    for c,v in lift.items():print(f"  {c:20} losers {v['share_losers']:5.1f}%  winners {v['share_winners']:5.1f}% | avgR with {v['avg_r_with'] if v['avg_r_with'] is None else round(v['avg_r_with'],3)} vs {v['avg_r_without']:.3f} (n={v['n_with']})")
    for name in ['by_side','by_btc','by_holding','by_year']:print('\n',name,pd.DataFrame(res[name]).round(2).to_string(index=False))
if __name__=='__main__':main()
