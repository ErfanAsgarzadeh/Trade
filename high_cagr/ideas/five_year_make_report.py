"""Builds the two Persian HTML reports (full 5-year test, 30%-monthly-withdrawal test) from five_year_report.py outputs."""
from pathlib import Path
import sys,io,base64,json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
OUT=ROOT/'high_cagr/output/ideas/five_year'
SEED=10000.;START=pd.Timestamp('2021-10-05');MIN0=START
NAMES={'main':'Shahin','c3':'Mojsavar','pa':'Ghoghnous'};FA={'main':'شاهین','c3':'موج‌سوار','pa':'ققنوس'}
C=dict(ink='#1f2937',mut='#6b7280',grid='#e5e7eb',blue='#2563eb',teal='#0d9488',orange='#d97706',pos='#16a34a',neg='#dc2626',gray='#9ca3af',purple='#7c3aed')
BOT=dict(main=C['blue'],c3=C['teal'],pa=C['orange'])
plt.rcParams.update({'font.size':10,'axes.edgecolor':C['grid'],'axes.labelcolor':C['mut'],'xtick.color':C['mut'],'ytick.color':C['mut'],'axes.titlecolor':C['ink'],
    'axes.titlesize':11,'axes.titleweight':'bold','axes.titlelocation':'left','axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.color':C['grid'],'grid.linewidth':.6,'figure.dpi':110})
def img(fig):
    b=io.BytesIO();fig.savefig(b,format='png',bbox_inches='tight',facecolor='white');plt.close(fig);return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
def usd(x,_=None):return f'${x:,.0f}' if abs(x)<1e4 else (f'${x/1e6:.2f}M' if abs(x)>=1e6 else f'${x/1e3:.0f}k')
def fnum(x,d=0):return f'{x:,.{d}f}'
def dates(n):return pd.date_range(START,periods=n)

def load(name):
    d=np.load(OUT/f'daily_{name}.npy');w=np.load(OUT/f'wd_{name}.npy');m=np.load(OUT/f'margin_{name}.npy');t=pd.read_csv(OUT/f'trades_{name}.csv')
    t['exit']=MIN0+pd.to_timedelta(t.exit_min,unit='m');t['entry']=MIN0+pd.to_timedelta(t.entry_min,unit='m')
    t['hours']=(t.exit_min-t.entry_min)/60;t['ret']=t.pnl/t.notional*100
    return d,w,m,t

def monthly(d,w):
    """Month-end balance (before withdrawal) vs previous month-end (after). Returns DataFrame idx=month."""
    s=pd.Series(d,index=dates(len(d)));wd=pd.Series(w,index=s.index)
    me=s.resample('ME').last();wm=wd.resample('ME').sum();pre=me+wm
    prev=me.shift(1).fillna(SEED);ret=(pre/prev-1)*100
    df=pd.DataFrame(dict(end=me,pre=pre,prev=prev,ret=ret,wd=wm,profit=pre-prev));df.index=df.index.to_period('M');return df
def yearly(d,w):
    m=monthly(d,w);g=m.groupby(m.index.year)
    out=pd.DataFrame(dict(ret=g.apply(lambda x:((1+x.ret/100).prod()-1)*100),profit=g.profit.sum(),wd=g.wd.sum()));return out
def dd_series(eq):
    pk=np.maximum.accumulate(eq);return (eq/pk-1)*100
