"""Persian HTML report: coin lists for the three bots on the TheTrueTrade futures universe (universe_*.py outputs)."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
HERE=Path(__file__).resolve().parent;OUT=ROOT/'high_cagr/output/ideas/winrate/universe'
J=lambda n:json.loads((OUT/n).read_text())
NAMES={'main':'شاهین','c3':'موج‌سوار','pa':'ققنوس'}
f1=lambda x:f'{x:,.1f}';f2=lambda x:f'{x:,.2f}'
def row(c,h=False):
    t='th' if h else 'td';return '<tr>'+''.join(f'<{t}>{x}</{t}>' for x in c)+'</tr>'
def short(s):return s.replace('USDT','')

def main():
    mk=json.loads((HERE/'ttt_markets.json').read_text());cov=json.loads((HERE/'ttt_binance_coverage.json').read_text())
    sel=J('selection.json');a1=J('allocation.json');a2=J('allocation2.json');pc=pd.read_csv(OUT/'per_coin.csv')
    cur=a2['runs']['CURRENT (TTT subset 5/7/10)'];dep=a2['runs']['CURRENT + liquid fill (latest)'];alt=a2['runs']['CURRENT + liquid fill (2024)']
    rnd=np.array(a2['random_5_7_10']['valid']);r41=a1['random_valid_calmar']
    short_hist=[s for s,v in cov.items() if v['n']<18]
    missing=dict(c3=['EGLD','ONE','SUSHI'],pa=['AXS','XTZ','CELR','ALICE','C98','THETA','IOST','CVC','CRV','IOTA'])
    # final lists table
    lists=dep['lists'];old=cur['lists']
    t_list=[row(['ربات','تعداد','ارزهای فعلی که می‌مانند','ارزهای جدید (جایگزین)','ارزهای فعلی که در TTT نیستند'],True)]
    for b in ('main','c3','pa'):
        keep=[short(s) for s in lists[b] if s in old[b]];new=[short(s) for s in lists[b] if s not in old[b]]
        t_list.append(row([NAMES[b],len(lists[b]),'، '.join(keep),'، '.join(new) or '—','، '.join(missing.get(b,[])) or '—']))
    # account comparison
    t_acc=[row(['حالت','نرخ برد (اعتبارسنجی)','Calmar آموزش','Calmar اعتبارسنجی','CAGR کل','CAGR اعتبارسنجی','بیشترین افت کل'],True)]
    for lab,r in (('فهرست فعلی (فقط ارزهای موجود در TTT، ۲۲ ارز)',cur),('<b>پیشنهادی: فعلی + جایگزین‌های پرنقدشونده (۳۵ ارز)</b>',dep),
                  ('جایگزین محافظه‌کار (نقدشوندگی ۲۰۲۴)',alt),('انتخاب بر اساس سود دورهٔ آموزش (۴۱ ارز)',sel['accounts']['TRAIN_PICK']),
                  ('همهٔ ارزها بر اساس نقدشوندگی (۴۱ ارز)',a1['runs']['LIQ2024 8/15/rest'])):
        t_acc.append(row([lab,f1(r['win_rate']['valid']),f2(r['train'][0]),f2(r['valid'][0]),f1(r['cagr']),f1(r['valid'][1]),f1(r['dd'])]))
    # carry over
    co=sel['carry_over'];t_co=[row(['ربات','ارزهای «خوب» در ۲۰۲۱–۲۴: R هر معامله در ۲۰۲۵–۲۶','ارزهای «بد» در ۲۰۲۱–۲۴: R هر معامله در ۲۰۲۵–۲۶','نرخ برد خوب / بد'],True)]
    for b in ('main','c3','pa'):
        s,r=co[b]['selected'],co[b]['rejected'];t_co.append(row([NAMES[b],f"{s['meanR']:.2f} ({s['n']} معامله)",f"{r['meanR']:.2f} ({r['n']} معامله)",f"{s['win']:.1f}٪ / {r['win']:.1f}٪"]))
    # per coin tables for recommended lists
    blocks=[]
    for b in ('main','c3','pa'):
        g=pc[(pc.bot==b)&pc.coin.isin(lists[b])].set_index('coin').loc[lists[b]]
        t=[row(['ارز','سال داده','معامله','نرخ برد','R هر معامله','R آموزش','R اعتبارسنجی','جدید؟'],True)]
        for s,x in g.iterrows():
            t.append(row([short(s),f1(x.years),int(x.all_n),f1(x.all_win)+'٪',f2(x.all_meanR),'—' if pd.isna(x.train_meanR) else f2(x.train_meanR),'—' if pd.isna(x.valid_meanR) else f2(x.valid_meanR),'✚' if s not in old[b] else '']))
        blocks.append(f'<h3>{NAMES[b]}</h3><div class="tw"><table>{"".join(t)}</table></div>')
    # universe table
    t_u=[row(['ارز','دسته','شروع داده Binance','در آزمون'],True)]
    for s in sorted(mk):t_u.append(row([short(s),mk[s]['category'],cov[s]['first'],'❌ تاریخچه کوتاه' if s in short_hist else '✅']))
    rank=a1['rank_latest'][:15];t_r=[row(['رتبه','ارز','میانهٔ حجم روزانه (میلیون دلار، ۱۲ ماه اخیر Binance)'],True)]+[row([i+1,short(s),f'{v/1e6:,.0f}']) for i,(s,v) in enumerate(rank)]
    html=f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>فهرست ارز ربات‌ها</title><style>
:root{{--bg:#fff;--ink:#1f2937;--mut:#6b7280;--line:#e5e7eb;--card:#f9fafb;--blue:#2563eb;--neg:#dc2626}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111827;--ink:#e5e7eb;--mut:#9ca3af;--line:#374151;--card:#1f2937;--blue:#60a5fa;--neg:#f87171}}}}
body{{background:var(--bg);color:var(--ink);font-family:Vazirmatn,Tahoma,system-ui,sans-serif;margin:0;line-height:1.9}}main{{max-width:1080px;margin:auto;padding:24px 16px}}
h1{{font-size:1.6rem}}h2{{margin-top:2em;border-bottom:2px solid var(--line);padding-bottom:6px}}.tw{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.88rem;margin:10px 0}}th,td{{border:1px solid var(--line);padding:5px 8px;text-align:center}}th{{background:var(--card)}}
.note{{background:var(--card);border-inline-start:4px solid var(--blue);padding:10px 14px;border-radius:6px;margin:12px 0}}.warn{{border-color:var(--neg)}}
</style></head><body><main>
<h1>بهترین فهرست ارز برای هر ربات — بازار فیوچرز TheTrueTrade</h1>
<p style="color:var(--mut)">۶۳ قرارداد دائمی USDT-M از thetruetrade.io/markets (۲۰۲۶-۱۰-۲۹). ۵۰ ارز با حداقل ۱۸ ماه دادهٔ Binance آزموده شدند؛ هر سه ربات با قواعد جدید (فیلتر ورود دیرهنگام شاهین، قفل سود موج‌سوار). دورهٔ آزمون ۲۰۲۱-۱۰ تا ۲۰۲۶-۱۰، آموزش تا پایان ۲۰۲۴.</p>
<div class="note"><b>نتیجه:</b> انتخاب ارز بر اساس سود گذشته کار نمی‌کند (جدول ۲)؛ فهرست فعلی از ۱۰۰٪ فهرست‌های تصادفی هم‌اندازه بهتر بود (Calmar اعتبارسنجی {cur['valid'][0]:.1f} در برابر میانهٔ {np.median(rnd):.1f})، و افزودن ارزهای زیاد افت سرمایه را تا ۳۳–۴۳٪ بالا برد. بهترین گزینه: <b>نگه‌داشتن فهرست فعلی و جایگزینی ارزهایی که در TTT نیستند با پرنقدشونده‌ترین ارزهای TTT</b> — Calmar اعتبارسنجی {dep['valid'][0]:.1f} در برابر {cur['valid'][0]:.1f}، CAGR کل {dep['cagr']:.0f}٪ در برابر {cur['cagr']:.0f}٪، افت {dep['dd']:.1f}٪ در برابر {cur['dd']:.1f}٪.</div>
<h2>۱. فهرست پیشنهادی</h2><div class="tw"><table>{''.join(t_list)}</table></div>
<h2>۲. آیا انتخاب ارز بر اساس نتایج گذشته جواب می‌دهد؟</h2><div class="tw"><table>{''.join(t_co)}</table></div>
<p>ارز «خوب» = در ۲۰۲۱–۲۰۲۴ دست‌کم ۲۰/۱۵/۶ معامله (شاهین/موج‌سوار/ققنوس)، میانگین R مثبت و ضریب سود ≥ ۱٫۱. در ۲۰۲۵–۲۰۲۶ ارزهای خوب و بد تقریباً یکسان عمل کردند؛ پس جدول‌های «بهترین ارز از بک‌تست» فقط برازش گذشته است.</p>
<h2>۳. مقایسهٔ حساب مشترک</h2><div class="tw"><table>{''.join(t_acc)}</table></div>
<p>۴۰ فهرست تصادفی با همان اندازهٔ فعلی (۵/۷/۱۰): Calmar اعتبارسنجی میانه {np.median(rnd):.2f} (۱۰٪ تا ۹۰٪: {np.percentile(rnd,10):.2f} تا {np.percentile(rnd,90):.2f})؛ ۳۰ فهرست تصادفی ۴۱‌ارزی: میانه {r41['median']:.2f}. ریسک هر معامله در همهٔ حالت‌ها ثابت است؛ ارز بیشتر یعنی پوزیشن هم‌زمان بیشتر و افت بزرگ‌تر.</p>
<h2>۴. کارنامهٔ هر ارز در فهرست پیشنهادی</h2>{''.join(blocks)}
<p>ققنوس روی هر ارز سالانه حدود ۵ معامله دارد؛ آمار تک‌ارزی آن عمدتاً نویز است (مثلاً ATOM: آموزش −۰٫۳۴R، اعتبارسنجی +۰٫۹۶R). ارزهای جدید ققنوس به خاطر نقدشوندگی انتخاب شده‌اند نه سود گذشته.</p>
<h2>۵. نقدشونده‌ترین ارزهای TTT (بر اساس Binance)</h2><div class="tw"><table>{''.join(t_r)}</table></div>
<h2>۶. همهٔ ۶۳ قرارداد TTT</h2><div class="tw"><table>{''.join(t_u)}</table></div>
<h2>۷. محدودیت‌ها</h2><ul>
<li>دادهٔ قیمت و حجم از Binance است؛ عمق بازار و کارمزد واقعی TTT (۰٫۰۴٪ taker طبق سایت) بررسی نشده. نقدشوندگی TTT ممکن است بسیار کمتر باشد.</li>
<li>ربات فعلاً فقط روی LBank (paper) اجرا می‌شود و اتصال به TTT ندارد؛ استفاده روی TTT نیازمند نوشتن connector است.</li>
<li>۱۳ قرارداد (طلا، نقره، نفت، مس، سهام تسلا/انویدیا/مایکرواستراتژی/اسپیس‌ایکس، HYPE، ASTER، GRAM، BTW) کمتر از ۱۸ ماه داده دارند و آزموده نشدند. PAXG (توکن طلا) از تخصیص کنار گذاشته شد.</li>
<li>بخشی از فهرست فعلی موج‌سوار در تحقیقات قبلی با دیدن داده انتخاب شده بود؛ برتری آن بر فهرست‌های تصادفی ممکن است تا حدی خوش‌بینانه باشد. فهرست پیشنهادی از نقدشوندگی ۱۲ ماه اخیر استفاده می‌کند و جایگزین محافظه‌کار (نقدشوندگی ۲۰۲۴) آزمون کاملاً بدون نگاه به آینده است.</li>
<li>ارزهای خیلی جدید (PUMP، TRUMP، ENA، ONDO) تاریخچهٔ کوتاه دارند؛ اگر محافظه‌کارتر می‌خواهید فهرست ۲۰۲۴ را بگیرید.</li></ul>
<p style="color:var(--mut);font-size:.85rem">بازتولید: <code>prepare_ttt.py, universe_eval.py, universe_select.py, universe_alloc.py, universe_alloc2.py, make_universe_report.py</code> در <code>high_cagr/ideas/winrate/</code>.</p>
</main></body></html>'''
    (OUT/'report_fa.html').write_text(html);print('WROTE',OUT/'report_fa.html')
if __name__=='__main__':main()
