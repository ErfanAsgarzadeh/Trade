"""Persian HTML report for three_bots_replay.py (writes high_cagr/output/ideas/three_bots/report_fa.html)."""
from pathlib import Path
import json,math,html
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'high_cagr/output/ideas/three_bots'
R=json.loads((OUT/'result.json').read_text());daily=np.load(OUT/'daily_equity.npy');T=pd.read_csv(OUT/'trades.csv')
dates=pd.date_range('2021-10-05',periods=len(daily));FA={'main':'شاهین','c3':'موج‌سوار','pa':'ققنوس'}
fa=lambda x:str(x).translate(str.maketrans('0123456789.-','۰۱۲۳۴۵۶۷۸۹٫−'))
def n(x,d=1):return f'{x:,.{d}f}'

# ---------- equity (log) + per-bot cumulative realized ----------
W,H,PL,PR,PT,PB=920,300,64,16,14,30
def xs(i,N):return PL+(W-PL-PR)*i/(N-1)
lo,hi=math.log10(5000),math.log10(daily.max()*1.15)
ys=lambda v:PT+(H-PT-PB)*(1-(math.log10(v)-lo)/(hi-lo))
step=3;idx=list(range(0,len(daily),step))+[len(daily)-1]
eq_path='M'+' L'.join(f'{xs(i,len(daily)):.1f},{ys(daily[i]):.1f}' for i in idx)
grid=''
for v in (1e4,3e4,1e5,3e5,1e6):
    if lo<=math.log10(v)<=hi:grid+=f'<line x1="{PL}" x2="{W-PR}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" class="g"/><text x="{PL-8}" y="{ys(v)+4:.1f}" class="ax" text-anchor="end">${v/1000:,.0f}k</text>'
years=''
for y in range(2022,2027):
    i=(pd.Timestamp(f'{y}-01-01')-dates[0]).days;years+=f'<line x1="{xs(i,len(daily)):.1f}" x2="{xs(i,len(daily)):.1f}" y1="{PT}" y2="{H-PB}" class="g"/><text x="{xs(i,len(daily)):.1f}" y="{H-10}" class="ax" text-anchor="middle">{y}</text>'