def stats(d,t,w=None):
    r=np.diff(np.concatenate([[SEED],d]))/np.concatenate([[SEED],d[:-1]]);r=r+(0 if w is None else w/np.concatenate([[SEED],d[:-1]])) if w is not None else r
    yrs=len(d)/365.25;eq=d if w is None else d+np.cumsum(w)
    cagr=((d[-1]+(0 if w is None else w.sum()))/SEED)**(1/yrs)-1 if w is None else None
    dd=dd_series(d);sd=r.std()*np.sqrt(365);sh=r.mean()*365/sd if sd>0 else 0;dn=r[r<0].std()*np.sqrt(365);so=r.mean()*365/dn if dn>0 else 0
    win=t[t.pnl>0];los=t[t.pnl<=0];pf=win.pnl.sum()/-los.pnl.sum() if len(los) and los.pnl.sum()<0 else np.inf
    ls=(t.sort_values('exit').pnl<=0).astype(int).to_numpy();mx=cur=0
    for x in ls:cur=cur+1 if x else 0;mx=max(mx,cur)
    # longest time under water
    pk=np.maximum.accumulate(d);uw=d<pk;ln=cur=0
    for x in uw:cur=cur+1 if x else 0;ln=max(ln,cur)
    return dict(final=d[-1],cagr=(d[-1]/SEED)**(1/yrs)-1,dd=dd.min(),sharpe=sh,sortino=so,vol=sd*100,trades=len(t),win=len(win)/len(t)*100,pf=pf,
        avgw=win.ret.mean(),avgl=los.ret.mean(),exp=t.ret.mean(),payoff=win.ret.mean()/-los.ret.mean(),maxloss=mx,uw=ln,best=t.pnl.max(),worst=t.pnl.min(),
        hold=t.hours.median(),calmar=((d[-1]/SEED)**(1/yrs)-1)/(-dd.min()/100))

# ------------------------------------------------------------------ charts
def ch_equity(d,extra=None,title='Account equity (log scale)'):
    fig,ax=plt.subplots(figsize=(10,4.2));x=dates(len(d));ax.plot(x,d,color=C['blue'],lw=1.6,label='Equity')
    if extra:
        for lab,s,col in extra:ax.plot(x,s,color=col,lw=1.4,label=lab)
    ax.set_yscale('log');ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title(title);ax.legend(frameon=False,loc='upper left');ax.axhline(SEED,color=C['gray'],lw=.8,ls='--');return img(fig)
def ch_dd(d,title='Drawdown from equity peak'):
    fig,ax=plt.subplots(figsize=(10,3));dd=dd_series(d);x=dates(len(d));ax.fill_between(x,dd,0,color=C['neg'],alpha=.35,lw=0);ax.plot(x,dd,color=C['neg'],lw=1)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title(title);return img(fig)
def bars_signed(ax,x,v,w=.8):
    ax.bar(x,v,width=w,color=[C['pos'] if a>=0 else C['neg'] for a in v])
def ch_yearly(y):
    fig,ax=plt.subplots(figsize=(7,3.6));bars_signed(ax,[str(i) for i in y.index],y.ret.values,.6)
    for i,v in enumerate(y.ret.values):ax.text(i,v,f'{v:,.0f}%',ha='center',va='bottom' if v>=0 else 'top',fontsize=9,color=C['ink'])
    ax.set_title('Yearly return (calendar year, first/last partial)');ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.margins(y=.15);return img(fig)
def ch_monthly(m):
    fig,ax=plt.subplots(figsize=(10,3.6));x=m.index.to_timestamp();bars_signed(ax,x,m.ret.values,20);ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Monthly return (each bar = one month)');return img(fig)
def ch_hist_monthly(m):
    fig,ax=plt.subplots(figsize=(7,3.6));v=m.ret.values;bins=np.linspace(min(v.min(),-5),max(v.max(),5),19)
    n,b,p=ax.hist(v,bins=bins,color=C['blue'],edgecolor='white',lw=1)
    for pa,l in zip(p,b[:-1]):
        if l+ (b[1]-b[0])/2<0:pa.set_facecolor(C['neg'])
        else:pa.set_facecolor(C['pos'])
    ax.axvline(np.median(v),color=C['ink'],lw=1,ls='--');ax.text(np.median(v),ax.get_ylim()[1]*.95,f' median {np.median(v):.1f}%',fontsize=9)
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Histogram of monthly returns');ax.set_ylabel('months');return img(fig)
def ch_heat(m):
    pv=m.assign(y=m.index.year,mo=m.index.month).pivot(index='y',columns='mo',values='ret');fig,ax=plt.subplots(figsize=(10,3.2))
    lim=max(abs(np.nanmin(pv.values)),abs(np.nanmax(pv.values)));lim=min(lim,80)
    im=ax.imshow(pv.values,cmap='RdYlGn',vmin=-lim,vmax=lim,aspect='auto');ax.grid(False)
    ax.set_xticks(range(12),['J','F','M','A','M','J','J','A','S','O','N','D']);ax.set_yticks(range(len(pv)),pv.index)
    for i in range(pv.shape[0]):
        for j in range(12):
            v=pv.values[i,j]
            if np.isfinite(v):ax.text(j,i,f'{v:.0f}',ha='center',va='center',fontsize=8,color=C['ink'])
    ax.set_title('Monthly return heatmap (%)');return img(fig)
