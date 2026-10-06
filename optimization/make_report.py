"""Self-contained Persian optimization/ablation report, complete matrix and ledger."""
from pathlib import Path
import json,html,base64
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).parent;OUT=ROOT/'output';BASE=ROOT.parent/'btc_backtest/output'
m=json.loads((OUT/'matrix.json').read_text());rows={r['id']:r for r in m['matrix']}
w=rows['SINGLE__B_runner_hard4__reject__slope_ADX25'];b=rows['MTF__baseline__none__none']
verification=json.loads((OUT/'verification.json').read_text())
fmt=lambda v:'—' if v is None else f'{v:,.2f}'
esc=lambda s:html.escape(str(s))
headers=['پیکربندی','معامله','برد ٪','میانگین برد $','میانگین زیان $','کارمزد $','Funding $','PF','افت ٪','خالص $']
keys=['trades','win_rate_pct','avg_win','avg_loss','fees','funding_pnl','profit_factor','max_dd_pct','net_profit']
def table(cases,period='full',element=''):
    head=''.join('<th>'+s+'</th>' for s in headers)
    body=''.join('<tr><td dir="ltr">'+esc(c['id'])+'</td>'+''.join('<td dir="ltr">'+(str(c[period][k]) if k=='trades' else fmt(c[period][k]))+'</td>' for k in keys)+'</tr>' for c in cases)
    return f'<div class="scroll"><table {element}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
ids=['MTF__baseline__none__none','MTF__baseline__widen__none','MTF__baseline__reject__none',
     'MTF__baseline__none__slope','MTF__baseline__none__ADX20','MTF__baseline__none__ADX25',
     'MTF__A2_quarter_entry__none__none','MTF__A25_quarter_entry__none__none',
     'MTF__A2_confirm_4h__none__none','MTF__B_runner_hard4__none__none','MTF__B_pure_kijun_entry__none__none',
     'SINGLE__baseline__none__none','MTF__B_runner_hard4__reject__slope_ADX25',w['id']]
ledger=np.load(OUT/'winner_ledger.npz');t=ledger['trades'];f=ledger['fills']
reasons={3:'stop',6:'hard_tp_4R',7:'kijun_break',8:'end_of_test'}
trades=[]
for i,row in enumerate(t):
    sign=row[2];ff=f[f[:,1]==i];entry_raw=row[3]/(1+sign*.0002)
    slip=sign*(row[3]-entry_raw)*row[4]
    for fill in ff:slip+=sign*(fill[3]/(1-sign*.0002)-fill[3])*fill[2]
    trade=dict(id=i+1,side='long' if sign==1 else 'short',entry_time=pd.Timestamp(int(row[0]),unit='ms',tz='UTC').isoformat(),
        exit_time=pd.Timestamp(int(row[1]),unit='ms',tz='UTC').isoformat(),entry_price=row[3],qty_btc=row[4],
        stop_distance_pct=row[6]/row[3]*100,gross_pnl=row[7],fees=row[8],funding_pnl=row[9],net_pnl=row[10],
        estimated_slippage_cost=slip,net_R=row[10]/(row[4]*row[6]),exit_reason=reasons[int(row[11])])
    trades.append(trade)
(OUT/'winner_trades.json').write_text(json.dumps(trades,indent=2))
slippage_total=sum(x['estimated_slippage_cost'] for x in trades)
assert abs(sum(x['net_pnl'] for x in trades)-w['full']['net_profit'])<1e-7
annual={}
for tr in trades:
    year=tr['exit_time'][:4];annual.setdefault(year,dict(trades=0,net=0,fees=0))
    annual[year]['trades']+=1;annual[year]['net']+=tr['net_pnl'];annual[year]['fees']+=tr['fees']
