"""Create readable Persian report and source-free reproducibility package."""
from pathlib import Path
import json
import html
import base64
import shutil
import zipfile
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).parent
OUT=ROOT/'output'
metadata=json.loads((OUT/'summary.json').read_text())
base,cost,sensitivity=metadata['scenarios']
trades=json.loads((OUT/'execution_costs_trades.json').read_text())
fee_trades=json.loads((OUT/'strategy_fee_only_trades.json').read_text())
frame=pd.DataFrame(trades)
frame['year']=pd.to_datetime(frame.exit_time,format='ISO8601',utc=True).dt.year
annual=frame.groupby('year').agg(trades=('id','count'),net_pnl=('net_pnl','sum')).reset_index()
fee_frame=pd.DataFrame(fee_trades)
fee_frame['year']=pd.to_datetime(fee_frame.exit_time,format='ISO8601',utc=True).dt.year
fee_annual=fee_frame.groupby('year').net_pnl.sum()
annual['fee_only_profit']=annual.year.map(fee_annual)
(OUT/'annual_results.json').write_text(annual.to_json(orient='records',indent=2))

fig,ax=plt.subplots(figsize=(10.5,4.8),layout='constrained')
for name,label,color in [('strategy_fee_only','Configured fees only','#4281d8'),('execution_costs','Fees + 2 bps slippage + funding','#b6425a')]:
    equity=pd.DataFrame(json.loads((OUT/f'{name}_equity.json').read_text()))
    equity['date']=pd.to_datetime(equity.timestamp,format='ISO8601',utc=True)
    monthly=equity.set_index('date').equity_usd.resample('ME').last()
    ax.plot(monthly.index,monthly.values,label=label,color=color,linewidth=1.7)
ax.axhline(10000,color='#7c8595',linestyle='--',linewidth=1,label='Initial capital $10,000')
ax.set_title('BTCUSDT perpetual: five-year strategy backtest',loc='left',fontsize=13,pad=12)
ax.set_ylabel('Account equity (USD)');ax.grid(alpha=.18);ax.spines[['right','top']].set_visible(False)
ax.legend(loc='upper right',frameon=False,fontsize=8)
fig.savefig(OUT/'equity_curve.png',dpi=170);plt.close(fig)

fmt=lambda value:f'{value:,.2f}'
metrics=[('تعداد معامله',base['trades'],cost['trades']),('معامله سودده',base['winning_trades'],cost['winning_trades']),
         ('معامله زیان‌ده',base['losing_trades'],cost['losing_trades']),('درصد برد',fmt(base['win_rate_pct'])+'٪',fmt(cost['win_rate_pct'])+'٪'),
         ('سود خالص ($)',fmt(base['net_profit']),fmt(cost['net_profit'])),('بازده',fmt(base['return_pct'])+'٪',fmt(cost['return_pct'])+'٪'),
         ('سرمایه نهایی ($)',fmt(base['final_equity']),fmt(cost['final_equity'])),('بیشترین افت سرمایه',fmt(base['max_drawdown_pct'])+'٪',fmt(cost['max_drawdown_pct'])+'٪'),
         ('ضریب سود',fmt(base['profit_factor']),fmt(cost['profit_factor']))]
summary_rows=''.join(f'<tr><td>{label}</td><td dir="ltr">{left}</td><td dir="ltr">{right}</td></tr>' for label,left,right in metrics)
year_rows=''.join(f'<tr><td>{int(r.year)}</td><td>{int(r.trades)}</td><td dir="ltr">{fmt(r.fee_only_profit)}</td><td dir="ltr">{fmt(r.net_pnl)}</td></tr>' for r in annual.itertuples())
trade_rows=[]
for original,trade in zip(fee_trades,trades):
    assert original['id']==trade['id'] and original['signal_time']==trade['signal_time']
    values=[trade['id'],'خرید' if trade['side']=='long' else 'فروش',trade['entry_time'][:16].replace('T',' '),trade['exit_time'][:16].replace('T',' '),fmt(trade['entry_price']),f"{trade['initial_qty_btc']:.4f}",fmt(trade['gross_pnl']),fmt(trade['fees']),fmt(trade['funding_pnl']),fmt(trade['net_pnl']),fmt(original['net_pnl']),trade['exit_reason']]
    trade_rows.append('<tr>'+''.join(f'<td dir="ltr">{html.escape(str(v))}</td>' for v in values)+'</tr>')
