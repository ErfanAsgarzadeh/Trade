"""Persian HTML report for win_prob_model.py (reads its outputs; also adds per-trade R for the explanation chart)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt,matplotlib.ticker as mt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import five_year_make_report as R, five_year_report as FY, win_prob_model as W
OUT=W.OUT;C=R.C
NAMES={'base':'همه معاملات (پایه)','skip20':'رد ۲۰٪ پایین','skip30':'رد ۳۰٪ پایین','skip40':'رد ۴۰٪ پایین','skip50':'رد ۵۰٪ پایین',
       'size_lin':'ریسک ×(۰٫۵ تا ۱٫۵)','size_strong':'ریسک ×(۰٫۲۵ تا ۱٫۷۵)','skip30_size':'رد ۳۰٪ + ریسک متغیر'}
EN={'base':'Base','skip20':'Skip 20%','skip30':'Skip 30%','skip40':'Skip 40%','skip50':'Skip 50%','size_lin':'Size 0.5-1.5x','size_strong':'Size 0.25-1.75x','skip30_size':'Skip30+Size'}

def main():
    res=json.loads((OUT/'result.json').read_text());S=pd.read_csv(OUT/'scored_trades.csv')
    L=[l for l in FY.ledgers('soft') if not l['is_add']]
    S['R']=[l['unit']/(l['entry']*(l['stop_frac']+FY.FEE_RT+FY.SLIP_ALLOW)) for l in L]
    te=S.em>=W.TEST_START;T=S[te]
    m=res['models']['logit'];g=res['models']['gbm'];sc=res['scen']['logit']['test'];sg=res['scen']['gbm']['test'];s24=res['scen']['logit']['y2024']
    # charts
    fig,ax=plt.subplots(figsize=(10,4));x=pd.date_range('2025-01-01',periods=len(np.load(OUT/'daily_logit_base.npy')))
    for k,col in (('base',C['blue']),('size_lin',C['teal']),('skip30',C['orange']),('skip50',C['neg'])):
        ax.plot(x,np.load(OUT/f'daily_logit_{k}.npy'),color=col,lw=1.8 if k=='base' else 1.4,label=EN[k])
    ax.set_yscale('log');ax.yaxis.set_major_formatter(mt.FuncFormatter(R.usd));ax.legend(frameon=False,loc='upper left');ax.set_title('Test 2025-01 .. 2026-10: $10,000 account, logistic score');eq=R.img(fig)
    keys=list(EN)
    fig,axs=plt.subplots(1,2,figsize=(10,3.8))
    for ax,(lab,f,fmt) in zip(axs,(('Calmar (CAGR / max DD)',lambda d:d['calmar'],'{:.1f}'),('Max drawdown %',lambda d:d['dd'],'{:.0f}%'))):
        v=[f(sc[k]) for k in keys];ax.barh([EN[k] for k in keys][::-1],v[::-1],color=[C['blue'] if k=='base' else C['gray'] for k in keys][::-1])
        for i,val in enumerate(v[::-1]):ax.text(val,i,' '+fmt.format(val),va='center',fontsize=8,ha='left' if val>=0 else 'right')
        ax.set_title(lab);ax.grid(axis='y',visible=False);ax.margins(x=.2)
    fig.tight_layout();bars=R.img(fig)
    fig,axs=plt.subplots(1,2,figsize=(10,3.6))
    for ax,(nm,col) in zip(axs,(('logit',C['blue']),('gbm',C['purple']))):
        q=pd.cut(T[f'pct_{nm}'],[0,.2,.4,.6,.8,1.0001],labels=['0-20','20-40','40-60','60-80','80-100'],include_lowest=True)
        wr=T.groupby(q,observed=False).win.mean()*100;n=T.groupby(q,observed=False).size()
        ax.bar(wr.index.astype(str),wr.values,color=col,width=.6);ax.axhline(T.win.mean()*100,color=C['ink'],ls='--',lw=1)
        for i,(v,k) in enumerate(zip(wr.values,n.values)):ax.text(i,v,f'{v:.0f}%\nn={k}',ha='center',va='bottom',fontsize=8)
        ax.set_ylim(0,65);ax.set_title(f'{nm}: TEST win rate by TRAIN score percentile');ax.set_xlabel('score percentile');ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    fig.tight_layout();wr_img=R.img(fig)
    lo=T[T.pct_logit<.3];hi=T[T.pct_logit>=.3]
    fig,ax=plt.subplots(figsize=(10,3.6));bins=np.linspace(-2,12,57)
    ax.hist(hi.R.clip(-2,12),bins=bins,color=C['blue'],alpha=.6,label=f'kept (score >= 30th pct), n={len(hi)}',density=True)
    ax.hist(lo.R.clip(-2,12),bins=bins,color=C['orange'],alpha=.6,label=f'skipped (bottom 30%), n={len(lo)}',density=True)
    ax.set_title('TEST trades: result in R (risk units), skipped vs kept');ax.legend(frameon=False);ax.set_xlabel('R');rimg=R.img(fig)
    big=T[T.R>=5];share_lo=(big.pct_logit<.3).mean()*100
    co=pd.Series(res['coef']).sort_values()
    fig,ax=plt.subplots(figsize=(7,4));ax.barh(co.index,co.values,color=[C['pos'] if v>0 else C['neg'] for v in co.values]);ax.set_title('Logistic coefficients (standardised; + = more likely to win)');ax.grid(axis='y',visible=False);coef=R.img(fig)
    def row(k,d):return f"<tr><th>{NAMES[k]}</th><td class=n>{R.usd(d['final'])}</td><td class=n>{d['cagr']:.0f}%</td><td class=n>{d['dd']:.1f}%</td><td class=n>{d['calmar']:.2f}</td><td class=n>{d['trades']}</td><td class=n>{d['win']:.1f}%</td><td class=n>{d['pf']:.2f}</td></tr>"
    hdr='<tr><th>سناریو</th><th>موجودی نهایی</th><th>CAGR</th><th>MDD</th><th>Calmar</th><th>معامله</th><th>نرخ برد</th><th>PF</th></tr>'
    tab=lambda d:'<div style="overflow-x:auto"><table>'+hdr+''.join(row(k,d[k]) for k in keys)+'</table></div>'
    passed=[k for k in keys if k!='base' and sc[k]['calmar']>sc['base']['calmar'] and sc[k]['dd']>=sc['base']['dd']-2]
    kp=''.join([R.kpi('AUC تست (لجستیک)',f"{m['auc_test']:.3f}"),R.kpi('AUC تست (GBM)',f"{g['auc_test']:.3f}"),R.kpi('AUC سال ۲۰۲۴',f"{m['auc_2024']:.3f}"),
        R.kpi('نرخ برد تست',f"{res['win']['test']*100:.1f}%"),R.kpi('معامله آموزش / تست',f"{res['n']['train']} / {res['n']['test']}"),R.kpi('سناریوهای قبول‌شده',f'{len(passed)}/{len(keys)-1}')])
    body=f"""<h1>مدل احتمال موفقیت معامله — نتیجه تست</h1>