year_rows=''.join(f'<tr><td>{year}</td><td>{annual.get(year,{}).get("trades",0)}</td><td>{fmt(annual.get(year,{}).get("net",0))}</td></tr>' for year in map(str,range(2021,2027)))
curve=ledger['equity'][:,0];start=pd.Timestamp(m['start_utc']);idx=pd.date_range(start,periods=len(curve),freq='h')
series=pd.Series(curve,index=idx).ffill().fillna(10000);series=series[series.index<pd.Timestamp(m['end_exclusive_utc'])]
base_equity=pd.DataFrame(json.loads((BASE/'execution_costs_equity.json').read_text()))
base_equity['timestamp']=pd.to_datetime(base_equity.timestamp,format='ISO8601',utc=True)
fig,ax=plt.subplots(figsize=(11,4.8),layout='constrained')
ax.plot(base_equity.set_index('timestamp').equity_usd.resample('ME').last(),label='Baseline: MTF / 241 trades',color='#b6425a')
ax.plot(series.resample('ME').last(),label='Selected: 4H runner / 8 trades',color='#257657')
ax.axhline(10000,color='#7c8595',linestyle='--',linewidth=1);ax.set_ylabel('USD equity');ax.set_title('BTCUSDT — five years, fees + slippage + funding',loc='left');ax.grid(alpha=.2);ax.legend(frameon=False);ax.spines[['top','right']].set_visible(False)
fig.savefig(OUT/'comparison.png',dpi=150);plt.close(fig)
image=base64.b64encode((OUT/'comparison.png').read_bytes()).decode()
trade_cols=['id','side','entry_time','exit_time','stop_distance_pct','gross_pnl','fees','estimated_slippage_cost','funding_pnl','net_pnl','net_R','exit_reason']
trade_head=['#','جهت','ورود UTC','خروج UTC','استاپ ٪','ناخالص $','کارمزد $','اثر لغزش $','Funding $','خالص $','خالص R','علت خروج']
trade_table='<div class="scroll"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in trade_head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td dir="ltr">'+esc(fmt(tr[k]) if isinstance(tr[k],float) else tr[k])+'</td>' for k in trade_cols)+'</tr>' for tr in trades)+'</tbody></table></div>'
fee_original=json.loads((BASE/'summary.json').read_text())['scenarios'][0]
proxy_cases=sum(x['full']['missing_funding_proxy_events']>0 for x in m['matrix'])
page=f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مقایسه و بهینه‌سازی بک‌تست بیت‌کوین</title><style>
body{{font-family:Tahoma,Arial,sans-serif;line-height:1.9;background:#f4f6fa;color:#172238;margin:0}}main{{max-width:1450px;margin:auto;padding:26px}}section{{background:white;border:1px solid #dce1ea;border-radius:12px;padding:24px;margin:20px 0}}h1{{margin:0}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:10px;border-bottom:1px solid #dce1ea;text-align:right;white-space:nowrap}}th{{background:#edf2f9;position:sticky;top:0}}.scroll{{overflow:auto}}.muted{{color:#4a5871}}.warning{{background:#fff1d5;padding:16px;border-radius:8px}}code{{direction:ltr;unicode-bidi:embed}}img{{width:100%;height:auto}}input{{padding:10px;width:min(95%,600px);border:1px solid #ccd3df;border-radius:8px}}a{{color:#285cb2}}
</style></head><body><main><h1>بک‌تست بهینه‌سازی و حذف‌و‌اضافهٔ بیت‌کوین</h1><p>۵ اکتبر ۲۰۲۱ تا ابتدای ۵ اکتبر ۲۰۲۶ UTC · ۲٬۶۲۹٬۴۴۰ کندل یک‌دقیقه‌ای BTCUSDT دائمی · سرمایه اولیه ۱۰٬۰۰۰ دلار</p>
<section><h2>نتیجه و تنظیم انتخاب‌شده</h2><p>۴۳۲ پیکربندی غیرتکراری، هرکدام روی کل دوره، دوره آموزش و دوره بعدی اجرا شدند (۱٬۲۹۶ اجرای مقایسه‌ای). معیار انتخاب، بیشترین سود خالص کل دوره و سپس PF بود. برنده سود و برنده PF یکسان شدند.</p>{table([b,w])}
<p>ورود، رژیم و تریل همگی ۴ساعته؛ فیلتر شیب Kijun در سه کندل و Tenkan در دو کندل، ADX Wilder(14)≥۲۵؛ بدون خروج جزئی؛ سربه‌سر فقط در ۲R؛ هدف سخت ۴R؛ استاپ تریل Kijun±۰٫۵ATR. شکست Kijun با بسته‌شدن کندل در سمت نامطلوب خط موجب خروج کامل می‌شود. علامت فاصله‌ها برای فروش معکوس است.</p>
<p>حداقل فاصله استاپ ۱٫۲٪ با سیاست REJECT در config فعال شد. در ترکیب برنده، NONE، WIDEN و REJECT نتیجه دقیقاً یکسان داشتند؛ هیچ ستاپ کم‌فاصله‌ای رد یا تغییر نکرد. انتخاب REJECT در میان این تساوی، نتیجه بک‌تست را عوض نمی‌کند.</p>
<p>کارمزد از {fmt(b['full']['fees'])} به {fmt(w['full']['fees'])} دلار کاهش یافت ({fmt((1-w['full']['fees']/b['full']['fees'])*100)}٪). عدد تاریخی {fmt(fee_original['total_fees']) if 'total_fees' in fee_original else '869.94'} دلار متعلق به سناریوی فقط کارمزد بود؛ با اضافه شدن لغزش و Funding، اندازه پوزیشن و کارمزد مبنا تغییر می‌کند.</p>
<p class="warning">این برنده با دیدن کل دوره انتخاب شده و فقط ۸ معامله دارد؛ سود تاریخی ۱٫۲۵٪ طی پنج سال اثبات مزیت پایدار نیست. از ۴۳۲ جست‌وجو برای انتخاب استفاده شده است؛ دوره دوم نیز آزمون مستقلِ دست‌نخورده محسوب نمی‌شود.</p></section>
<section><h2>تشخیص مکانیک مبنا</h2><p>در سناریوی فقط کارمزد، ۸۸ از ۱۰۲ معامله سودده با استاپ تمام شدند (۸۶٫۲۷٪) و فقط ۱۴ معامله با شکست Kijun بسته شدند. ۱۴ معامله از ۲۴۱ معامله استاپ اولیه کمتر از ۰٫۶٪ داشتند؛ این تعداد به‌تنهایی علت تمام هزینه‌ها را توضیح نمی‌دهد. در سناریوی همه هزینه‌ها، ۸۷ از ۱۰۱ برد با استاپ و ۱۴ خروج با شکست Kijun ثبت شد. رفتار بازار رنج و اثر فیلترها با مقایسه‌های زیر سنجیده شده، نه با فرض قطعی علت هر معامله.</p></section>
<section><h2>مقایسه اصلاح‌های مستقل و MTF با SINGLE</h2>{table([rows[i] for i in ids])}<p>در ردیف‌های اصلاح مستقل، سایر پارامترها ثابت‌اند. تغییر خروج به‌تنهایی زیان را افزایش داد؛ رد استاپ کوچک به‌تنهایی سود خالص ۸۱٫۳۰ دلار داد. تغییر به SINGLE با خروج قدیمی هنوز زیان‌ده است. مقایسه دو ردیف آخر، همان خروج، فیلتر و حداقل استاپ را با ورود ۱ساعته و ۴ساعته مقایسه می‌کند.</p></section>
<section><h2>مسیر سرمایه و توزیع سالانه برنده</h2><img src="data:image/png;base64,{image}" alt="Baseline and selected strategy equity"><p class="muted">نمودار از نقاط انتهای ماه است؛ Max DD از مسیر دقیقه‌ای و نقاط رویداد محاسبه شده است. ستون سال بر اساس تاریخ خروج معامله است؛ سال اول و آخر ناقص‌اند.</p><table><tr><th>سال</th><th>معامله</th><th>خالص $</th></tr>{year_rows}</table></section>
<section><h2>آموزش در برابر دوره بعدی</h2><p>آموزش: ۲۰۲۱/۱۰/۰۵ تا ابتدای ۲۰۲۵/۰۱/۰۱؛ دوره بعدی: ۲۰۲۵/۰۱/۰۱ تا ابتدای ۲۰۲۶/۱۰/۰۵. هر دوره از سرمایه ۱۰٬۰۰۰ دلار و بدون پوزیشن شروع می‌شود و پوزیشن باز در انتهای دوره بسته می‌شود؛ بنابراین مجموع دو دوره دقیقاً با اجرای پیوسته برابر نیست.</p><h3>آموزش</h3>{table([w,m['train_selected']], 'train')}<h3>دوره بعدی</h3>{table([w,m['train_selected']], 'validation')}<p class="warning">برنده‌ای که صرفاً با سود آموزش انتخاب شد، MTF + خروج قدیمی + رد استاپ زیر ۱٫۲٪ بود؛ در دوره بعدی {fmt(m['train_selected']['validation']['net_profit'])} دلار زیان داد. این نتیجه، حساسیت انتخاب تنظیمات را نشان می‌دهد.</p></section>
<section><h2>هزینه‌ها، منبع و قرارداد اجرای یکسان</h2><ul><li>همان ۱۲۶ آرشیو رسمی Binance USD-M و SHA-256 ثبت‌شده در data_manifest.json؛ ۱۹۹ کندل بسته از هر پنجره fetch=۲۰۰ و گرم‌کردن از اوت ۲۰۲۱. هیچ کندل باز یا داده آینده در سیگنال استفاده نشده است.</li><li>ریسک ۰٫۵٪، سقف نُوشنال ۵۰٪ سرمایه، کارمزد رفت‌وبرگشت ۰٫۱۲٪، لغزش نامطلوب ۲ basis point در هر fill، Funding واقعی بایننس با جهت و موجودی پوزیشن؛ Funding مثبت دریافتی و منفی پرداختی است. لغزش در قیمت اجرا و ناخالص لحاظ شده و دوباره از خالص کسر نمی‌شود.</li><li>برنده: ناخالص پس از لغزش {fmt(w['full']['gross_pnl'])} دلار − کارمزد {fmt(w['full']['fees'])} + Funding {fmt(w['full']['funding_pnl'])} = خالص {fmt(w['full']['net_profit'])} دلار. اثر مستقیم لغزش بر همان fillها {fmt(slippage_total)} دلار بود؛ حذف لغزش ممکن است مسیر پوزیشن را تغییر دهد، پس این عدد یک اجرای بدون لغزش نیست.</li><li>Funding آرشیوی چهار روز اول اکتبر ۲۰۲۶ در دسترس نبود. برای پوزیشن فعالِ ترکیب‌های متاثر، هر ۸ ساعت هزینه نامطلوب فرضی ۰٫۰۱٪ نُوشنال اعمال شد؛ {proxy_cases} ترکیب دارای این فرض‌اند. مبنا و برنده هیچ رویداد Funding فرضی ندارند. داده LBank یا Funding آن در این آزمون استفاده نشده است.</li><li>هر ورود تا خروج کامل یک معامله؛ PF و میانگین برد/باخت از سود خالص معامله شامل همه هزینه‌ها؛ Avg Loss منفی است. خالص R بر اساس فاصله اولیه استاپ×حجم واقعی محاسبه می‌شود. سفارش‌های لغوشده معامله شمرده نشده‌اند.</li><li>مسیر دقیقه برای خرید O-L-H-C و برای فروش O-H-L-C است؛ رویدادها روی مسیر بین OHLC حل می‌شوند. پنجره tick پانزده‌ثانیه‌ای از OHLC قابل بازیابی نیست. اسکن کندل در دقیقه بازشدن بعدی با برچسب +۳ ثانیه مدل شده است.</li><li>ADX با هموارسازی Wilder و seed دوره−۱ در هر پنجره ۱۹۹ کندلی محاسبه می‌شود. شرط Kijun غیرسخت و شرط Tenkan سخت است؛ ADX=threshold پذیرفته می‌شود. جست‌وجو: ۱۵ تعریف خروج، دو حالت، سه سیاست استاپ و شش فیلتر؛ حالت‌های یکسانِ تریل در SINGLE حذف شدند.</li></ul></section>
<section><h2>کنترل نتیجه و تست‌ها</h2><p>موتور سریع برای تعداد معامله، سود خالص و Max DD مبنا با موتور قبلی دقیقاً تطبیق داده شد. برنده و مبنا دوباره اجرا و هزینه‌های دفتر معاملات تطبیق داده شدند. ADX در ۲۴ پنجره واقعی با کد ربات برابر بود.</p><p>با معکوس کردن ترتیب High/Low، سود برنده {fmt(verification['winner_reversed']['net_profit'])} دلار و تعداد معاملات {verification['winner_reversed']['trades']} شد؛ سود مبنا {fmt(verification['baseline_reversed']['net_profit'])} دلار بود. این آزمون جایگزین داده tick نیست.</p><p>تست‌های خروج جزئی، سربه‌سر در ۲R بدون فروش جزئی، هدف کامل ۴R در هر دو جهت، استاپ حداقل، ADX، فیلتر شیب، انتظار برای کندل تازه ۴ساعته و سازگاری پوزیشن قدیمی اجرا شدند؛ ۱۰۱ تست پایتون و تست JavaScript داشبورد گذشتند؛ جزئیات در TEST_RESULTS.md.</p><p>کد config.json و lbank_bot.py به‌روزرسانی شده‌اند. حالت dry-run قبلی حفظ شده است؛ این اجرای تاریخی سفارش واقعی در LBank ثبت نمی‌کند. PnL نمایشی ربات کاغذی مثل نسخه قبلی فقط کارمزد دارد؛ Funding و لغزش در موتور این بک‌تست محاسبه شده‌اند.</p></section>
<section><h2>تمام معاملات برنده</h2>{trade_table}</section>
<section><h2>ماتریس کامل ۴۳۲ ترکیب</h2><p>مرتب‌شده بر اساس سود خالص کل دوره. بخش stop: none/widen/reject؛ momentum: none/slope/ADX20/ADX25/slope_ADX20/slope_ADX25. A2 و A25: TP در ۲ یا ۲٫۵R و بستن ۳۵٪؛ quarter: استاپ در منفی ۰٫۲۵R؛ confirm: نگه‌داشتن استاپ تا بسته‌شدن کندل در ۲R؛ entry/4h تایم‌فریم تریل است. B_runner: سربه‌سر در ۲R بدون خروج جزئی؛ hard3/hard4: هدف نهایی ۳/۴R؛ pure_kijun: تریل از ورود بدون انتقال اجباری به سربه‌سر.</p><input id="filter" type="search" placeholder="جست‌وجو: مثلاً SINGLE یا reject یا A25">{table(m['matrix'],element='id="matrix"')}<p class="muted">برای پارامترهای عددی دقیق، نتایج هر سه دوره و تعداد رویدادهای Funding فرضی، matrix.json را ببینید.</p></section>
</main><script>document.getElementById('filter').addEventListener('input',function(){{const query=this.value.toLowerCase();for(const row of document.querySelectorAll('#matrix tbody tr'))row.hidden=!row.cells[0].textContent.toLowerCase().includes(query)}});</script></body></html>'''
(OUT/'report_fa.html').write_text(page)
(BASE/'report_fa.html').write_text(page)
(ROOT/'output/selection.json').write_text(json.dumps(dict(deployed_id=w['id'],tie_ids=[x['id'] for x in m['matrix'] if abs(x['full']['net_profit']-w['full']['net_profit'])<1e-9],slippage_cost_at_fixed_fills=slippage_total),indent=2))
print('Report generated:',len(page),'characters')