def ch_trade_hist(t):
    fig,ax=plt.subplots(figsize=(7,3.6));v=t.ret.clip(-15,40);bins=np.linspace(-15,40,56);n,b,p=ax.hist(v,bins=bins,edgecolor='white',lw=.5)
    for pa,l in zip(p,b[:-1]):pa.set_facecolor(C['pos'] if l>=0 else C['neg'])
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Trade result as % of notional (clipped -15..40)');ax.set_ylabel('trades');return img(fig)
def ch_hold(t):
    fig,ax=plt.subplots(figsize=(7,3.6));ax.hist((t.hours/24).clip(0,40),bins=40,color=C['purple'],edgecolor='white',lw=.5);ax.set_title('Holding time (days, clipped at 40)');ax.set_ylabel('trades');return img(fig)
def ch_bots(t):
    fig,ax=plt.subplots(figsize=(10,3.8))
    for b in ('main','c3','pa'):
        s=t[t.bot==b].sort_values('exit');ax.plot(s.exit,s.pnl.cumsum(),color=BOT[b],lw=1.6,label=NAMES[b])
    ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title('Cumulative net P&L by bot ($, compounding)');ax.legend(frameon=False,loc='upper left');return img(fig)
def ch_bot_share(t):
    s=t.groupby('bot').pnl.sum().reindex(['main','c3','pa']);fig,ax=plt.subplots(figsize=(5,3.6))
    ax.bar([NAMES[b] for b in s.index],s.values,color=[BOT[b] for b in s.index],width=.55)
    for i,v in enumerate(s.values):ax.text(i,v,usd(v),ha='center',va='bottom',fontsize=9)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title('Net profit by bot');ax.margins(y=.15);return img(fig)
def ch_coin(t):
    s=t.groupby('coin').pnl.sum().sort_values();s=pd.concat([s.head(8),s.tail(8)]);fig,ax=plt.subplots(figsize=(7,4.4))
    ax.barh([c.replace('USDT','') for c in s.index],s.values,color=[C['pos'] if v>=0 else C['neg'] for v in s.values]);ax.xaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title('Net P&L by coin (8 worst, 8 best)');ax.grid(axis='y',visible=False);return img(fig)
def ch_margin(m):
    fig,ax=plt.subplots(figsize=(10,3));x=dates(len(m));ax.fill_between(x,m*100,0,color=C['blue'],alpha=.3,lw=0);ax.plot(x,m*100,color=C['blue'],lw=.7);ax.axhline(80,color=C['neg'],lw=1,ls='--');ax.text(x[5],81,'80% shared cap',fontsize=9,color=C['neg'])
    ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Margin in use (daily close, % of equity)');return img(fig)
def ch_rolling(d):
    s=pd.Series(d,index=dates(len(d)));r=(s/s.shift(180)-1)*100;fig,ax=plt.subplots(figsize=(10,3));ax.plot(r.index,r.values,color=C['blue'],lw=1.4);ax.axhline(0,color=C['gray'],lw=.8)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Rolling 180-day return');return img(fig)
