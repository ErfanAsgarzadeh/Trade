"""Observed failure diagnostics for the selected winner; no strategy retuning.
Position-level categories are mutually exclusive. Excursions exclude entry/exit
minutes, whose tick order is unobserved; full-bar upper bounds are also recorded.
"""
from pathlib import Path
import sys,json,html,collections
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'lbank_project'),str(ROOT)]
import lbank_bot as bot
from high_cagr.run_suite import START,PERIODS
OUT=ROOT/'high_cagr/output'
LABELS={'COST_FLIP':'حرکت قیمت مثبت؛ زیان پس از هزینه‌ها','NO_FOLLOW_THROUGH':'شکست بدون ادامهٔ محسوس (<۰٫۵R)','FAST_REVERSAL':'برگشت سریع (≤۸ ساعت و <۱R)','GIVEBACK_GE1R':'پس‌دادن حرکت سوددهٔ ≥۱R','SLOW_FAILURE':'شکست تدریجی / سایر زیان‌های قیمت','WIN':'پوزیشن سودده','FLAT':'خنثی'}

def classify(pnl,ideal_gross,mfe,hours):
 if pnl>=0:return 'WIN' if pnl>0 else 'FLAT'
 if ideal_gross>0:return 'COST_FLIP'
 if mfe<.5:return 'NO_FOLLOW_THROUGH'
 if hours<=8 and mfe<1:return 'FAST_REVERSAL'
 if mfe>=1:return 'GIVEBACK_GE1R'
 return 'SLOW_FAILURE'