eqdata=json.dumps([[str(dates[i].date()),round(float(daily[i]),0)] for i in idx])
# drawdown
dd=1-daily/np.maximum.accumulate(daily);H2=150;ddmax=max(.30,dd.max()*1.1)
yd=lambda v:PT+(H2-PT-PB)*v/ddmax
dd_path=f'M{PL},{PT} '+' '.join(f'L{xs(i,len(dd)):.1f},{yd(dd[i]):.1f}' for i in idx)+f' L{W-PR},{PT} Z'
ddgrid=''.join(f'<line x1="{PL}" x2="{W-PR}" y1="{yd(v):.1f}" y2="{yd(v):.1f}" class="g"/><text x="{PL-8}" y="{yd(v)+4:.1f}" class="ax" text-anchor="end">{int(v*100)}٪</text>' for v in (0,.1,.2,.3) if v<=ddmax)
ddyears=''.join(f'<text x="{xs((pd.Timestamp(f"{y}-01-01")-dates[0]).days,len(dd)):.1f}" y="{H2-10}" class="ax" text-anchor="middle">{y}</text>' for y in range(2022,2027))
iw=int(np.argmax(dd));pk=int(np.argmax(daily[:iw+1]))
# per-bot cumulative realized P&L (by exit day)
T['day']=np.minimum(T.exit_min//1440,len(daily)-1)
cum={b:np.cumsum(np.bincount(T[T.bot==b].day,weights=T[T.bot==b].pnl,minlength=len(daily))) for b in ('main','c3','pa')}
cmax=max(c.max() for c in cum.values())*1.08;cmin=min(0,min(c.min() for c in cum.values()))
yc=lambda v:PT+(H-PT-PB)*(1-(v-cmin)/(cmax-cmin))
botpaths=''.join(f'<path d="M{" L".join(f"{xs(i,len(daily)):.1f},{yc(cum[b][i]):.1f}" for i in idx)}" class="ln s{k+1}"/><text x="{W-PR-4}" y="{yc(cum[b][-1])-6:.1f}" class="lab" text-anchor="end">{FA[b]}</text>'
                 for k,b in enumerate(('main','c3','pa')))
cgrid=''.join(f'<line x1="{PL}" x2="{W-PR}" y1="{yc(v):.1f}" y2="{yc(v):.1f}" class="g"/><text x="{PL-8}" y="{yc(v)+4:.1f}" class="ax" text-anchor="end">${v/1000:,.0f}k</text>' for v in range(0,int(cmax),100000))
cumdata=json.dumps([[str(dates[i].date())]+[round(float(cum[b][i]),0) for b in ('main','c3','pa')] for i in idx])

# ---------- risk frontier (CAGR vs DD) ----------
G=R['grid'];SC=R['scale'];SCK=[.5,.75,1.,1.25,1.5,2.,2.5]
FW,FH=920,380;fx0,fx1,fy0,fy1=10,60,40,400
fx=lambda v:PL+(FW-PL-PR)*(v-fx0)/(fx1-fx0);fy=lambda v:PT+(FH-PT-PB)*(1-(v-fy0)/(fy1-fy0))
fgrid=''.join(f'<line x1="{fx(v):.1f}" x2="{fx(v):.1f}" y1="{PT}" y2="{FH-PB}" class="g"/><text x="{fx(v):.1f}" y="{FH-10}" class="ax" text-anchor="middle">{v}٪</text>' for v in range(10,61,10))
fgrid+=''.join(f'<line x1="{PL}" x2="{FW-PR}" y1="{fy(v):.1f}" y2="{fy(v):.1f}" class="g"/><text x="{PL-8}" y="{fy(v)+4:.1f}" class="ax" text-anchor="end">{v}٪</text>' for v in range(50,401,50))
series=[('main','شاهین',[(r['dd'],r['cagr'],f"{r['risk']['main']*100:.2f}٪") for r in G['main']]),('c3','موج‌سوار',[(r['dd'],r['cagr'],f"{r['risk']['c3']*100:.2f}٪") for r in G['c3']]),
        ('pa','ققنوس',[(r['dd'],r['cagr'],f"{r['risk']['pa']*100:.2f}٪") for r in G['pa']]),('all','هر سه با هم',[(r['dd'],r['cagr'],f"×{k}") for k,r in zip(SCK,SC)])]
front=''
for k,(key,name,pts) in enumerate(series):
    front+=f'<path d="M{" L".join(f"{fx(d):.1f},{fy(c):.1f}" for d,c,_ in pts)}" class="ln s{k+1}"/>'
    for d,c,lab in pts:front+=f'<circle cx="{fx(d):.1f}" cy="{fy(c):.1f}" r="5" class="pt s{k+1}" data-tip="{name} · ریسک {lab} · CAGR {c:.1f}٪ · افت {d:.1f}٪"><title>{name} · ریسک {lab} · CAGR {c:.1f}٪ · افت {d:.1f}٪</title></circle>'
    d,c,lab=pts[-1];dy={'main':4,'c3':18,'pa':4,'all':-12}[key];front+=f'<text x="{fx(d)+10:.1f}" y="{fy(c)+dy:.1f}" class="lab">{name}</text>'
b=R['base'];front+=f'<circle cx="{fx(b["dd"]):.1f}" cy="{fy(b["cagr"]):.1f}" r="8" class="cur"/><text x="{fx(b["dd"])-30:.1f}" y="{fy(b["cagr"])+6:.1f}" class="lab" text-anchor="end">پیش‌فرض فعلی</text>'

# ---------- tables ----------
def rtab(rows,key):
    out=''
    for r in rows:
        risk=r['risk'][key] if key else None;cur=abs(r['cagr']-b['cagr'])<1e-6 and abs(r['dd']-b['dd'])<1e-6
        out+=(f"<tr class='{'cur' if cur else ''}'><td>{(f'{risk*100:.2f}٪' if key else '')}</td><td>{n(r['cagr'])}٪</td><td>{n(r['dd'])}٪</td><td>{r['calmar']:.2f}</td>"
              f"<td>{n(r['train'][1])}٪ / {n(r['train'][2])}٪</td><td>{n(r['valid'][1])}٪ / {n(r['valid'][2])}٪</td><td>{n(r['margin_avg'],0)}٪ / {n(r['margin_p95'],0)}٪ / {n(r['margin_peak'],0)}٪</td>"
              f"<td>{sum(r['rejected'].values())} / {sum(r['shrunk'].values())}</td><td>${r['final_equity']/1000:,.0f}k</td></tr>")
    return out
TH="<tr><th>{}</th><th>CAGR</th><th>بیشترین افت</th><th>Calmar</th><th>Train<br>CAGR / افت</th><th>Valid<br>CAGR / افت</th><th>مارجین<br>میانگین / P95 / اوج</th><th>ورود رد / کوچک‌شده</th><th>سرمایهٔ پایانی</th></tr>"
grid_tabs=''.join(f"<h3>ریسک {FA[k]} (دو ربات دیگر روی پیش‌فرض)</h3><div class='tw'><table>{TH.format('ریسک '+FA[k])}{rtab(G[k],k)}</table></div>" for k in ('main','c3','pa'))
scale_rows=''
for k,r in zip(SCK,SC):
    rr=r['risk'];cur=k==1.
    scale_rows+=(f"<tr class='{'cur' if cur else ''}'><td>×{k} <span class='sm'>({rr['main']*100:.2f} / {rr['c3']*100:.2f} / {rr['pa']*100:.2f}٪)</span></td><td>{n(r['cagr'])}٪</td><td>{n(r['dd'])}٪</td><td>{r['calmar']:.2f}</td>"
                 f"<td>{n(r['train'][1])}٪ / {n(r['train'][2])}٪</td><td>{n(r['valid'][1])}٪ / {n(r['valid'][2])}٪</td><td>{n(r['margin_avg'],0)}٪ / {n(r['margin_p95'],0)}٪ / {n(r['margin_peak'],0)}٪</td>"
                 f"<td>{sum(r['rejected'].values())} / {sum(r['shrunk'].values())}</td><td>${r['final_equity']/1000:,.0f}k</td></tr>")
yr=''.join(f"<td class='{'neg' if v<0 else ''}'>{n(v)}٪</td>" for v in b['yearly'].values())
yh=''.join(f'<th>{y}{"*" if y in ("2021","2026") else ""}</th>' for y in b['yearly'])
alone=''
for k in ('main','c3','pa'):
    a=R['alone'][k];alone+=f"<tr><td>{FA[k]}</td><td>{b['entries'][k]:,}</td><td>{(T[T.bot==k].pnl>0).mean()*100:.1f}٪</td><td>${b['pnl'][k]/1000:,.0f}k</td><td>{b['pnl'][k]/sum(b['pnl'].values())*100:.0f}٪</td><td>{n(a['cagr'])}٪</td><td>{n(a['dd'])}٪</td><td>{a['calmar']:.2f}</td></tr>"
yrs_alone=''.join(f"<tr><td>{FA[k]}</td>"+''.join(f"<td class='{'neg' if v<0 else ''}'>{n(v)}٪</td>" for v in R['alone'][k]['yearly'].values())+"</tr>" for k in ('main','c3','pa'))
m=pd.Series(daily,index=dates).resample('ME').last();mr=(m/m.shift(1).fillna(10000.)-1)*100
mtab='';
for y in sorted(set(mr.index.year)):
    cells=''
    for mo in range(1,13):
        v=mr[(mr.index.year==y)&(mr.index.month==mo)]
        cells+=f"<td class='{'neg' if len(v) and v.iloc[0]<0 else ''}'>{n(v.iloc[0]) if len(v) else ''}</td>"
    mtab+=f'<tr><th>{y}</th>{cells}</tr>'
neg_m=int((mr<0).sum());worst=mr.min();worst_d=mr.idxmin()
uw=(dd>0).astype(int);runs=[];c=0
for v in uw:
    c=c+1 if v else 0;runs.append(c)
long_uw=max(runs)

tpl=(Path(__file__).with_name('three_bots_report_template.html')).read_text()
rep={'{{FINAL}}':f"${b['final_equity']:,.0f}",'{{CAGR}}':n(b['cagr']),'{{DD}}':n(b['dd']),'{{CALMAR}}':f"{b['calmar']:.2f}",'{{TRAIN}}':f"{n(b['train'][1])}٪ / {n(b['train'][2])}٪",
     '{{VALID}}':f"{n(b['valid'][1])}٪ / {n(b['valid'][2])}٪",'{{DDPEAK}}':str(dates[pk].date()),'{{DDTROUGH}}':str(dates[iw].date()),'{{MAVG}}':n(b['margin_avg'],0),'{{MP95}}':n(b['margin_p95'],0),'{{MPEAK}}':n(b['margin_peak'],1),
     '{{EQGRID}}':grid+years,'{{EQPATH}}':eq_path,'{{EQDATA}}':eqdata,'{{DDGRID}}':ddgrid+ddyears,'{{DDPATH}}':dd_path,'{{CGRID}}':cgrid+years,'{{BOTPATHS}}':botpaths,'{{CUMDATA}}':cumdata,
     '{{FGRID}}':fgrid,'{{FRONT}}':front,'{{GRIDTABS}}':grid_tabs,'{{SCALEROWS}}':scale_rows,'{{SCALEHEAD}}':TH.format('ضریب ریسک هر سه'),'{{YH}}':yh,'{{YR}}':yr,'{{ALONE}}':alone,'{{YRSALONE}}':yrs_alone,'{{MTAB}}':mtab,
     '{{NEGM}}':str(neg_m),'{{NM}}':str(len(mr)),'{{WORSTM}}':n(worst),'{{WORSTMD}}':worst_d.strftime('%Y-%m'),'{{LONGUW}}':str(long_uw),'{{NTOT}}':f"{sum(b['entries'].values()):,}",
     '{{W}}':str(W),'{{H}}':str(H),'{{H2}}':str(H2),'{{FW}}':str(FW),'{{FH}}':str(FH),'{{PL}}':str(PL),'{{PR}}':str(PR)}
for k,v in rep.items():tpl=tpl.replace(k,v)
assert '{{' not in tpl,tpl[tpl.find('{{'):tpl.find('{{')+30]
(OUT/'report_fa.html').write_text(tpl);print('written',len(tpl))