image=base64.b64encode((OUT/'equity_curve.png').read_bytes()).decode()
page=f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بک‌تست پنج‌ساله بیت‌کوین</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;margin:0;background:#f4f6fa;color:#172238;line-height:1.9}}main{{max-width:1350px;margin:auto;padding:28px}}section{{background:white;border:1px solid #dce1ea;border-radius:12px;padding:24px;margin:20px 0}}h1{{margin:0}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:10px;border-bottom:1px solid #e1e5ec;text-align:right;white-space:nowrap}}th{{background:#edf2f9}}.scroll{{overflow:auto}}.loss{{color:#9b263b;font-weight:bold}}.note{{color:#4a5871}}img{{max-width:100%;height:auto}}a{{color:#285cb2}}ul{{padding-right:22px}}</style></head><body><main>
<h1>بک‌تست پنج‌سالهٔ بیت‌کوین</h1><p>۵ اکتبر ۲۰۲۱ تا ابتدای ۵ اکتبر ۲۰۲۶ (UTC) · قرارداد دائمی BTCUSDT بایننس</p>
<section><h2>نتیجه</h2><p class="loss">این تنظیمات در دورهٔ بررسی‌شده زیان‌ده بودند. ۲۴۱ معامله اجرا شد. سرمایهٔ ۱۰٬۰۰۰ دلاری با هزینه‌های اجرا به {fmt(cost['final_equity'])} دلار رسید.</p>
<table><thead><tr><th>شاخص</th><th>کارمزد مطابق استراتژی</th><th>کارمزد + لغزش + Funding</th></tr></thead><tbody>{summary_rows}</tbody></table>
<p class="note">هر ورود تا خروج کامل یک معامله است. TP1 و خروج باقی‌مانده دو معامله شمرده نشده‌اند. {cost['long_trades']} معامله خرید و {cost['short_trades']} معامله فروش انجام شد.</p></section>
<section><h2>مسیر سرمایه</h2><img src="data:image/png;base64,{image}" alt="Equity curves"><p class="note">نمودار از سرمایهٔ انتهای هر ماه تهیه شده است. افت سرمایه با قیمت‌های داخل مدل یک‌دقیقه‌ای محاسبه شده، نه فقط نقاط ماهانه.</p></section>
<section><h2>نتایج سالانه</h2><table><thead><tr><th>سال میلادی</th><th>معاملات بسته‌شده</th><th>سود خالص فقط با کارمزد ($)</th><th>سود خالص با هزینه‌های اجرا ($)</th></tr></thead><tbody>{year_rows}</tbody></table><p class="note">۲۰۲۱ از ۵ اکتبر و ۲۰۲۶ تا ابتدای ۵ اکتبر است. سودها بر اساس سال خروج کامل معامله گروه‌بندی شده‌اند.</p></section>
<section><h2>پارامترها و روش</h2><ul>
<li>سرمایهٔ اولیه ۱۰٬۰۰۰ دلار. ریسک هر معامله ۰٫۵٪ از سرمایهٔ جاری. حجم با سود و زیان حساب تغییر می‌کند.</li>
<li>همان تنظیمات تحویلی: روند ۴ساعته، ورود ۱ساعته، Ichimoku برابر 20/60/120/30، RSI و ATR برابر ۱۴، تمام فیلترهای Al Brooks فعال.</li>
<li>اهرم ۵ و سقف مارجین هر پوزیشن ۱۰٪. فقط بیت‌کوین معامله شده و هم‌زمان یک پوزیشن مجاز است. مقدار پایه به پایین‌ترین گام ۰٫۰۰۰۱ BTC گرد می‌شود.</li>
<li>کارمزد رفت‌وبرگشت ۰٫۱۲٪ روی ارزش ورود و خروج تقسیم شده است. در سناریوی هزینهٔ اجرا، لغزش فرضی ۰٫۰۲٪ در هر fill علیه پوزیشن اعمال شده است. این لغزش اندازه‌گیری واقعی نیست.</li>
<li>Funding با نرخ تاریخی بایننس و ارزش پوزیشن با قیمت باز شدن دقیقهٔ تسویه تخمین زده شده است. mark price واقعی زمان تسویه در این مدل وارد نشده است.</li>
<li>آخرین آرشیو Funding دریافت‌شده مربوط به سپتامبر ۲۰۲۶ است. در چهار روز پایانی اکتبر هیچ پوزیشن بازی در زمان تسویه نبود، پس نرخ‌های دریافت‌نشده روی نتیجه اثر نداشتند.</li>
<li>۲٬۶۲۹٬۴۴۰ کندل یک‌دقیقه‌ای در دورهٔ تست، به‌علاوه دادهٔ گرم‌کردن اندیکاتورها از اول اوت ۲۰۲۱. تمام ۱۲۶ آرشیو با SHA256 رسمی بررسی شدند. کندل تکراری، مفقود یا نامعتبر یافت نشد.</li>
<li>تنها کندل‌های بسته‌شده برای سیگنال مصرف شدند. پنجرهٔ ۱۹۹ کندل بسته‌شده و بازنشانی Wilder مطابق موتور قبلی بازتولید شد. برابری محاسبات در ۵۰ نقطه بررسی شد. از کندل باز HTF یا اطلاعات آینده برای تصمیم ورود استفاده نشده است.</li>
<li>زمان‌بندی +۳ ثانیه با قیمت باز شدن دقیقه تقریب زده شده است. Watchdog پانزده‌ثانیه‌ای و ترتیب واقعی تیک‌های بازار قابل بازسازی دقیق از OHLC یک‌دقیقه‌ای نیست.</li>
<li>برای خرید مسیر هر دقیقه به صورت Open→Low→High→Close و برای فروش Open→High→Low→Close فرض شد. قیمت fill داخل این مسیر مدل‌سازی شده است. زمان‌های ریز داخل دقیقه، زمان واقعی سفارش نیستند.</li>
<li>مسیر معکوس هم اجرا شد: تعداد معاملات و سود خالص سناریوی هزینهٔ اجرا برابر ماندند. افت سرمایه در آن مدل {fmt(sensitivity['max_drawdown_pct'])}٪ بود. این آزمون تضمین اجرای واقعی نیست.</li>
<li>۶۳۳ سیگنال واجد شرایط پیدا شد. ۳۷۲ setup در حالت بدون پوزیشن ساخته شد و ۱۳۱ مورد بدون ورود لغو یا منقضی شدند. ۲۴۱ مورد به معامله تبدیل شدند.</li>
<li>بازده قبل از کارمزد در سناریوی پایه مجموعاً {fmt(base['gross_profit'])} دلار بود؛ {fmt(base['fees'])} دلار کارمزد، نتیجه را به زیان تبدیل کرد.</li>
<li>۱۱ تست اختصاصی بک‌تست، از جمله جلوگیری از استفاده از آینده، Gap، خروج جزئی، حد ضرر، حسابداری و علامت Funding، پاس شدند. پارامترها بهینه‌سازی نشده‌اند.</li>
</ul><p class="note">این نتیجه متعلق به دادهٔ بایننس و مفروضات این بک‌تست است. سود یا اجرای فیوچرز LBank از آن اثبات نمی‌شود. منبع: <a href="https://github.com/binance/binance-public-data">آرشیو رسمی بایننس</a>. فهرست URL و checksum در data_manifest.json است.</p></section>
<section><h2>سود و زیان تک‌تک معاملات</h2><p class="note">زمان‌ها UTC و تقریبی هستند. مبلغ‌ها دلارند. «خالص اجرا» شامل کارمزد، لغزش و Funding است.</p><div class="scroll"><table><thead><tr><th>شماره</th><th>جهت</th><th>ورود UTC</th><th>خروج UTC</th><th>قیمت ورود</th><th>حجم BTC</th><th>ناخالص</th><th>کارمزد</th><th>Funding</th><th>خالص اجرا</th><th>خالص فقط کارمزد</th><th>علت خروج</th></tr></thead><tbody>{''.join(trade_rows)}</tbody></table></div></section>
</main></body></html>'''
(OUT/'report_fa.html').write_text(page,encoding='utf-8')
report=['# نتیجهٔ بک‌تست پنج‌سالهٔ بیت‌کوین','',
        'دوره: 2021-10-05 00:00 UTC تا 2026-10-05 00:00 UTC (انتهای دوره غیرشامل).',
        'داده: قرارداد دائمی BTCUSDT بایننس. سرمایهٔ اولیه: ۱۰٬۰۰۰ دلار. ریسک: ۰٫۵٪. روند ۴ساعته و ورود ۱ساعته.','',
        '| شاخص | فقط کارمزد استراتژی | کارمزد، لغزش و Funding |','|---|---:|---:|']
report += [f'| {label} | {left} | {right} |' for label,left,right in metrics]
report += ['', 'نتیجه: این تنظیمات در این دوره سودده نبودند. جزئیات هر ۲۴۱ معامله و روش کامل در report_fa.html است.',
           'لغزش فرضی ۰٫۰۲٪ در هر اجرا است. Funding از بایننس است. مسیر قیمت داخل دقیقه فرض شده و اجرای واقعی پانزده‌ثانیه‌ای بازسازی نشده است.',
           'فایل summary.json شامل پارامترهاست. فایل‌های trades.json معاملات کامل و exit_fills.json خروج‌های جزئی و کامل را نگه می‌دارند.',
           'بازده سالانه در annual_results.json بر اساس سال خروج معامله است. دادهٔ LBank استفاده نشده است.',
           '', '## بازتولید', 'در پوشهٔ بسته و با Python 3.11+:',
           '```bash','pip install -r btc_backtest/requirements-backtest.txt','python btc_backtest/download_data.py','python btc_backtest/backtest.py',
           'cd btc_backtest','python -m pytest test_backtest.py -q','python make_report.py','```',
           'برای نمودار matplotlib لازم است. آرشیوهای خام بازار داخل این بسته نیستند و دانلودکننده آن‌ها را از منبع رسمی می‌گیرد. فایل data_manifest.json checksum دادهٔ این اجرا را نگه می‌دارد.']
(OUT/'RESULTS_FA.md').write_text('\n'.join(report)+'\n',encoding='utf-8')

# Make a small shareable package with full ledgers and reproducible source.
paths=[ROOT/'backtest.py',ROOT/'download_data.py',ROOT/'make_report.py',ROOT/'test_backtest.py',ROOT/'requirements-backtest.txt']
paths += [p for p in OUT.iterdir() if p.suffix in ('.json','.png','.html','.md','.log')]
archive=ROOT.parent/'btc_five_year_backtest.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in paths:z.write(p,str(p.relative_to(ROOT.parent)))
    for name in ['lbank_bot.py','config.json','requirements.txt','requirements-dev.txt']:
        p=ROOT.parent/'lbank_project'/name;z.write(p,str(p.relative_to(ROOT.parent)))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print('Saved',archive,archive.stat().st_size,'bytes')
print('Annual results:',annual.to_dict('records'))
