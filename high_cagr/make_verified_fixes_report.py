"""Decision gate + Persian report for the conditional ablation (reads output/ablation_fixes.json)."""
from pathlib import Path
import json,html
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'high_cagr/output';R='0.0075'
d=json.loads((OUT/'ablation_fixes.json').read_text());rows,verd=d['rows'],d['verdicts']
base=rows['0_BASELINE'][R]['full']
# A fix family is usable only if one of its ISOLATED variants is ACCEPTED (fallback rule): combos inherit nothing.
families={'1':['1A','1B'],'2':['2A','2B'],'4':['4A','4B']}
usable={k:[v for v in vs if verd[R][v]['verdict']=='ACCEPTED'] for k,vs in families.items()}
accepted=[n for n,v in verd[R].items() if v['verdict']=='ACCEPTED']
def parts(name):return [] if name=='0_BASELINE' else name.split('+')
eligible=[n for n in accepted if all(p in sum(usable.values(),[]) for p in parts(n))]
# Parsimony tie-break (not in the brief): among accepted configs built only from individually accepted fixes, fewest rules, then Calmar.
final=sorted(eligible,key=lambda n:(len(parts(n)),-rows[n][R]['full']['calmar']))[0] if eligible else '0_BASELINE'
robust={n:verd['0.01'][n]['verdict'] for n in accepted}
decision=dict(risk_level=float(R),baseline=base,accepted_at_0075=accepted,accepted_at_01=[n for n,v in verd['0.01'].items() if v['verdict']=='ACCEPTED'],
    usable_isolated_fixes=usable,final_subset=final,
    config_overrides={'strategy_settings':dict(profit_floor_enabled=True,profit_floor_trigger_r=2.0,profit_floor_lock_r=0.25,safe_pyramid_enabled=True,pyramid_risk_fraction=0.35)} if final=='4B' else {},
    note='Rules #1 and #2 are not implemented in the live bot because no isolated variant of either was accepted.')
(OUT/'verified_fixes.json').write_text(json.dumps(decision,indent=1))
e=html.escape
def fmt(x,k):return f'{x:,.0f}' if k=='net' else f'{x:.3f}' if k in('pf','calmar') else f'{x:.2f}'
def table(risk):
    head='<tr><th rowspan=2>سیاست</th>'+''.join(f'<th colspan=5>{t}</th>' for t in ('کل ۵ سال','Train ۲۰۲۱–۲۰۲۴','اعتبارسنجی ۲۰۲۵–۲۰۲۶'))+'<th rowspan=2>نتیجه</th></tr><tr>'+'<th>CAGR٪</th><th>سود$</th><th>PF</th><th>DD٪</th><th>Calmar</th>'*3+'</tr>'
    body=''
    for n in rows:
        r=rows[n][risk];v=verd[risk][n]['verdict'];cls={'ACCEPTED':'ok','REJECTED':'no','BASELINE':'base'}[v]
        cells=''.join(f"<td>{fmt(r[p]['cagr_pct'],'c')}</td><td>{fmt(r[p]['net_profit'],'net')}</td><td>{fmt(r[p]['profit_factor'],'pf')}</td><td>{fmt(r[p]['max_dd_pct'],'d')}</td><td>{fmt(r[p]['calmar'],'calmar')}</td>" for p in ('full','train','oos'))
        body+=f'<tr class={cls}><th scope=row>{e(n)}</th>{cells}<td><b class="v {cls}">{v}</b></td></tr>'
    return f'<div class=scroll><table dir=ltr>{head}{body}</table></div>'
def winners():
    out=''
    for n in rows:
        t=rows[n][R]['top25_baseline_winners'];ratio=t['policy_pnl']/t['baseline_pnl']
        out+=f"<tr><th scope=row>{e(n)}</th><td>{t['baseline_pnl']:,.0f}</td><td>{t['policy_pnl']:,.0f}</td><td>{ratio:.2f}×</td><td>{t['still_open_same_entry']}/25</td></tr>"
    return out