def analyze_period(w,period,prices,frames,adx_cache):
 z=np.load(OUT/(w['id']+'__'+period+'.npz'));t=z['trades'];units=[]
 for k,r in enumerate(t):
  s=w['symbols'][int(r[0])];sign=int(r[3]);entry,exit,qty,dist=r[4],r[8],r[5],r[7]
  first=int((r[1]-START)//60000);last=int((r[2]-START)//60000)
  # Strictly interior, fully observed minute candles. Endpoint prices are exact
  # modeled fills; endpoint bar highs/lows remain upper-bound sensitivity only.
  interior=prices[s][first+1:last]
  high=max(entry,exit,float(interior[:,1].max()) if len(interior) else entry)
  low=min(entry,exit,float(interior[:,2].min()) if len(interior) else entry)
  entire=prices[s][first:last+1]
  upper=max(entry,exit,float(entire[:,1].max()));lower=min(entry,exit,float(entire[:,2].min()))
  mfe=max(0.,(high-entry if sign==1 else entry-low)/dist)
  mae=max(0.,(entry-low if sign==1 else high-entry)/dist)
  mfe_upper=max(0.,(upper-entry if sign==1 else entry-lower)/dist)
  entry_raw=entry/(1+sign*.0002);exit_raw=exit/(1-sign*.0002)
  ideal=sign*(exit_raw-entry_raw)*qty;slippage=ideal-r[9]
  units.append(dict(period=period,unit_id=k,parent_id=int(r[17]),leg='ADD' if r[18] else 'ROOT',symbol=s,side='LONG' if sign==1 else 'SHORT',entry_ts=int(r[1]),exit_ts=int(r[2]),entry_utc=pd.Timestamp(r[1],unit='ms',tz='UTC').isoformat(),exit_utc=pd.Timestamp(r[2],unit='ms',tz='UTC').isoformat(),entry_price=entry,exit_price=exit,qty=qty,initial_stop=r[6],initial_r=dist,modeled_risk_usd=r[15],gross_pnl=r[9],ideal_gross_before_slippage=ideal,slippage_drag=slippage,fees=r[10],funding_pnl=r[11],net_pnl=r[12],net_r=r[12]/r[15] if r[15] else 0.,mfe_r=mfe,mfe_upper_bound_r=mfe_upper,mae_r=mae,hours=(r[2]-r[1])/3600000,exit_reason='STOP' if r[13]==3 else 'PERIOD_END',raw_exit=exit_raw))
 u=pd.DataFrame(units);positions=[]
 for parent,g in u.groupby('parent_id',sort=True):
  root=g[g.leg=='ROOT'].iloc[0];s=root.symbol;f=frames[s];ix=np.searchsorted(f.timestamp.to_numpy()+14400000,root.entry_ts,side='right')-1;bar=f.iloc[ix]
  cachekey=(s,int(ix))
  if cachekey not in adx_cache:adx_cache[cachekey]=float(bot.adx_wilder(f.iloc[max(0,ix-198):ix+1],14).iloc[-1])
  sign=1 if root.side=='LONG' else -1
  boundary=max(bar.donchian_high_10,bar.kumo_top) if sign==1 else min(bar.donchian_low_10,bar.kumo_bottom)
  strength=sign*(bar.close-boundary)/bar.close*100
  net=float(g.net_pnl.sum());ideal=float(g.ideal_gross_before_slippage.sum());category=classify(net,ideal,root.mfe_r,root.hours)
  upper_category=classify(net,ideal,root.mfe_upper_bound_r,root.hours)
  exit_kind=('PERIOD_END' if root.exit_reason=='PERIOD_END' else 'INITIAL_STOP_OR_GAP' if sign*(root.raw_exit-root.initial_stop)<=root.entry_price*1e-8 else 'RATCHETED_STOP')
  positions.append(dict(period=period,position_id=int(parent),symbol=s,side=root.side,entry_utc=root.entry_utc,exit_utc=root.exit_utc,entry_ts=int(root.entry_ts),exit_ts=int(root.exit_ts),exit_year=pd.Timestamp(root.exit_ts,unit='ms',tz='UTC').year,entry_price=root.entry_price,exit_price=root.exit_price,initial_stop=root.initial_stop,net_pnl=net,gross_pnl=float(g.gross_pnl.sum()),ideal_gross_before_slippage=ideal,slippage_drag=float(g.slippage_drag.sum()),fees=float(g.fees.sum()),funding_pnl=float(g.funding_pnl.sum()),mfe_r=float(root.mfe_r),mfe_upper_bound_r=float(root.mfe_upper_bound_r),mae_r=float(root.mae_r),hours=float(root.hours),category=category,upper_category=upper_category,endpoint_sensitive=category!=upper_category,exit_kind=exit_kind,adds=int((g.leg=='ADD').sum()),root_net_pnl=float(root.net_pnl),add_net_pnl=float(g[g.leg=='ADD'].net_pnl.sum()),net_r=net/root.modeled_risk_usd if root.modeled_risk_usd else 0.,entry_adx14=adx_cache[cachekey],kijun_slope_atr=sign*(bar.kijun-f.iloc[max(0,ix-3)].kijun)/bar.atr,breakout_strength_pct=float(strength)))
 p=pd.DataFrame(positions);assert len(p)==w[period]['root_entries'];assert abs(p.net_pnl.sum()-w[period]['net_profit'])<1e-6
 assert np.allclose(u.ideal_gross_before_slippage-u.slippage_drag-u.fees+u.funding_pnl,u.net_pnl,atol=1e-8)
 loss=p[p.net_pnl<0];win=p[p.net_pnl>0]
 def stats(g):
  neg=g[g.net_pnl<0];pos=g[g.net_pnl>0]
  return dict(positions=len(g),losses=len(neg),win_rate_pct=len(pos)/len(g)*100 if len(g) else 0.,net_pnl=float(g.net_pnl.sum()),negative_pnl=float(neg.net_pnl.sum()),avg_loss=float(neg.net_pnl.mean()) if len(neg) else 0.,avg_win=float(pos.net_pnl.mean()) if len(pos) else 0.,fees=float(g.fees.sum()),funding_pnl=float(g.funding_pnl.sum()),slippage_drag=float(g.slippage_drag.sum()),avg_mfe_r=float(g.mfe_r.mean()) if len(g) else 0.)
 categories={k:{**stats(g),'share_of_losing_positions_pct':len(g)/len(loss)*100,'median_hours':float(g.hours.median())} for k,g in loss.groupby('category')}
 slices={key:{str(value):stats(g) for value,g in p.groupby(key)} for key in ['symbol','side','exit_year','exit_kind','adds']}
 # Descriptive entry cohorts only: the winning strategy did not use these gates.
 p['adx_cohort']=pd.cut(p.entry_adx14,[-np.inf,20,25,35,np.inf],right=False,labels=['<20','20–25','25–35','>=35']).astype(str)
 p['breakout_cohort']=pd.cut(p.breakout_strength_pct,[-np.inf,.25,.5,1.,np.inf],right=False,labels=['<0.25%','0.25–0.5%','0.5–1%','>=1%']).astype(str)
 p['slope_cohort']=np.where(p.kijun_slope_atr<=0,'flat_or_adverse','favorable')
 for key in ['adx_cohort','breakout_cohort','slope_cohort']:slices[key]={str(v):stats(g) for v,g in p.groupby(key)}
 order=p.sort_values(['exit_ts','position_id']);longest=0;current=0;streaks=[];streak_start=None
 for _,r in order.iterrows():
  if r.net_pnl<0:
   if current==0:streak_start=r.exit_utc
   current+=1;longest=max(longest,current)
  elif current:
   streaks.append(dict(length=current,start_utc=streak_start,end_utc=prior_end));current=0
  prior_end=r.exit_utc
 if current:streaks.append(dict(length=current,start_utc=streak_start,end_utc=prior_end))
 p['exit_4h_bucket']=(p.exit_ts//14400000)*14400000
 clusters=p.groupby('exit_4h_bucket').agg(positions=('net_pnl','size'),losses=('net_pnl',lambda x:int((x<0).sum())),symbols=('symbol',lambda x:','.join(sorted(set(x)))),net_pnl=('net_pnl','sum')).reset_index()
 clusters['utc']=pd.to_datetime(clusters.exit_4h_bucket,unit='ms',utc=True).astype(str)
 curve=z['equity'];curve=curve[np.isfinite(curve).all(axis=1)];peak=np.maximum.accumulate(curve[:,1]);d=(peak-curve[:,1])/peak;trough=int(np.argmax(d));peak_ix=int(np.argmax(curve[:trough+1,1]));dd_start,dd_end=int(curve[peak_ix,0]),int(curve[trough,0]);window=p[(p.exit_ts>dd_start)&(p.exit_ts<=dd_end)]
 summary=dict(**stats(p),unit_count=len(u),losing_units=int((u.net_pnl<0).sum()),negative_positions=len(loss),overlapping_tags=dict(losses_exit_within_8h=int((loss.hours<=8).sum()),losses_mfe_at_least_1r=int((loss.mfe_r>=1).sum()),losses_mfe_at_least_2r=int((loss.mfe_r>=2).sum())),category_totals=categories,cohorts=slices,longest_exit_order_loss_streak=longest,largest_streaks=sorted(streaks,key=lambda x:x['length'],reverse=True)[:10],worst_positions=p.nsmallest(15,'net_pnl').replace({np.nan:None}).to_dict('records'),worst_exit_clusters=clusters.nsmallest(15,'net_pnl').to_dict('records'),endpoint_sensitive_losers=int(loss.endpoint_sensitive.sum()),pyramid=dict(add_units=int((u.leg=='ADD').sum()),negative_add_units=int(((u.leg=='ADD')&(u.net_pnl<0)).sum()),add_net_pnl=float(u[u.leg=='ADD'].net_pnl.sum()),positions_with_add=int((p.adds>0).sum()),negative_combined_positions_with_add=int(((p.adds>0)&(p.net_pnl<0)).sum()),negative_add_but_combined_positive=int(((p.add_net_pnl<0)&(p.net_pnl>0)).sum())),drawdown_window=dict(start_utc=pd.Timestamp(dd_start,unit='ms',tz='UTC').isoformat(),end_utc=pd.Timestamp(dd_end,unit='ms',tz='UTC').isoformat(),hourly_sampled_dd_pct=float(d[trough]*100),minute_engine_dd_pct=w[period]['max_dd_pct'],closed_position_summary=stats(window),closed_loss_categories={k:stats(g) for k,g in window[window.net_pnl<0].groupby('category')}),rejections={k:w[period][k] for k in ['min_stop_rejections','slot_rejections','margin_rejections']})
 return p,u,summary

def main():
 m=json.loads((OUT/'matrix.json').read_text());w=m['winner'];prices={s:np.load(ROOT/'high_cagr/prepared'/s/'prices.npy',mmap_mode='r') for s in w['symbols']};frames={}
 for s in w['symbols']:
  z=np.load(ROOT/'high_cagr/prepared'/s/f"4h_{w['preset']}.npz");frames[s]=pd.DataFrame(z['data'],columns=json.loads(str(z['columns'])))
 cache={};result=dict(winner_id=w['id'],scope='Selected winner; Full and independent Train/OOS ledgers, not all rejected configurations',rules=LABELS,method='Interior complete minute bars plus modeled fill endpoints; full endpoint-bar MFE upper bound to flag sensitivity. ADX(14) reproduces 199-closed-bar reset. Cohorts are descriptive, not causal or proven new filters.',periods={})
 for period in PERIODS:
  p,u,r=analyze_period(w,period,prices,frames,cache);result['periods'][period]=r
  p.to_csv(OUT/f'failure_positions_{period}.csv',index=False);p[p.net_pnl<0].to_csv(OUT/f'failure_losing_positions_{period}.csv',index=False);u.to_csv(OUT/f'failure_units_{period}.csv',index=False);print(period,'positions',len(p),'negative',r['negative_positions'],'unit_losses',r['losing_units'],flush=True)
 (OUT/'failure_diagnostics.json').write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result['periods']['full']['category_totals'],indent=2),flush=True)
if __name__=='__main__':main()
