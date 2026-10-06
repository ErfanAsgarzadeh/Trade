from pathlib import Path
import json,html,base64
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
E=lambda s:html.escape(str(s))
N=lambda n:'—' if n is None else f'{n:,.2f}'
def main():
 d=json.loads((ROOT/'output/matrix.json').read_text());rows=d['matrix'];winner=d['winner'];coverage=json.loads((ROOT/'output/coverage.json').read_text());v=json.loads((ROOT/'output/verification.json').read_text())
 btc=sorted([x for x in rows if x['kind']=='BTC_SCALED' and x['eligible']],key=lambda x:x['full']['net_profit'],reverse=True);reference=next(x for x in rows if x['kind']=='BTC_REFERENCE')
 plt.figure(figsize=(11,4.5))
 for label,case in [('BTC 0.5%',reference),('BTC scaled',btc[0] if btc else None),('6-symbol portfolio',winner)]:
  if case is None:continue
  c=np.load(ROOT/'output'/(case['id']+'__full.npz'))['equity'];c=c[np.isfinite(c).all(axis=1)];ix=np.linspace(0,len(c)-1,min(3000,len(c)),dtype=int)
  plt.plot(pd.to_datetime(c[ix,0],unit='ms',utc=True),c[ix,1],label=label,lw=1)
 plt.axhline(10000,color='gray',lw=.6);plt.ylabel('Shared marked equity (USD)');plt.grid(alpha=.15);plt.legend();plt.tight_layout();plt.savefig(ROOT/'output/equity_comparison.png',dpi=145);plt.close()
 def summary(case,title):
  if case is None:return '<h2>'+title+'</h2><p>هیچ ترکیب واجدشرایط پیدا نشد؛ پیکربندی قبلی حفظ شده است.</p>'
  result='<h2>'+title+'</h2><p class="id">'+E(case['id'])+'</p><table><tr><th>دوره</th><th>تعداد</th><th>خالص $</th><th>بازده %</th><th>CAGR %</th><th>PF</th><th>DD %</th><th>کارمزد $</th><th>Funding $</th></tr>'
  for p,label in [('full','کل پنج سال'),('train','آموزش'),('oos','دوره بعدی')]:
   s=case[p];result+='<tr>'+''.join('<td>'+x+'</td>' for x in [label,str(s['trades']),N(s['net_profit']),N(s['return_pct']),N(s['cagr_pct']),N(s['profit_factor']),N(s['max_dd_pct']),N(s['fees']),N(s['funding_pnl'])])+'</tr>'
  result+='</table><h3>تفکیک نماد: سود خالص $ / تعداد معامله</h3><table><tr><th>نماد</th><th>کل</th><th>آموزش</th><th>دوره بعدی</th></tr>'
  for symbol in case['symbols']:result+='<tr><td>'+symbol+'</td>'+''.join('<td>'+N(case[p]['per_symbol'][symbol]['net_profit'])+' / '+str(case[p]['per_symbol'][symbol]['trades'])+'</td>' for p in ['full','train','oos'])+'</tr>'
  return result+'</table>'
 document='''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>پرتفوی و افزایش ریسک Donchian</title><style>body{font-family:Tahoma,Arial;background:#101923;color:#e3edf7;margin:24px;line-height:1.85}main{max-width:1500px;margin:auto}h1,h2,h3{color:#75d8bf}table{border-collapse:collapse;font-size:13px;width:100%;margin:14px 0}td,th{border:1px solid #34465b;padding:7px;white-space:nowrap;text-align:center}th{background:#203449}tr:nth-child(even){background:#152332}.scroll{overflow:auto}.id{direction:ltr;overflow-wrap:anywhere}.note{padding:15px;background:#243442;border-radius:9px}img{width:100%;max-width:1000px;background:white;border-radius:8px}select{padding:8px;margin:6px}a{color:#91cfff}</style><main><h1>پرتفوی Donchian + Kumo و افزایش ریسک</h1>'''
 document+='<p>بازه ثابت 2021-10-05 تا 2026-10-05 UTC، انتها غیرشامل؛ سرمایه اولیه مشترک $10,000. آموزش تا پایان ۲۰۲۴؛ دوره بعدی از 2025-01-01. ماتریس اصلی: ۴ استراتژی ثابت × ۱۰ حالت = ۴۰ ترکیب و ۱۲۰ اجرا. پس از رد تمام ۲۴ پرتفوی اصلی، ۱۶ ترکیب تکمیلی با ریسک ۰٫۳۷۵٪ و ۰٫۵٪ پیش از اجرای تکمیلی ثبت شدند؛ مجموع ۵۶ ترکیب و ۱۶۸ اجرای دوره‌ای.</p>'
 document+='<div class="note">انتخاب: بیشترین سود خالص پرتفوی، حداقل ۴۰ معامله کل، سود مثبت آموزش و دوره بعدی و افت ≤۲۵٪ در هر سه دوره. '+str(d['eligible_portfolio_count'])+' پرتفوی قبول شدند. دوره بعدی قبلاً و اکنون در انتخاب استفاده شده؛ آزمون مستقل دست‌نخورده نیست. آزمون کاهش ریسک تکمیلی به نتایج ماتریس اصلی پاسخ داده و یک پژوهش تطبیقی است.</div>'
 document+=summary(winner,'پرتفوی منتخب')+summary(btc[0] if btc else None,'BTC با افزایش ریسک: برترین ترکیب واجدشرایط')+summary(reference,'مرجع BTC با ریسک ۰٫۵٪')
 
 if winner:document+='<p class="note">سقف مارجین ۲۵٪ هدف مصرف سرمایه نیست. بیشترین مجموع مارجین رزروشده در ورود منتخب '+N(winner['full']['maximum_entry_margin_pct'])+'٪ و بیشترین نُوشنال ورودی '+N(winner['full']['maximum_entry_notional_pct'])+'٪ سرمایه بود؛ محدودیت ریسک تعیین‌کنندهٔ اندازه سفارش است.</p>'
 document+='<h2>مسیر سرمایه پس از هزینه‌های مدل</h2><img src="data:image/png;base64,'+base64.b64encode((ROOT/'output/equity_comparison.png').read_bytes()).decode()+'">'
 for original in d['declaration']['cases'][::10]:
  group=[x for x in rows if x['kind']=='PORTFOLIO' and x['eligible'] and x['strategy']['id']==original['strategy']['id']]
  if group:document+=summary(max(group,key=lambda x:x['full']['net_profit']),'برترین پرتفوی این استراتژی')
 headers=['نوع','تنظیمات','کانال','SL / Trail','ریسک %','پوزیشن']
 for p in ['کل','آموزش','دوره بعدی']:headers += [p+' تعداد',p+' خالص $',p+' بازده %',p+' CAGR %',p+' PF',p+' DD %']
 headers+=['شرایط'];table=[]
 for x in sorted(rows,key=lambda x:x['full']['net_profit'],reverse=True):
  s=x['strategy'];cells=[E(x['kind']+(' (تکمیلی)' if x.get('supplemental') else '')),E(s['setting']),str(s['lookback']),E(s['stop']+'/'+s['trail']),N(x['risk']*100),str(x['max_open_positions'])]
  for p in ['full','train','oos']:
   m=x[p];cells+=[str(m['trades']),N(m['net_profit']),N(m['return_pct']),N(m['cagr_pct']),N(m['profit_factor']),N(m['max_dd_pct'])]
  cells.append('قبول' if x['eligible'] else 'رد');table.append('<tr data-kind="'+x['kind']+'" data-eligible="'+str(int(x['eligible']))+'">'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>')
 document+='<h2>ماتریس کامل</h2><select id="kind"><option value="">همه</option><option>PORTFOLIO</option><option>BTC_SCALED</option><option>BTC_REFERENCE</option></select><select id="eligible"><option value="">همه شرایط</option><option value="1">قبول</option><option value="0">رد</option></select><div class="scroll"><table id="matrix"><thead><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join(table)+'</tbody></table></div>'
 document+='''<h2>تعریف اجرا و محدودیت‌ها</h2><ul><li>چهار ترکیب، SINGLEهای واجدشرایط قبلی با بیشترین سود کل هستند؛ یکی کانال ۱۰ و سه ترکیب کانال ۲۰ دارند. شبکه قبل از نتایج در predeclared_grid.json ثبت شده است.</li><li>BTC: ریسک ۱، ۱٫۵ و ۲٪ و سقف نُوشنال ۱۵۰٪؛ پرتفوی: ریسک ۰٫۷۵، ۱ و ۱٫۵٪، سه یا چهار پوزیشن و حداکثر مارجین ۲۵٪ هر پوزیشن با اهرم ۵؛ سقف نُوشنال هر پوزیشن ۱۲۵٪. مارجین اولیه رزروشده مجموعاً از سرمایه MTM بیشتر نمی‌شود. اهرم سود را ضرب نمی‌کند.</li><li>اولویت با بیشترین فاصله درصدی Close از مرز سخت‌تر کانال قبلی و کوموی جاری است؛ تساوی با ترتیب ثابت نمادها حل می‌شود. ورود بازار در Open اولین دقیقه پس از بسته‌شدن 4h با لغزش نامطلوب ۲bps؛ برچسب اجرای +۳ ثانیه. استاپ gap در Open و لغزش نامطلوب؛ تریل فقط پس از بسته‌شدن کندل تغییر می‌کند.</li><li>کارمزد ۰٫۱۲٪ رفت‌وبرگشت، REJECT استاپ کمتر از ۱٫۲٪ هم در سیگنال و هم Fill، و توقف ورود با زیان تحقق‌یافته خروج ۲٪ طی ۲۴ ساعت حفظ شده‌اند. Funding در این محدودیت روزانه وارد نمی‌شود، مطابق مرجع.</li><li>Funding آرشیوی واقعی تا پایان سپتامبر؛ چهار روز اکتبر با هزینه فرضی نامطلوب ۰٫۰۱٪ نُوشنال هر ۸ ساعت مدل شده‌اند. این بخش واقعی نیست و stress دوبرابری در verification.json موجود است. Funding قبل از Fill همان دقیقه پردازش می‌شود.</li><li>گام سفارش ثابت قبلی ۰٫۰۰۰۱ واحد پایه و حداقل $5 برای تمام نمادهاست. LOT_SIZE، tickSize و حداقل سفارش تاریخی بازسازی نشده‌اند. درخواست exchangeInfo قبلی HTTP 451 داد؛ محدودیت را دور نزده‌ایم.</li><li>OHLC معاملات معمولی و Open برای Funding استفاده شده‌اند؛ Mark Price، لیکوییدیشن و tierهای maintenance تاریخی مدل نشده‌اند. DD از سرمایه MTM با برآورد کارمزد خروج و مسیر فرضی هم‌زمان OHLC محاسبه شده؛ سقف ۲۵٪ به این مدل مربوط است، نه ضمانت اجرای واقعی.</li><li>هر دوره مستقل از $10,000 و بدون پوزیشن شروع و با بستن پوزیشن‌های انتهایی تمام می‌شود. جمع سود آموزش و دوره بعدی الزاماً برابر کل نیست. CAGR از مدت دقیق با سال 365.25 روز است؛ PF از خالص هر معامله پس از تمام هزینه‌های مدل.</li><li>پرتفوی مجموعهٔ ثابت شش دارایی از ابتدای دوره است؛ ریسک انتخاب نمادها بر اساس بقا وجود دارد. ربات paper و بک‌تست متفاوت‌اند: paper سفارش زنده، Funding واقعی و لغزش بک‌تست را اجرا نمی‌کند.</li></ul>'''
 document+='<h2>کنترل داده</h2><table><tr><th>نماد</th><th>دقیقه آزمون</th><th>گرم‌کردن</th><th>Funding واقعی</th><th>پنجره تطبیق</th></tr>'
 for x in coverage:document+='<tr>'+''.join('<td>'+E(y)+'</td>' for y in [x['symbol'],x['minutes'],x['warmup_minutes'],x['observed_funding_events'],sum(x['parity_windows'].values())])+'</tr>'
 document+='</table><p>۷۵۶ آرشیو اصلی و ۱۰ آرشیو روزانه بازیابی با SHA‑256؛ دقیقه تکراری/گم‌شده یا OHLC نامعتبر مجاز نیست. در SOL و XRP پنج روز (2022-02-26 تا 28 و 2022-04-01 تا 02)، هر نماد 7200 دقیقه، در آرشیو ماهانه غایب بود و از آرشیو روزانه رسمی بازیابی شد؛ قیمت مصنوعی استفاده نشد. هر چهار مرجع BTC با خطای 1e-7 بازتولید شده‌اند. کنترل '+str(v['period_ledgers_checked'])+' دفتر دوره‌ای انجام شد.</p>'
 if winner:
  document+='<h2>حساسیت پرتفوی منتخب</h2><table><tr><th>حالت</th><th>تعداد</th><th>خالص $</th><th>DD %</th></tr>'
  for label,m in v['winner_sensitivity'].items():document+='<tr>'+''.join('<td>'+y+'</td>' for y in [E(label),str(m['trades']),N(m['net_profit']),N(m['max_dd_pct'])])+'</tr>'
  document+='</table>'
 document+='''<p><a href="https://github.com/binance/binance-public-data">مستندات Binance</a> · <a href="https://data.binance.vision/">آرشیو رسمی</a></p><script>const kind=document.getElementById('kind'),eligible=document.getElementById('eligible');function filter(){for(const r of document.querySelectorAll('#matrix tbody tr'))r.hidden=Boolean((kind.value&&r.dataset.kind!==kind.value)||(eligible.value&&r.dataset.eligible!==eligible.value))}kind.addEventListener('change',filter);eligible.addEventListener('change',filter);</script></main></html>'''
 for p in [ROOT/'output/report_fa.html',ROOT.parent/'btc_backtest/output/report_fa.html']:p.write_text(document)
 print('REPORT',len(document),'rows',len(table),flush=True)
if __name__=='__main__':main()
