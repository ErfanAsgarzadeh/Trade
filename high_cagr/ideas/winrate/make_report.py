"""Persian HTML report of the win-rate study (reads the JSON outputs, writes output/ideas/winrate/report_fa.html)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
OUT=ROOT/'high_cagr/output/ideas/winrate'
J=lambda n:json.loads((OUT/n).read_text())
NAMES={'main':'شاهین','c3':'موج‌سوار','pa':'ققنوس'}
CAUSE={'WIN':'سودده','GIVEBACK_GE1R':'رسید به ≥۱R و برگشت','GIVEBACK_05_1R':'رسید به ۰٫۵ تا ۱R و برگشت','FAST_STOP_LE8H':'استاپ سریع (≤۸ ساعت)',
       'NO_FOLLOW_LT02R':'بدون ادامه (<۰٫۲R)','WEAK_02_05R':'حرکت ضعیف (۰٫۲ تا ۰٫۵R)'}
f1=lambda x:f'{x:,.1f}';f2=lambda x:f'{x:,.2f}'

def svg_curve(series,labels,colors,w=900,h=320):
    pad=72;n=len(series[0]);lo=np.log10(min(s.min() for s in series)*.9);hi=np.log10(max(s.max() for s in series)*1.1)
    X=lambda i:pad+(w-pad-10)*i/(n-1);Y=lambda v:h-28-(h-48)*(np.log10(v)-lo)/(hi-lo)
    out=[f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="منحنی سرمایه" style="width:100%;height:auto;direction:ltr">']
    for p in range(int(np.floor(lo)),int(np.ceil(hi))+1):
        for m in (1,3):
            v=m*10**p
            if lo<=np.log10(v)<=hi:out.append(f'<line x1="{pad}" x2="{w-10}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/><text x="{pad-4}" y="{Y(v)+4:.1f}" font-size="11" text-anchor="end" fill="var(--mut)">${v:,.0f}</text>')
    for k,yr in enumerate(range(2022,2027)):
        i=(pd.Timestamp(f'{yr}-01-01')-pd.Timestamp('2021-10-05')).days
        out.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="20" y2="{h-28}" stroke="var(--line)"/><text x="{X(i):.1f}" y="{h-10}" font-size="11" text-anchor="middle" fill="var(--mut)">{yr}</text>')
    for s,c in zip(series,colors):
        pts=' '.join(f'{X(i):.1f},{Y(v):.1f}' for i,v in enumerate(s) if i%3==0 or i==n-1)
        out.append(f'<polyline fill="none" stroke="{c}" stroke-width="2" points="{pts}"/>')
    for k,(lab,c) in enumerate(zip(labels,colors)):
        out.append(f'<rect x="{pad+10+k*230}" y="6" width="14" height="4" fill="{c}"/><text x="{pad+30+k*230}" y="12" font-size="12" fill="var(--ink)">{lab}</text>')
    return ''.join(out)+'</svg>'

def row(cells,head=False):
    t='th' if head else 'td';return '<tr>'+''.join(f'<{t}>{c}</{t}>' for c in cells)+'</tr>'

def main():
    dg=J('diagnosis.json');fin=J('final.json');ex=J('exits.json');ml=J('ml_gate.json');ru=J('rules.json');o30=J('oos30_late_rule.json');oc=J('oos_c3exit.json')
    b=fin['shipped|x1'];f=fin['final|x1']
    # 1 diagnosis table
    t1=[row(['علت','شاهین (سهم٪ / جمع R)','موج‌سوار','ققنوس'],True)]
    for c in CAUSE:
        t1.append(row([CAUSE[c]]+[f"{dg[k]['causes'][c]['share']:.1f}٪ / {dg[k]['causes'][c]['sumR']:+.0f}" for k in ('main','c3','pa')]))
    # 2 exits: top rows per scope
    gate=lambda r:(r['win_rate']['train']>=b['win_rate']['train']+3 and r['win_rate']['valid']>=b['win_rate']['valid']+3 and r['train'][0]>=.95*b['train'][0]
                   and r['valid'][0]>=.95*b['valid'][0] and r['dd']<=b['dd']+2 and r['cagr']>=b['cagr']-10)
    pick=['main+c3+pa|lock1.0->0.1','main+c3+pa|half@2.0+lock1->0.1','main|lock0.5->0.1','main|lock0.75->0.1','c3|lock0.75->0.1','c3|lock1.0->0.3','c3|half@2.0+lock1->0.1','pa|lock1.0->0.1','pa|lock1.5->0.1']
    t2=[row(['نوع (ربات | قاعده)','برد آموزش','برد اعتبارسنجی','Calmar آموزش','Calmar اعتبارسنجی','CAGR','DD','همه گیت‌ها'],True),
        row(['<b>وضعیت فعلی</b>',f1(b['win_rate']['train']),f1(b['win_rate']['valid']),f2(b['train'][0]),f2(b['valid'][0]),f1(b['cagr']),f1(b['dd']),'—'])]
    for k in pick:
        r=ex[k];t2.append(row([k.replace('main+c3+pa','هر سه').replace('main','شاهین').replace('c3','موج‌سوار').replace('pa','ققنوس'),f1(r['win_rate']['train']),f1(r['win_rate']['valid']),
                               f2(r['train'][0]),f2(r['valid'][0]),f1(r['cagr']),f1(r['dd']),'✅' if gate(r) else '❌']))
    # 3 ml
    mb=ml['baseline'];t3=[row(['حالت','AUC میانگین (۴ سال × ۳ ربات)','برد ۲۰۲۳–۲۴','برد ۲۰۲۵–۲۶','CAGR ۲۰۲۳–۲۴','CAGR ۲۰۲۵–۲۶','DD ۲۰۲۵–۲۶'],True),
        row(['بدون فیلتر','—',f1(mb['w2324']['win']),f1(mb['w2526']['win']),f1(mb['w2324']['cagr']),f1(mb['w2526']['cagr']),f1(mb['w2526']['dd'])])]
    for k,v in ml['variants'].items():
        a=np.nanmean([x for y in v['aucs'].values() for x in y.values()])
        t3.append(row([k,f2(a),f1(v['w2324']['win']),f1(v['w2526']['win']),f1(v['w2324']['cagr']),f1(v['w2526']['cagr']),f1(v['w2526']['dd'])]))
    # 4 independent checks
    t4=[row(['آزمون مستقل','برد قبل → بعد','CAGR قبل → بعد','DD قبل → بعد','Calmar آموزش','Calmar اعتبارسنجی'],True)]
    for name,lab,bk,vk in (('شاهین روی ۱۰ کوین هرگز معامله‌نشده','xuni10','xuni10|base','xuni10|late_rule'),('شاهین روی ۳۰ کوین هرگز معامله‌نشده','all30','all30|base','all30|late_rule')):
        x,y=o30[bk],o30[vk];t4.append(row([name,f"{x['win']:.1f} → {y['win']:.1f}",f"{x['full'][1]:.1f} → {y['full'][1]:.1f}",f"{x['full'][2]:.1f} → {y['full'][2]:.1f}",f"{x['train'][0]:.2f} → {y['train'][0]:.2f}",f"{x['valid'][0]:.2f} → {y['valid'][0]:.2f}"]))
    for name,bk,vk in (('موج‌سوار روی ۲۰ کوین هرگز معامله‌نشده','other20|base','other20|c3exit'),('موج‌سوار روی ۱۰ کوین خودش (تنها)','main10|base','main10|c3exit')):
        x,y=oc[bk],oc[vk];t4.append(row([name,f"{x['win_rate']['all']:.1f} → {y['win_rate']['all']:.1f}",f"{x['cagr']:.1f} → {y['cagr']:.1f}",f"{x['dd']:.1f} → {y['dd']:.1f}",f"{x['train'][0]:.2f} → {y['train'][0]:.2f}",f"{x['valid'][0]:.2f} → {y['valid'][0]:.2f}"]))
    # 5 final
    t5=[row(['حالت','هزینه','برد کل','شاهین','موج‌سوار','ققنوس','Calmar آموزش','Calmar اعتبارسنجی','CAGR','DD','PF','سرمایه نهایی'],True)]
    lab={'shipped':'وضعیت فعلی','c3exit':'فقط خروج موج‌سوار','main_late':'فقط فیلتر شاهین','final':'<b>ترکیب نهایی</b>'}
    for k,v in fin.items():
        n,c=k.split('|');t5.append(row([lab[n],'×۱' if c=='x1' else '×۲',f1(v['win_rate']['all']),f1(v['win_rate']['main']),f1(v['win_rate']['c3']),f1(v['win_rate']['pa']),f2(v['train'][0]),f2(v['valid'][0]),f1(v['cagr']),f1(v['dd']),f2(v['pf']),f"${v['final']:,.0f}"]))
    t6=[row(['سال']+list(b['yearly']),True),row(['وضعیت فعلی']+[f1(x) for x in b['yearly'].values()]),row(['ترکیب نهایی']+[f1(x) for x in f['yearly'].values()])]
    chart=svg_curve([np.load(OUT/'daily_shipped.npy'),np.load(OUT/'daily_final.npy')],['وضعیت فعلی','ترکیب نهایی'],['var(--mut)','var(--blue)'])
    thr=ru['thresholds']['main_late']
    html=f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>افزایش نرخ برد</title><style>
:root{{--bg:#fff;--ink:#1f2937;--mut:#6b7280;--line:#e5e7eb;--card:#f9fafb;--pos:#16a34a;--neg:#dc2626;--blue:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111827;--ink:#e5e7eb;--mut:#9ca3af;--line:#374151;--card:#1f2937;--pos:#4ade80;--neg:#f87171;--blue:#60a5fa}}}}
body{{background:var(--bg);color:var(--ink);font-family:Vazirmatn,Tahoma,system-ui,sans-serif;margin:0;line-height:1.9}}
main{{max-width:1080px;margin:auto;padding:24px 16px}}h1{{font-size:1.7rem;margin:.2em 0}}h2{{margin-top:2.2em;border-bottom:2px solid var(--line);padding-bottom:6px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}}.k{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.k b{{display:block;font-size:1.35rem;direction:ltr;text-align:right}}.k span{{color:var(--mut);font-size:.82rem}}
.tw{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.88rem;margin:10px 0}}th,td{{border:1px solid var(--line);padding:5px 8px;text-align:center;white-space:nowrap}}th{{background:var(--card)}}
.note{{background:var(--card);border-inline-start:4px solid var(--blue);padding:10px 14px;border-radius:6px;margin:12px 0}}.warn{{border-color:var(--neg)}}code{{direction:ltr;unicode-bidi:embed}}
</style></head><body><main>
<h1>تحقیق افزایش نرخ معاملات پیروز — سه ربات فعال روی یک حساب</h1>
<p style="color:var(--mut)">شاهین + موج‌سوار + ققنوس (C_exhaustion_soft ×۱٫۵)، حساب paper ده‌هزار دلاری، ۲۰۲۱-۱۰-۰۵ تا ۲۰۲۶-۱۰-۰۴، سقف مارجین مشترک ۸۰٪. آموزش تا پایان ۲۰۲۴، اعتبارسنجی ۲۰۲۵ به بعد. دفتر پایه دقیقاً بازتولید شد (۲٬۸۷۵ معامله، اختلاف سود صفر).</p>
<div class="kpis">
<div class="k"><span>نرخ برد کل (قبل → بعد)</span><b>{b['win_rate']['all']:.1f}% → {f['win_rate']['all']:.1f}%</b></div>
<div class="k"><span>موج‌سوار</span><b>{b['win_rate']['c3']:.1f}% → {f['win_rate']['c3']:.1f}%</b></div>
<div class="k"><span>شاهین</span><b>{b['win_rate']['main']:.1f}% → {f['win_rate']['main']:.1f}%</b></div>
<div class="k"><span>ققنوس (بدون تغییر)</span><b>{b['win_rate']['pa']:.1f}% → {f['win_rate']['pa']:.1f}%</b></div>
<div class="k"><span>CAGR</span><b>{b['cagr']:.0f}% → {f['cagr']:.0f}%</b></div>
<div class="k"><span>بیشترین افت</span><b>{b['dd']:.1f}% → {f['dd']:.1f}%</b></div>
</div>
<div class="note"><b>خلاصه:</b> دو تغییر از همهٔ گیت‌های ازپیش‌اعلام‌شده عبور کردند و روی کوین‌هایی که ربات‌ها هرگز معامله نکرده‌اند هم تأیید شدند:
(۱) <b>مدیریت خروج موج‌سوار</b>: وقتی سود به ۱R رسید استاپ به ‎+0.1R‎ می‌رود و نصف حجم در ‎+2R‎ بسته می‌شود؛
(۲) <b>فیلتر «ورود دیرهنگام» شاهین</b>: اگر قیمت در ۶۰ کندل ۴ساعتهٔ اخیر (۱۰ روز) بیش از <code>{np.expm1(thr)*100:.1f}%</code> در جهت معامله رفته باشد، ورود جدید انجام نمی‌شود.
<b>فیلتر هوش مصنوعی (XGBoost) مهارت پیش‌بینی نداشت</b> (AUC حدود ۰٫۵) و نرخ برد را بالا نبرد؛ پیشنهاد نمی‌شود.</div>
<h2>منحنی سرمایه (مقیاس لگاریتمی)</h2>{chart}
<h2>۱. علل شکست — هر معاملهٔ زیان‌ده دقیقاً یک علت (از مسیر دقیقه‌ای)</h2>
<div class="tw"><table>{''.join(t1)}</table></div>
<div class="note">مهم‌ترین یافته: بخش بزرگی از زیان‌ها <b>اول وارد سود شده‌اند و بعد برگشته‌اند</b>. در موج‌سوار ۳۵٪ کل معاملات (۲۱٪ با سود ≥۱R) سود را پس داده‌اند چون این ربات قفل سود نداشت؛ شاهین از قبل قفل ۱R→‎+0.1R‎ دارد و برگشت ≥۱R در آن فقط ۱٪ است.
دومین علت در شاهین <b>ورود دیرهنگام</b> است: در پنجک بالای «حرکت ۱۰ روز اخیر در جهت معامله» نرخ برد ۳۷٪ (آموزش) و ۲۸٪ (اعتبارسنجی) با امید منفی بود، و در ۵ سال از ۶ سال معاملات حذف‌شده امید منفی داشتند.
سایر یافته‌ها: ATR بالا در شاهین (استاپ پهن) نرخ برد را ~۱۵pp پایین می‌آورد (هم‌پوشان با ورود دیرهنگام)؛ در موج‌سوار funding شلوغ در جهت معامله بد است اما در ۲۰۲۴ برعکس شد، پس پذیرفته نشد؛ در ققنوس ساعت روز و ADX اثر دارند اما ناپایدارند.</div>
<h2>۲. مدیریت خروج (شبکهٔ ازپیش‌اعلام‌شده، انتخاب فقط روی آموزش)</h2>
<div class="tw"><table>{''.join(t2)}</table></div>
<p>گیت‌ها: برد ≥ پایه+۳pp در هر دو دوره، Calmar ≥ ۰٫۹۵×پایه در هر دو دوره، DD ≤ پایه+۲pp، CAGR ≥ پایه−۱۰pp. قاعدهٔ انتخابی طبق پیش‌اعلام (بیشترین Calmar آموزش بین گزینه‌های عبوری از گیت برد آموزش): <b>موج‌سوار | half@2.0+lock1→0.1</b>. قفل سود تهاجمی (۰٫۵R) نرخ برد را تا ۶۸٪ می‌برد اما CAGR را نصف می‌کند؛ نرخ برد بالا به‌تنهایی هدف خوبی نیست.
خروج‌های تهاجمی‌تر برای شاهین و ققنوس Calmar آموزش را پایین آوردند و رد شدند.</p>
<h2>۳. فیلتر هوش مصنوعی (XGBoost walk-forward برای هر سه ربات)</h2>
<div class="tw"><table>{''.join(t3)}</table></div>
<div class="note warn">مدل روی هر سال فقط با معاملاتی آموزش دید که ۱۴ روز قبل از آن سال بسته شده بودند، و آستانه فقط روی سال قبل انتخاب شد. AUC در ۱۲ جفت سال×ربات بین ۰٫۴۲ و ۰٫۶۱ نوسان کرد (میانگین حدود ۰٫۵۰): یعنی مدل معاملهٔ برنده را از بازنده تشخیص نمی‌دهد و حذف ۲۰٪ ورودی‌ها CAGR را کاهش داد. این با نتایج قبلی (امتیاز تصویری AUC ۰٫۴۸، چک‌لیست پرایس‌اکشن) سازگار است. قاعدهٔ ساده و قابل‌توضیح بهتر از مدل پیچیده جواب داد.</div>
<h2>۴. آزمون مستقل روی کوین‌های دست‌نخورده</h2>
<div class="tw"><table>{''.join(t4)}</table></div>
<p>آستانهٔ شاهین از دورهٔ آموزش ۵ کوین خودش ثابت شد و بدون تغییر روی ۳۰ کوین دیگر اجرا شد. قاعدهٔ موج‌سوار هم بدون تغییر روی ۲۰ کوینی که هرگز برای آن انتخاب نشده بودند اجرا شد. هر دو در هر دو دوره بهبود دادند.</p>
<h2>۵. ترکیب نهایی و تست استرس هزینه</h2>
<div class="tw"><table>{''.join(t5)}</table></div>
<div class="tw"><table>{''.join(t6)}</table></div>
<p>«×۲» یعنی هر معامله یک رفت‌وبرگشت کامل کارمزد+لغزش اضافه می‌پردازد. ترکیب نهایی در هر دو حالت از وضعیت فعلی بهتر است.</p>
<h2>۶. محدودیت‌ها و قدم بعدی</h2>
<ul>
<li>قاعدهٔ شاهین پس از دیدن هر دو دوره در تشخیص پیدا شد (post-hoc)؛ به همین دلیل آزمون ۳۰ کوین دست‌نخورده انجام شد که آن را تأیید کرد، ولی هنوز آزمون آینده (paper زنده) جایگزین ندارد.</li>
<li>مدیریت خروج روی مسیر دقیقه‌ای دفتر موجود شبیه‌سازی شده (فقط می‌تواند زودتر خارج کند)؛ ترتیب درون‌دقیقه‌ای ناشناخته است و فعال‌سازی قفل از دقیقهٔ بعد فرض شد.</li>
<li>اعداد مطلق (CAGR بالای ۱۰۰٪) حاصل ترکیب سود و کوین‌های انتخاب‌شده است؛ مطالعهٔ عدم قطعیت قبلی نشان داد انتخاب کوین بزرگ‌ترین ریسک است. مقایسهٔ نسبی معتبرتر از عدد مطلق است.</li>
<li>داده Binance است؛ اجرای LBank، حداقل سفارش و تأخیر polling مدل نشده‌اند.</li>
<li>ققنوس: هیچ تغییری عبور نکرد؛ نرخ برد آن ۴۱٪ می‌ماند.</li>
<li>هیچ تنظیمی در ربات paper تغییر نکرده است. قدم بعدی پیشنهادی: پیاده‌سازی دو قاعده در <code>c3_sleeve.py</code> و ربات اصلی با سوییچ قابل خاموش‌کردن و تست parity با این شبیه‌سازی.</li>
</ul>
<p style="color:var(--mut);font-size:.85rem">بازتولید: <code>python restore_data.py; python high_cagr/restore_ledgers.py; python high_cagr/prepare.py; python high_cagr/ideas/winrate/fetch30.py</code> سپس <code>ledger.py, diagnose.py, run_exits.py, run_ml.py, run_rules.py, run_oos30.py, run_oos_c3exit.py, run_final.py, make_report.py</code> در <code>high_cagr/ideas/winrate/</code>. نیازمندی: pandas 2.2.3 / numpy 2.2.6 (pandas 3 مهرهای زمانی را خراب می‌کند).</p>
</main></body></html>'''
    (OUT/'report_fa.html').write_text(html);print('WROTE',OUT/'report_fa.html')
if __name__=='__main__':main()