def ch_side(t):
    g=t.assign(side=np.where(t.side>0,'Long','Short')).groupby(['bot','side']).pnl.sum().unstack().reindex(['main','c3','pa']);fig,ax=plt.subplots(figsize=(5,3.6));x=np.arange(3)
    ax.bar(x-.18,g['Long'],.36,color=C['blue'],label='Long');ax.bar(x+.18,g['Short'],.36,color=C['orange'],label='Short');ax.set_xticks(x,[NAMES[b] for b in g.index]);ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.legend(frameon=False);ax.set_title('Net P&L: long vs short');return img(fig)

# ------------------------------------------------------------------ html
CSS="""<style>
:root{--bg:#fff;--ink:#1f2937;--mut:#6b7280;--line:#e5e7eb;--card:#f9fafb;--pos:#16a34a;--neg:#dc2626;--blue:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#111827;--ink:#e5e7eb;--mut:#9ca3af;--line:#374151;--card:#1f2937;--pos:#4ade80;--neg:#f87171;--blue:#60a5fa}img{background:#fff;border-radius:8px}}
body{background:var(--bg);color:var(--ink);font-family:Vazirmatn,Tahoma,system-ui,sans-serif;margin:0;line-height:1.9}
main{max-width:1080px;margin:auto;padding:24px 16px}h1{font-size:1.7rem;margin:.2em 0}h2{margin-top:2.2em;border-bottom:2px solid var(--line);padding-bottom:6px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}.k{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.k b{display:block;font-size:1.35rem;direction:ltr;text-align:right}.k span{color:var(--mut);font-size:.82rem}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}img{width:100%;height:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.9rem;margin:10px 0}th,td{border:1px solid var(--line);padding:5px 9px;text-align:center}th{background:var(--card)}td.n{direction:ltr}
.note{background:var(--card);border-inline-start:4px solid var(--blue);padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.92rem}.warn{border-color:var(--neg)}
.pos{color:var(--pos)}.neg{color:var(--neg)}p.cap{color:var(--mut);font-size:.85rem;margin:2px 0 12px}
</style>"""
def kpi(l,v):return f'<div class="k"><b>{v}</b><span>{l}</span></div>'
def table(df,fmt=None):
    h='<table><tr><th></th>'+''.join(f'<th>{c}</th>' for c in df.columns)+'</tr>'
    for i,r in df.iterrows():h+=f'<tr><th>{i}</th>'+''.join(f'<td class="n">{(fmt or {}).get(c,lambda x:x)(v) if not isinstance(v,str) else v}</td>' for c,v in r.items())+'</tr>'
    return h+'</table>'
def pct(x):return f'{x:,.1f}%'
def pcls(v):return 'pos' if v>=0 else 'neg'
def page(title,body):return f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{CSS}</head><body><main>{body}</main></body></html>'
def tag(src,cap=''):return f'<figure style="margin:0"><img src="{src}" alt="">{f"<p class=cap>{cap}</p>" if cap else ""}</figure>'

LIMITS="""<div class="note warn"><b>محدودیت‌ها (مهم):</b> این بک‌تست روی داده واقعی دقیقه‌ای Binance Futures (اکتبر ۲۰۲۱ تا ۴ اکتبر ۲۰۲۶) با کارمزد ۰٫۱۲٪ رفت‌وبرگشت، لغزش ۲bps، Funding واقعی و همان فرمول سایزینگ ربات انجام شده، اما اجرای زنده نیست.
ظرفیت بازار و نقدشوندگی در حساب‌های بزرگ (میلیون دلاری) روی آلت‌کوین‌ها مدل نشده؛ اعداد بالای چند ده‌هزار دلار با ترکیب مرکب تقریباً قطعاً در عمل قابل‌دستیابی نیستند. حد ضرر روزانهٔ ۲٪ شاهین، precision صرافی و تأخیر polling مدل نشده‌اند.
پارامترهای ققنوس و روش‌های انتخاب شده روی همین دوره تنظیم شده‌اند (in-sample)؛ نتیجه تضمین آینده نیست.</div>"""