g=lambda n,k,p='full':rows[n][R][p][k]
page=f'''<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>گزارش اصلاحیه‌های راستی‌آزمایی‌شده</title>
<style>
:root{{--bg:#f7f7f4;--fg:#1d1f21;--mut:#5d636b;--card:#fff;--line:#d9dbd6;--ok:#17653b;--okbg:#e4f3ea;--no:#8a2a2a;--nobg:#f8e8e6;--base:#3a4a63;--basebg:#e8edf5}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#16181a;--fg:#e8e9e6;--mut:#a3a8ae;--card:#1f2224;--line:#363a3d;--ok:#7fd1a0;--okbg:#17301f;--no:#f0a29a;--nobg:#381d1b;--base:#a9bde0;--basebg:#212b3b}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.8 system-ui,"Vazirmatn",Tahoma,sans-serif;padding:0 16px 48px}}
main{{max-width:1180px;margin:0 auto}}h1{{font-size:1.7rem;margin:32px 0 4px}}h2{{font-size:1.25rem;margin:36px 0 8px}}p,li{{max-width:75ch}}.mut{{color:var(--mut)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:14px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}.kpis div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}.kpis b{{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}}
.scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}}table{{border-collapse:collapse;width:100%;font-size:.82rem;font-variant-numeric:tabular-nums;text-align:right}}
th,td{{padding:5px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}thead th,tr:first-child th{{background:var(--bg)}}tbody th,th[scope=row]{{text-align:left;position:sticky;left:0;background:var(--card)}}
tr.ok{{background:var(--okbg)}}tr.ok th[scope=row]{{background:var(--okbg)}}tr.base{{background:var(--basebg)}}tr.base th[scope=row]{{background:var(--basebg)}}
.v{{padding:1px 8px;border-radius:99px;font-size:.75rem}}.v.ok{{color:var(--ok)}}.v.no{{color:var(--no)}}.v.base{{color:var(--base)}}code{{direction:ltr;unicode-bidi:embed}}
</style></head><body><main>
<h1>راستی‌آزمایی سه اصلاحیهٔ علت‌های زیان</h1>
<p class=mut>همان دادهٔ ۵ سالهٔ ۱ دقیقه‌ای، ۵ نماد، کارمزد ۰٫۱۲٪، لغزش ۲bps، Funding و REJECT زیر ۱٫۲٪. کرنل جدید با اصلاحیه‌های خاموش بیت‌به‌بیت با کرنل قبلی برابر است (۶ آزمون برابری: دو ریسک × سه دوره). ۲۷ سیاست × ۲ سطح ریسک × ۳ دوره = ۱۶۲ اجرا.</p>
<div class=kpis><div><span class=mut>برنده</span><b dir=ltr>{e(final)}</b></div><div><span class=mut>CAGR (پایه ← جدید)</span><b dir=ltr>{base['cagr_pct']:.2f} ← {g(final,'cagr_pct'):.2f}٪</b></div>
<div><span class=mut>افت سرمایه (پایه ← جدید)</span><b dir=ltr>{base['max_dd_pct']:.2f} ← {g(final,'max_dd_pct'):.2f}٪</b></div><div><span class=mut>Calmar</span><b dir=ltr>{base['calmar']:.3f} ← {g(final,'calmar'):.3f}</b></div>
<div><span class=mut>سود خالص</span><b dir=ltr>${base['net_profit']:,.0f} ← ${g(final,'net_profit'):,.0f}</b></div></div>
<h2>تصمیم</h2><div class=card><p><b>فقط اصلاحیهٔ ۴B (کف سود پس از ۲R + پیرامید امن‌تر)</b> در ربات اعمال شد. اصلاحیه‌های ۱ (سقف خوشه) و ۲ (محافظ کهنگی) هیچ‌کدام در حالت منفرد پذیرفته نشدند، پس طبق قاعدهٔ Fallback کنار گذاشته شدند و در ربات پیاده نشده‌اند.</p>
<p><code>2B+4B</code> هم دو معیار را پاس کرد (CAGR {g('2B+4B','cagr_pct'):.2f}٪، DD {g('2B+4B','max_dd_pct'):.2f}٪، Calmar {g('2B+4B','calmar'):.3f})، ولی ۲B به‌تنهایی رد شد (DD {g('2B','max_dd_pct'):.2f}٪ از پایه {base['max_dd_pct']:.2f}٪ بیشتر و Calmar {g('2B','calmar'):.3f} از {base['calmar']:.3f} کمتر) و افزودنش به ۴B فقط {g('2B+4B','cagr_pct')-g('4B','cagr_pct'):.2f} واحد CAGR می‌دهد و سود Train را {g('4B','net_profit','train')-g('2B+4B','net_profit','train'):,.0f}$ کم می‌کند. به همین دلیل ساده‌ترین زیرمجموعهٔ پذیرفته‌شده انتخاب شد؛ این قاعدهٔ «کمترین تعداد قانون» در دستور کار نبود و انتخاب من است.</p></div>
<h2>جدول Ablation — ریسک ۰٫۷۵٪ (ریسک مستقر)</h2>
<p class=mut>پذیرش: سود Train و اعتبارسنجی مثبت، و یکی از دو مسیر: (الف) Calmar بالاتر از ۰٫۹۵ و از پایه، با DD کمتر از پایه و CAGR ≥ ۳۰٪؛ یا (ب) CAGR و سود بالاتر از پایه با DD ≤ DD پایه. DD معیار، DD دورهٔ کامل است.</p>
{table(R)}
<h2>جدول Ablation — ریسک ۱٪ (آزمون پایداری)</h2>
<p class=mut>مقایسه با پایهٔ همان ریسک (CAGR {rows['0_BASELINE']['0.01']['full']['cagr_pct']:.2f}٪، DD {rows['0_BASELINE']['0.01']['full']['max_dd_pct']:.2f}٪). این سطح فقط برای سنجش پایداری است و مبنای تصمیم نبود؛ هر دو سیاست پذیرفته‌شده در این ریسک هم پذیرفته شدند.</p>
{table('0.01')}
<h2>کدام اصلاحیه کمک کرد و کدام آسیب زد</h2>
<div class=card><h3>#۱ سقف خوشه — به برنده‌های بزرگ آسیب زد</h3><p>ورودهای هم‌زمان فقط زیان‌ده نیستند: همان خوشه‌ها جایی‌اند که روندهای هم‌بستهٔ کریپتو سود می‌دهند. ۱A تعداد ورودها را از {rows['0_BASELINE'][R]['full']['root_entries']:,} به {g('1A','root_entries'):,} و ۱B به {g('1B','root_entries'):,} رساند و CAGR از {base['cagr_pct']:.1f}٪ به {g('1A','cagr_pct'):.1f}٪ و {g('1B','cagr_pct'):.1f}٪ افتاد. ۲۵ برنده‌ی برتر پایه با ۱A فقط {rows['1A'][R]['top25_baseline_winners']['policy_pnl']/rows['1A'][R]['top25_baseline_winners']['baseline_pnl']:.2f}× و با ۱B فقط {rows['1B'][R]['top25_baseline_winners']['policy_pnl']/rows['1B'][R]['top25_baseline_winners']['baseline_pnl']:.2f}× سود قبلی را نگه داشتند. DD کمتر شد (۲۸٫۲ و ۲۰٫۹٪) ولی Calmar از ۰٫۹۳۳ به ۰٫۷۲ و ۰٫۵۴ بدتر شد: هم CAGR و هم Calmar افت کردند، پس رد و کنار گذاشته شد.</p>
<h3>#۲ محافظ کهنگی — سود Train بهتر، اعتبارسنجی بدتر، DD بالاتر</h3><p>۲A روی {g('2A','root_entries'):,} ورود اعمال شد و DD را از {base['max_dd_pct']:.2f} به {g('2A','max_dd_pct'):.2f}٪ برد (Calmar {g('2A','calmar'):.3f}). CAGR در Train بالا رفت ({g('2A','cagr_pct','train'):.2f}٪ از {rows['0_BASELINE'][R]['train']['cagr_pct']:.2f}٪) ولی در اعتبارسنجی پایین آمد ({g('2A','cagr_pct','oos'):.2f}٪ از {rows['0_BASELINE'][R]['oos']['cagr_pct']:.2f}٪)؛ یعنی اثر پایدار نیست. ۲B تقریباً خنثی است (DD +{g('2B','max_dd_pct')-base['max_dd_pct']:.2f}، Calmar {g('2B','calmar'):.3f}) و رد شد.</p>
<h3>#۴ کف سود و پیرامید امن — تنها اصلاحیهٔ پذیرفته‌شده</h3><p>کف سود ۳۸۱ بار فعال شد و هیچ‌یک از ۳۸۱ پوزیشنی که به ۲R رسیدند با زیان خالص بسته نشد (در پایه ۳۶ مورد چنین بود). ۴A به‌تنهایی بالاترین CAGR را دارد ({g('4A','cagr_pct'):.2f}٪، Calmar {g('4A','calmar'):.3f}) ولی DD را از {base['max_dd_pct']:.2f} به {g('4A','max_dd_pct'):.2f}٪ برد و با دروازهٔ سخت‌گیرانه رد شد (DD باید کمتر شود). تعداد افزودن‌ها در ۴A از {rows['0_BASELINE'][R]['full']['pyramid_adds']} به {g('4A','pyramid_adds')} رسید؛ این با اینکه کف سود استاپ را زودتر به محدودهٔ پوشش هزینه می‌رساند سازگار است. ۴B همین کف را نگه می‌دارد و افزودن‌های ناامن را حذف می‌کند ({g('4B','pyramid_safe_rejects'):,} تلاش رد شد، {g('4B','pyramid_adds')} افزودن ماند)، و هر دو معیار را پاس کرد: CAGR {g('4B','cagr_pct'):.2f}٪، DD {g('4B','max_dd_pct'):.2f}٪، Calmar {g('4B','calmar'):.3f}. برنده‌های بزرگ آسیب ندیدند: {rows['4B'][R]['top25_baseline_winners']['policy_pnl']/rows['4B'][R]['top25_baseline_winners']['baseline_pnl']:.2f}× سود ۲۵ برندهٔ برتر پایه حفظ شد.</p></div>
<h2>آیا برنده‌های بزرگ خفه شدند؟ (۲۵ پوزیشن برتر پایه، ریسک ۰٫۷۵٪)</h2>
<div class=scroll><table dir=ltr><tr><th>سیاست</th><th>سود پایه$</th><th>سود همین پوزیشن‌ها$</th><th>نسبت</th><th>ورود مشابه موجود</th></tr>{winners()}</table></div>
<p class=mut>مسیر معاملات به‌خاطر ترکیب سرمایه و جایگاه‌ها تغییر می‌کند؛ این نسبت‌ها شاخص‌اند، نه شمارش دقیق علّی.</p>
<h2>محدودیت‌ها — قبل از اعتماد به نتیجه بخوانید</h2><div class=card><ul>
<li><b>درون‌نمونه است.</b> هر سه اصلاحیه از تشخیص زیان‌های همین ۵ سال ساخته شدند و ۲۰۲۵–۲۰۲۶ در انتخاب برندهٔ پایه نقش داشته؛ آزمون مستقل دست‌نخورده نیست. ۲۶ سیاست غیرپایه روی همین دادهٔ ثابت سنجیده شد، پس شانس انتخاب نتیجهٔ خوش‌شانس وجود دارد.</li>
<li><b>بهبود ۴B کوچک و نامتقارن است:</b> CAGR +{g('4B','cagr_pct')-base['cagr_pct']:.2f} واحد و DD −{base['max_dd_pct']-g('4B','max_dd_pct'):.2f} واحد. در Train بدتر شد ({g('4B','cagr_pct','train'):.2f}٪ در برابر {rows['0_BASELINE'][R]['train']['cagr_pct']:.2f}٪؛ سود {g('4B','net_profit','train'):,.0f}$ در برابر {rows['0_BASELINE'][R]['train']['net_profit']:,.0f}$) و تمام بهبود از اعتبارسنجی آمده ({g('4B','cagr_pct','oos'):.2f}٪ در برابر {rows['0_BASELINE'][R]['oos']['cagr_pct']:.2f}٪). معیارهای تو فقط مثبت‌بودن Train را می‌خواستند و پاس شد، ولی این الگو را باید جدی گرفت.</li>
<li>۴A با فاصلهٔ ۰٫۴۱ واحد DD رد شد؛ اگر معیار DD را آسان‌تر کنی، ۴A بهتر از ۴B است (Calmar {g('4A','calmar'):.3f}). من معیار را شل نکردم.</li>
<li>مسیر درون‌دقیقه‌ای و ترتیب فازها تقریبی است؛ MFE روی نقاط مسیر (open، حد مخالف، حد موافق، close) اندازه‌گیری می‌شود. Liquidation و Mark Price بازسازی نشده‌اند.</li>
<li>بررسی سربه‌سر پیرامید در ربات، Funding را در نظر نمی‌گیرد (در بک‌تست هم همین است)، و ربات paper لغزش و Funding را شبیه‌سازی نمی‌کند.</li>
<li>پوزیشن‌های paper که پیش از این تغییر باز شده‌اند کلیدهای جدید را ندارند؛ برای آن‌ها افزودن پیرامید مسدود می‌ماند (رفتار محافظه‌کارانه).</li></ul></div>
</main></body></html>'''
(OUT/'report_verified_fixes_fa.html').write_text(page);print('final subset:',final,'| usable:',usable,'| robust:',robust)
