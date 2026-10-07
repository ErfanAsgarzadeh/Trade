"""Builds report_2021_2025_fa.html from the backtest + diagnosis outputs (re-runs R=0.75% for the curve)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import run_suite as rs
from high_cagr.backtest_2021_2025 import setup,run,SYMBOLS
from high_cagr.stage2_experiment import folder
OUT=ROOT/'high_cagr/output'
def main():
    summ=json.loads((OUT/'bt2125_summary.json').read_text());diag=json.loads((OUT/'bt2125_diagnosis.json').read_text())
    p=pd.read_csv(OUT/'bt2125_positions.csv');W=p[p.net>0];L=p[p.net<0]
    ctx=setup();a,t,curve=run(ctx,.0075,2);c=curve[np.isfinite(curve[:,1])]
    eq=pd.Series(c[:,1],index=pd.to_datetime(c[:,0],unit='ms')).resample('1D').last().dropna();dd=(eq.cummax()-eq)/eq.cummax()*100
    monthly=eq.resample('ME').last();mret=(monthly.pct_change().fillna(monthly.iloc[0]/10000-1)*100)
    losses_per_month=L.assign(m=pd.to_datetime(L.exit_time).dt.to_period('M')).groupby('m').size()
    # stop-placement evidence
    wh=L[L.cause=='WHIPSAW'];extra=[]
    for r in wh.itertuples():
        arr=np.load(folder(r.symbol)/'prices.npy',mmap_mode='r');e1=int((pd.Timestamp(r.exit_time).value//10**6-rs.START)//60000);seg=arr[e1+1:e1+1+3*1440]
        d=abs(r.entry-r.stop);target=r.entry+r.side*d;hit=int(np.argmax(seg[:,1]>=target) if r.side==1 else np.argmax(seg[:,2]<=target));pre=seg[:hit+1]
        extra.append(max(0.,(r.exit_price-pre[:,2].min())/d if r.side==1 else (pre[:,1].max()-r.exit_price)/d))
    extra=np.array(extra)
    stop=dict(winner_mae_q={str(k):float(v) for k,v in W.mae_r.quantile([.5,.75,.9,.95]).items()},winners_mae_gt_075=float((W.mae_r>.75).mean()*100),winners_mae_gt_05=float((W.mae_r>.5).mean()*100),
              whipsaw_n=int(len(wh)),whipsaw_extra_q={str(k):float(v) for k,v in zip([.25,.5,.75,.9],np.quantile(extra,[.25,.5,.75,.9]))},survive_025=float((extra<=.25).mean()*100),survive_05=float((extra<=.5).mean()*100),
              losers_mfe_ge_1=int((L.mfe_r>=1).sum()),losers_mfe_ge_05=int((L.mfe_r>=.5).sum()))
    sd=p.R.std();tags=['tag_crowded','tag_volume_climax','tag_cluster','tag_weekend','tag_btc_against','tag_counter_daily','tag_late_entry']
    lift=[]
    for c in tags:
        w,o=p[p[c]],p[~p[c]];d=w.R.mean()-o.R.mean();se=sd*np.sqrt(1/len(w)+1/len(o))
        lift.append(dict(tag=c,n=int(len(w)),share_losers=float(L[c].mean()*100),share_winners=float(W[c].mean()*100),avg_r_with=float(w.R.mean()),avg_r_without=float(o.R.mean()),
                         diff=float(d),z=float(d/se),verdict='worse' if d/se<=-2 else ('better' if d/se>=2 else 'none')))
    trough=dd.idxmax();peak_before=eq[:trough].idxmax()
    quit=dict(peak_date=peak_before.strftime('%Y-%m-%d'),peak=float(eq[peak_before]),trough_date=trough.strftime('%Y-%m-%d'),trough=float(eq[trough]),final=float(eq.iloc[-1]),
              recovered_date=(eq[trough:][eq[trough:]>=eq[peak_before]].index[0].strftime('%Y-%m-%d') if (eq[trough:]>=eq[peak_before]).any() else None))
    sym=p.groupby('symbol').agg(n=('net','size'),net=('net','sum'),avg_r=('R','mean'),win=('net',lambda x:(x>0).mean()*100)).reset_index().sort_values('avg_r').to_dict('records')
    cols=['symbol','side','entry_time','exit_time','hours','net','R','mfe_r','mae_r','later_r','runup_atr','ext_atr','vol_ratio','crowd','width_pct','btc','roots_same_bar','cause']
    losers=L.sort_values('entry_time')[cols].copy();losers['entry_time']=losers.entry_time.str[:16];losers['exit_time']=losers.exit_time.str[:16]
    losers=losers.round(3).replace({np.nan:None})
    data=dict(lift=lift,quit=quit,r_sd=float(sd),summary=summ,diag={k:v for k,v in diag.items()},stop=stop,symbols=sym,
        equity=dict(d=[x.strftime('%Y-%m-%d') for x in eq.index],v=[round(x,2) for x in eq.values],dd=[round(x,2) for x in dd.values]),
        monthly=dict(m=[x.strftime('%Y-%m') for x in mret.index],r=[round(x,2) for x in mret.values]),
        losses_per_month=dict(mean=float(losses_per_month.mean()),max=int(losses_per_month.max())),
        losers=dict(cols=cols,rows=losers.values.tolist()))
    tpl=(ROOT/'high_cagr/report_2021_2025_template.html').read_text()
    html=tpl.replace('/*__DATA__*/null',json.dumps(data,ensure_ascii=False,separators=(',',':'),default=float))
    (OUT/'report_2021_2025_fa.html').write_text(html);print('report bytes',len(html.encode()))
    print(json.dumps(stop,indent=0)[:600]);print(json.dumps(lift,indent=0));print(quit);print('months',len(mret),'positive %',(mret>0).mean()*100,'loss/month',losses_per_month.mean(),losses_per_month.max())
if __name__=='__main__':main()
