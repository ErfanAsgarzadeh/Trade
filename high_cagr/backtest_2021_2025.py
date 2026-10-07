"""Backtest of the 15-symbol bot (4B + V2 + BTC-regime gate, 6 slots) for 2021-10-05..2025-12-31, across risk levels."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import ablation_fixes as ab, run_suite as rs
from high_cagr.kernel_fixes import simulate
from high_cagr.btc_regime_experiment import V2,btc_inside_kumo
from high_cagr.stage2_experiment import OLD,NEW,frame,build,gate
OUT=ROOT/'high_cagr/output';SYMBOLS=OLD+NEW;SLOTS=6
BEGIN=0;END=int((pd.Timestamp('2026-01-01',tz='UTC').timestamp()*1000-rs.START)//60000)
RISKS=[.0025,.005,.0075,.01,.0125,.015,.02];SLIPS=[2,5]
def setup():
    frames={(s,'4h','standard'):frame(s) for s in SYMBOLS}
    case,ss,bb,step,prices,funding=build(SYMBOLS,frames,SLOTS)
    inside=btc_inside_kumo(frames,ss.shape[1]);return frames,case,gate(ss,SYMBOLS,inside),bb,step,prices,funding,inside
def run(ctx,risk,bps):
    frames,case,sig,bb,step,prices,funding,_=ctx
    return simulate(prices,funding,sig,bb,rs.START,BEGIN,END,risk,SLOTS,step,True,slip=bps/1e4,**ab.FIX4['4B'],**V2)
def positions(t):
    """One row per root position (base unit + optional pyramid add)."""
    roots=t[t[:,18]==0];out=[]
    for r in roots:
        legs=t[t[:,17]==r[17]]
        out.append(dict(k=int(r[17]),sym=int(r[0]),side=int(r[3]),entry_ts=int(r[1]),exit_ts=int(legs[:,2].max()),entry=r[4],stop=r[6],dist=r[7],
            qty=r[5],risk_usd=r[15],equity=r[14],gross=float(legs[:,9].sum()),fees=float(legs[:,10].sum()),funding=float(legs[:,11].sum()),
            net=float(legs[:,12].sum()),exit_price=r[8],reason=int(r[13]),mfe_r=float(r[19]),added=int(len(legs)>1),stale=int(r[20])))
    return pd.DataFrame(out)
def stats(a,t,curve,risk):
    c=curve[np.isfinite(curve[:,1])];ts=pd.to_datetime(c[:,0],unit='ms');eq=pd.Series(c[:,1],index=ts)
    years=(END-BEGIN)/525960;final=a[0];peak=eq.cummax();dd=(peak-eq)/peak
    under=(eq<peak);longest=0;run_start=None
    for t_,u in zip(eq.index,under):
        if u and run_start is None:run_start=t_
        if not u and run_start is not None:longest=max(longest,(t_-run_start).days);run_start=None
    if run_start is not None:longest=max(longest,(eq.index[-1]-run_start).days)
    daily=eq.resample('1D').last().pct_change().dropna();monthly=eq.resample('ME').last().pct_change().dropna()
    p=positions(t);w=p[p.net>0];l=p[p.net<0];streak=best=0
    for x in p.sort_values('exit_ts').net:
        streak=streak+1 if x<0 else 0;best=max(best,streak)
    yearly={str(y):float(g.iloc[-1]/g.iloc[0]-1)*100 for y,g in eq.groupby(eq.index.year)}
    return dict(risk_pct=risk*100,final_equity=float(final),net_profit=float(final-10000),cagr=float(((final/10000)**(1/years)-1)*100),max_dd=float(a[1]*100),
        calmar=float(((final/10000)**(1/years)-1)*100/(a[1]*100)),profit_factor=float(w.net.sum()/-l.net.sum()),win_rate=float(len(w)/len(p)*100),positions=len(p),
        avg_r=float((p.net/p.risk_usd).mean()),sharpe=float(daily.mean()/daily.std()*np.sqrt(365)),longest_losing_streak=int(best),longest_underwater_days=int(longest),
        worst_month=float(monthly.min()*100),best_month=float(monthly.max()*100),positive_months_pct=float((monthly>0).mean()*100),fees=float(p.fees.sum()),funding=float(p.funding.sum()),
        margin_rejects=int(a[4]),max_margin_used_pct=float(a[7]*100),yearly=yearly)
def main():
    ctx=setup();res={}
    for bps in SLIPS:
        for risk in RISKS:
            a,t,curve=run(ctx,risk,bps);rs.summarize(a,t,curve,BEGIN,END,SYMBOLS);s=stats(a,t,curve,risk);res[f'{risk}|{bps}']=s
            print(f"R {risk*100:5.2f}% slip {bps}bps | CAGR {s['cagr']:7.2f} DD {s['max_dd']:6.2f} Calmar {s['calmar']:.2f} PF {s['profit_factor']:.3f} win {s['win_rate']:.1f}% Sharpe {s['sharpe']:.2f} | final ${s['final_equity']:,.0f} | streak {s['longest_losing_streak']} underwater {s['longest_underwater_days']}d worst month {s['worst_month']:.1f}% | marginrej {s['margin_rejects']}",flush=True)
    (OUT/'bt2125_summary.json').write_text(json.dumps(dict(period=['2021-10-05','2026-01-01'],symbols=SYMBOLS,slots=SLOTS,policy='4B + V2 + BTC-regime gate',results=res),indent=1))
if __name__=='__main__':main()