<p>آموزش با معاملات ۲۰۲۱-۱۰ تا ۲۰۲۳-۱۲ ({res['n']['train']} معامله)، تست روی ۲۰۲۵-۰۱ تا ۲۰۲۶-۱۰ ({res['n']['test']} معامله) که مدل هیچ‌وقت ندیده. سال ۲۰۲۴ کنار گذاشته شد و فقط برای اطلاع گزارش شده. ویژگی‌ها، مدل‌ها، سناریوها و قاعدهٔ قبولی پیش از اجرا در <code>win_prob_model.py</code> ثبت شده‌اند و بعد از دیدن نتایج تغییر نکرده‌اند.</p>
<div class="note warn"><b>نتیجه:</b> مدل تقریباً هیچ قدرت پیش‌بینی ندارد (AUC تست {m['auc_test']:.3f}؛ ۰٫۵ یعنی شیر یا خط). هیچ سناریویی قاعدهٔ قبولی (Calmar بالاتر از پایه بدون بدترشدن افت بیش از ۲ واحد درصد) را پاس نکرد. فیلتر یا ریسک متغیر بر اساس این امتیاز <b>نباید</b> وارد ربات شود.</div>
<div class="kpis">{kp}</div>
<h2>۱) رد معاملات با امتیاز پایین و ۲) ریسک بر اساس امتیاز — دورهٔ تست</h2>
<p>حساب ۱۰٬۰۰۰ دلاری که از ۲۰۲۵-۰۱-۰۱ خالی شروع می‌کند؛ همان موتور و هزینه‌های گزارش پنج‌ساله. امتیاز: مدل لجستیک (مدل اصلی).</p>
{tab(sc)}{R.tag(eq)}{R.tag(bars)}
<h2>چرا کار نکرد؟</h2>
<p>رد معاملات کم‌امتیاز نرخ برد را کمی بالا برد ({sc['base']['win']:.1f}٪ → {sc['skip50']['win']:.1f}٪)، ولی سود به‌شدت کم شد. دلیلش ماهیت روندی این ربات‌هاست: سود اصلی از تعداد کمی معاملهٔ خیلی بزرگ (۵R به بالا) می‌آید و مدل نمی‌تواند آن‌ها را از قبل تشخیص دهد. {share_lo:.0f}٪ از معاملات ۵R+ دورهٔ تست جزو ۳۰٪ «کم‌امتیاز» بودند و فیلتر آن‌ها را هم حذف می‌کرد.</p>
{R.tag(rimg,'توزیع نتیجهٔ معاملات تست (بر حسب R) برای معاملات ردشده و نگه‌داشته‌شده تقریباً یکسان است.')}
{R.tag(wr_img,'نرخ برد در دورهٔ تست بر اساس صدک امتیاز. اگر مدل کار می‌کرد، ستون‌ها باید از چپ به راست بالا می‌رفتند. خط‌چین = میانگین.')}
<h2>جزئیات مدل‌ها</h2>
<div style="overflow-x:auto"><table><tr><th></th><th>AUC آموزش (out-of-fold)</th><th>AUC ۲۰۲۴</th><th>AUC تست</th><th>شاهین</th><th>موج‌سوار</th><th>ققنوس</th></tr>
<tr><th>لجستیک (اصلی)</th><td class=n>{m['auc_train_oof']:.3f}</td><td class=n>{m['auc_2024']:.3f}</td><td class=n>{m['auc_test']:.3f}</td>{''.join(f"<td class=n>{m['per_bot'][b]['auc']:.3f}</td>" for b in ('main','c3','pa'))}</tr>
<tr><th>Gradient Boosting</th><td class=n>{g['auc_train_oof']:.3f}</td><td class=n>{g['auc_2024']:.3f}</td><td class=n>{g['auc_test']:.3f}</td>{''.join(f"<td class=n>{g['per_bot'][b]['auc']:.3f}</td>" for b in ('main','c3','pa'))}</tr></table></div>
<p>مدل GBM روی آموزش کمی بهتر بود ({g['auc_train_oof']:.3f}) ولی در ۲۰۲۴ زیر ۰٫۵ رفت؛ یعنی الگوهای آموزش را حفظ کرده بود. در تست، فیلتر GBM افت را کم کرد ولی سود را بیشتر کم کرد، پس Calmar باز هم بدتر از پایه بود:</p>
{tab(sg)}
{R.tag(coef,'ضرایب مدل لجستیک. همه کوچک‌اند؛ بزرگ‌ترین‌ها (نوسان و فاصلهٔ حد ضرر) هم اثر ضعیفی دارند.')}
<h2>سال ۲۰۲۴ (برای اطلاع، داده‌ای که مدل ندیده)</h2>{tab(s24)}
<h2>ویژگی‌ها</h2><p>همه در آخرین کندل ۴ساعته بسته‌شده قبل از ورود و هم‌جهت با معامله: فاصله تا EMA200 و EMA50، شیب EMA50، بازده ۲۰ و ۱۲۰ کندلی، ATR/قیمت و رتبهٔ آن در ۵۰۰ کندل، جای قیمت در رنج ۶۰ کندلی، وضعیت و حرکت BTC، درصد کوین‌های بالای EMA50، فاصلهٔ حد ضرر و نوع ربات.</p>
<h2>جمع‌بندی و قدم بعدی</h2>
<ul><li>با این ویژگی‌ها، «احتمال برد» هر معامله از گذشته قابل‌پیش‌بینی نیست؛ لبهٔ ربات‌ها در خود قواعد ورود/خروج است و سیگنال‌ها همین الان هم تقریباً یکدست‌اند.</li>
<li>برای سیستم‌های روندی هدف درست «احتمال برد» نیست، بلکه «اندازهٔ سود مورد انتظار (R)» یا «احتمال معاملهٔ بزرگ» است. اگر بخواهید، این را به‌عنوان یک آزمون جدید و مستقل، با همان تقسیم داده و قاعدهٔ قبولی از پیش ثبت‌شده، اجرا می‌کنم.</li>
<li>وزن فازی فعلی ققنوس (که روی همین دوره انتخاب شده بود) جداگانه ارزیابی نشده و این گزارش تغییری در آن نمی‌دهد.</li></ul>
<p class="cap">کد: <code>high_cagr/ideas/win_prob_model.py</code> و <code>win_prob_report.py</code>.</p>"""
    (OUT/'report_fa.html').write_text(R.page('مدل احتمال موفقیت',body),encoding='utf-8')
    print('passed',passed,'big-in-low',round(share_lo,1))
if __name__=='__main__':main()