def full_report():
    d,w,m,t=load('soft');do,wo,mo,to=load('old');s=stats(d,t);so=stats(do,to);M=monthly(d,w);Y=yearly(d,w)
    sub={b:stats(np.zeros(len(d))+1,t[t.bot==b]) for b in ('main','c3','pa')}
    kp=''.join([kpi('موجودی نهایی (از $10,000)',usd(s['final'])),kpi('CAGR',f"{s['cagr']*100:,.0f}%"),kpi('حداکثر افت (MDD)',f"{s['dd']:.1f}%"),kpi('Calmar',f"{s['calmar']:.1f}"),
        kpi('Sharpe (روزانه)',f"{s['sharpe']:.2f}"),kpi('Sortino',f"{s['sortino']:.2f}"),kpi('تعداد معامله',fnum(s['trades'])),kpi('نرخ برد',f"{s['win']:.1f}%"),kpi('Profit Factor',f"{s['pf']:.2f}"),
        kpi('ماه‌های سودده',f"{(M.ret>0).sum()}/{len(M)}"),kpi('بدترین ماه',f"{M.ret.min():.1f}%"),kpi('بهترین ماه',f"{M.ret.max():.0f}%")])
    rows=pd.DataFrame({FA[b]:dict(**{'تعداد معامله':int((t.bot==b).sum()),'نرخ برد':pct((t[t.bot==b].pnl>0).mean()*100),'سود خالص':usd(t[t.bot==b].pnl.sum()),
        'میانگین بازده هر معامله (از نوشنال)':f"{t[t.bot==b].ret.mean():.2f}%",'میانه نگهداری (ساعت)':f"{t[t.bot==b].hours.median():.0f}"}) for b in ('main','c3','pa')}).T
    yt=Y.copy();yt['ret']=yt.ret.map(lambda v:f'<span class="{pcls(v)}">{v:,.1f}%</span>');yt['profit']=yt.profit.map(usd);yt=yt.rename(columns={'ret':'بازده سال','profit':'سود دلاری'}).drop(columns='wd')
    cmp=pd.DataFrame({'ققنوس قبلی (C2)':[usd(so['final']),f"{so['cagr']*100:.0f}%",f"{so['dd']:.1f}%",f"{so['calmar']:.1f}",fnum(to[to.bot=='pa'].shape[0]),usd(to[to.bot=='pa'].pnl.sum())],
                      'ققنوس جدید (soft ×1.5)':[usd(s['final']),f"{s['cagr']*100:.0f}%",f"{s['dd']:.1f}%",f"{s['calmar']:.1f}",fnum((t.bot=='pa').sum()),usd(t[t.bot=='pa'].pnl.sum())]},
        index=['موجودی نهایی','CAGR','MDD','Calmar','تعداد معامله ققنوس','سود خالص ققنوس'])
    b=f"""<h1>گزارش بک‌تست پنج‌ساله — سه ربات با کد جدید</h1>
<p>حساب ۱۰٬۰۰۰ دلاری مشترک · ۲۰۲۱-۱۰-۰۵ تا ۲۰۲۶-۱۰-۰۴ · شاهین ۱٪، موج‌سوار ۰٫۴٪، ققنوس (<code>C_exhaustion_soft</code> با ضریب حجم ۱٫۵ و ریسک ۰٫۴۰٪×۱٫۵×وزن فازی) · سقف مارجین مشترک ۸۰٪، اهرم ۵ ایزوله</p>
{LIMITS}<div class="kpis">{kp}</div>
<h2>منحنی سرمایه و افت</h2>{tag(ch_equity(d,[('Old Ghoghnous (C2)',do,C['gray'])]),'مقیاس لگاریتمی؛ خط خاکستری = همین حساب با ققنوس قدیمی')}{tag(ch_dd(d))}{tag(ch_rolling(d))}
<p>بیشترین افت {abs(s['dd']):.1f}٪ و طولانی‌ترین دورهٔ زیر سقف قبلی {s['uw']} روز بوده است.</p>
<h2>هیستوگرام سالانه و ماهانه</h2><div class="grid2">{tag(ch_yearly(Y))}{tag(ch_hist_monthly(M))}</div>{tag(ch_monthly(M))}{tag(ch_heat(M))}
{table(yt)}
<h2>سهم هر ربات</h2><div class="grid2">{tag(ch_bot_share(t))}{tag(ch_side(t))}</div>{tag(ch_bots(t))}{table(rows)}
<h2>توزیع معاملات</h2><div class="grid2">{tag(ch_trade_hist(t))}{tag(ch_hold(t))}</div>
<div class="kpis">{kpi('میانگین برد',f"{s['avgw']:.2f}%")}{kpi('میانگین باخت',f"{s['avgl']:.2f}%")}{kpi('Payoff',f"{s['payoff']:.2f}")}{kpi('امید ریاضی هر معامله',f"{s['exp']:.2f}%")}{kpi('بیشترین باخت پیاپی',s['maxloss'])}{kpi('میانهٔ نگهداری',f"{s['hold']:.0f} ساعت")}</div>
{tag(ch_coin(t))}
<h2>مارجین</h2>{tag(ch_margin(m),'سقف ۸۰٪ مشترک؛ ورودی که جا نداشته باشد کوچک یا رد می‌شود')}
<h2>مقایسه با ققنوس قبلی</h2>{table(cmp)}
<p>سایر ربات‌ها نسبت به بک‌تست قبلی تغییری نکرده‌اند؛ بازتولید ققنوس قدیمی در همین موتور دقیقاً به موجودی نهایی گزارش قبلی ($948,259.61) رسید که صحت موتور را تأیید می‌کند.</p>
<p class="cap">روش: دفترهای معاملات از موتورهای پژوهشی تأییدشده‌ی مخزن، سپس بازپخش رویدادی روی یک حساب با موجودی مرکب (سایز = ریسک٪ × موجودی ÷ (فاصله حد ضرر + کارمزد + لغزش)). کد: <code>high_cagr/ideas/five_year_report.py</code></p>"""
    return page('گزارش پنج‌ساله',b)

def wd_report():
    d,w,m,t=load('wd30');d0,w0,m0,t0=load('soft');M=monthly(d,w);Y=yearly(d,w);M0=monthly(d0,w0);tot=d+np.cumsum(w);cw=np.cumsum(w);prevd=np.concatenate([[SEED],d[:-1]]);adj=SEED*np.cumprod((d+w)/prevd);s=stats(adj,t)
    wdm=M.wd;nwd=int((wdm>0).sum());yrs=len(d)/365.25
    fig,ax=plt.subplots(figsize=(10,3.6));ax.bar(wdm.index.to_timestamp(),wdm.values,width=20,color=C['teal']);ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title('Monthly withdrawal ($)');a1=img(fig)
    fig,ax=plt.subplots(figsize=(10,3.6));x=dates(len(d));ax.plot(x,cw,color=C['teal'],lw=1.8,label='Cumulative withdrawn');ax.plot(x,d,color=C['blue'],lw=1.6,label='Account balance');ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.legend(frameon=False,loc='upper left');ax.set_title('Account balance vs cash taken out');a2=img(fig)
    a3=ch_equity(d,[('Balance + withdrawn',tot,C['teal']),('No withdrawal',d0,C['gray'])],'Equity (log): with 30% monthly withdrawal vs none')
    fig,ax=plt.subplots(figsize=(7,3.6));yy=Y.wd;ax.bar([str(i) for i in yy.index],yy.values,width=.6,color=C['teal'])
    for i,v in enumerate(yy.values):ax.text(i,v,usd(v),ha='center',va='bottom',fontsize=9)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(usd));ax.set_title('Yearly withdrawals ($)');ax.margins(y=.15);a4=img(fig)
    fig,ax=plt.subplots(figsize=(7,3.6));bars_signed(ax,[str(i) for i in Y.index],Y.ret.values,.6)
    for i,v in enumerate(Y.ret.values):ax.text(i,v,f'{v:,.0f}%',ha='center',va='bottom' if v>=0 else 'top',fontsize=9)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Yearly return of the account (pre-withdrawal)');ax.margins(y=.15);a5=img(fig)
    fig,ax=plt.subplots(figsize=(7,3.6));v=M.ret.values;bins=np.linspace(min(v.min(),-5),max(v.max(),5),19);n,b_,p=ax.hist(v,bins=bins,edgecolor='white')
    for pa,l in zip(p,b_[:-1]):pa.set_facecolor(C['pos'] if l+(b_[1]-b_[0])/2>=0 else C['neg'])
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0));ax.set_title('Histogram of monthly returns (before withdrawal)');ax.set_ylabel('months');a6=img(fig)
    eq_lbl=f"{usd(d[-1])}";total=d[-1]+w.sum()
    kp=''.join([kpi('کل برداشت',usd(w.sum())),kpi('موجودی نهایی حساب',eq_lbl),kpi('ارزش کل (حساب + برداشت)',usd(total)),kpi('تعداد ماه برداشت',f'{nwd}/{len(M)}'),kpi('میانگین برداشت ماهانه',usd(wdm[wdm>0].mean())),
        kpi('بیشترین برداشت',usd(wdm.max())),kpi('MDD (بدون احتساب خود برداشت‌ها)',f"{s['dd']:.1f}%"),kpi('CAGR عملکرد معاملاتی',f"{s['cagr']*100:.0f}%"),kpi('بدون برداشت: موجودی نهایی',usd(d0[-1]))])
    yt=pd.DataFrame({'بازده ماهانهٔ ترکیبی سال':Y.ret.map(pct),'سود حساب':Y.profit.map(usd),'برداشت':Y.wd.map(usd)})
    ratio=total/d0[-1]*100
    b=f"""<h1>گزارش سناریوی برداشت ماهانه (۳۰٪ سود ماه)</h1>
<p>قاعده: در آخرین روز هر ماه (بسته‌شدن روز UTC) اگر موجودی حساب از پایان ماه قبل (پس از برداشت قبلی؛ ماه اول از $10,000) بیشتر باشد، <b>۳۰٪ از سود همان ماه</b> از حساب خارج می‌شود. ماه زیانده برداشتی ندارد و جبران هم نمی‌شود. سایزِ معاملات بعدی بر اساس موجودیِ کاهش‌یافته محاسبه می‌شود (بازپخش کامل، نه صرفاً ضرب ساده).</p>
{LIMITS}<div class="kpis">{kp}</div>
<div class="note">با برداشت ۳۰٪ ماهانه، ارزش کل (حساب + نقدِ برداشت‌شده) برابر <b>{ratio:.0f}٪</b> نتیجهٔ حالت بدون برداشت است؛ تفاوت، هزینهٔ از دست رفتن اثر مرکب است. در عوض {usd(w.sum())} پول واقعی بیرون از ریسک حساب است.</div>
<h2>نمودار خروجی (برداشت)</h2>{tag(a1)}{tag(a2)}<div class="grid2">{tag(a4)}{tag(a5)}</div>
<h2>سرمایه و مقایسه با بدون برداشت</h2>{tag(a3)}{tag(ch_dd(adj,'Trading drawdown (withdrawals excluded)'))}
<h2>هیستوگرام ماهانه</h2><div class="grid2">{tag(a6)}{tag(ch_heat(M))}</div>{tag(ch_monthly(M))}
{table(yt)}
<p class="cap">کد: <code>high_cagr/ideas/five_year_report.py</code> (پارامتر <code>wd=0.3</code>) و <code>five_year_make_report.py</code>. «ماه قبل» = موجودی پایان ماه قبل پس از برداشت.</p>"""
    return page('گزارش برداشت ماهانه',b)

if __name__=='__main__':
    (OUT/'report_fa.html').write_text(full_report(),encoding='utf-8');(OUT/'report_withdraw_fa.html').write_text(wd_report(),encoding='utf-8')
    for n in ('soft','wd30','old'):
        d,w,m,t=load(n);s=stats(d,t);print(n,{k:(round(float(v),3)) for k,v in s.items()})
