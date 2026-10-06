"""Self-contained Persian benchmark report, all periods and full winning ledger."""
from pathlib import Path
import json,html,base64
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).parent;OUT=ROOT/'output';BASE=ROOT.parent/'btc_backtest/output'
m=json.loads((OUT/'matrix.json').read_text());v=json.loads((OUT/'verification.json').read_text());winner=m['winner']
assert winner and winner['eligible']
prior=json.loads((ROOT.parent/'optimization/output/matrix.json').read_text());baseline=next(x for x in prior['matrix'] if x['id']=='MTF__baseline__none__none');micro=next(x for x in prior['matrix'] if x['id']=='MTF__baseline__reject__none')
old_stats=json.loads((BASE/'summary.json').read_text())['scenarios'][1]
for k in ['long_trades','short_trades']:baseline['full'][k]=old_stats[k]
old_ledger=np.load(ROOT.parent/'optimization/output/train_winner_ledger.npz')['trades']
micro['full']['long_trades']=int((old_ledger[:,2]==1).sum());micro['full']['short_trades']=int((old_ledger[:,2]==-1).sum())
families={'ICHI_BREAKOUT':'۱: شکست ایچیموکو','ICHI_PULLBACK':'۲: پولبک اصلاح‌شده ایچیموکو','EMA_PULLBACK':'۳: پولبک EMA20','DONCHIAN':'۴: شکست Donchian / Kumo'}
periods={'full':'کل پنج سال','train':'آموزش ۲۰۲۱–۲۰۲۴','oos':'دوره بعدی ۲۰۲۵–۲۰۲۶'}
fmt=lambda n:'—' if n is None else f'{n:,.2f}'
esc=lambda s:html.escape(str(s))
keys=['trades','long_trades','short_trades','win_rate_pct','avg_win','avg_loss','fees','funding_pnl','profit_factor','max_dd_pct','net_profit']
heads=['معامله','خرید','فروش','برد ٪','میانگین برد $','میانگین باخت $','کارمزد $','Funding $','PF','افت ٪','خالص $']
def metric_table(items):
    result='<div class="scroll"><table><thead><tr><th>پیکربندی / دوره</th>'+''.join('<th>'+x+'</th>' for x in heads)+'</tr></thead><tbody>'
    for label,data in items:
        result+='<tr><td>'+esc(label)+'</td>'+''.join('<td dir="ltr">'+(str(data[k]) if k in ['trades','long_trades','short_trades'] else fmt(data[k]))+'</td>' for k in keys)+'</tr>'
    return result+'</tbody></table></div>'
leaders=[]
for fam in families:
    for mode in ['SINGLE','MTF']:
        group=[x for x in m['matrix'] if x['family']==fam and x['mode']==mode];eligible=[x for x in group if x['eligible']]
        leaders.append((families[fam]+' · '+mode,(eligible or group)[0],len(eligible)))
leader_rows=''
for label,case,count in leaders:
    leader_rows+=f'<tr><td>{esc(label)}</td><td dir="ltr">{esc(case["id"])}</td><td>{case["full"]["trades"]}</td><td>{fmt(case["full"]["net_profit"])}</td><td>{fmt(case["train"]["net_profit"])}</td><td>{fmt(case["oos"]["net_profit"])}</td><td>{"پذیرفته" if case["eligible"] else "رد"}</td><td>{count}</td></tr>'
all_rows=''
for case in m['matrix']:
    eligibility='پذیرفته' if case['eligible'] else 'رد'
    all_rows+=f'<tr data-eligible="{int(case["eligible"])}"><td>{families[case["family"]]}</td><td dir="ltr">{esc(case["id"])}</td><td>{case["full"]["trades"]}</td><td>{fmt(case["full"]["net_profit"])}</td><td>{fmt(case["train"]["net_profit"])}</td><td>{fmt(case["oos"]["net_profit"])}</td><td>{fmt(case["full"]["profit_factor"])}</td><td>{fmt(case["full"]["max_dd_pct"])}</td><td>{fmt(case["full"]["fees"])}</td><td>{case["full"]["missing_funding_proxy_events"]}</td><td>{eligibility}</td></tr>'
ledger=np.load(OUT/'winner_ledger.npz');t=ledger['trades'];f=ledger['fills'];raw=np.load(ROOT.parent/'optimization/features.npz');prices=raw['prices'];funding=raw['funding']
start=int(pd.Timestamp(m['start_utc']).timestamp()*1000);trades=[];proxy_total=0
reason={3:'stop',6:'hard_tp',7:'close_through',8:'end_of_period'}
for i,row in enumerate(t):
    sign=row[2];ff=f[f[:,1]==i];slip=sign*(row[3]-row[3]/(1+sign*.0002))*row[4]
    for fill in ff:slip+=sign*(fill[3]/(1-sign*.0002)-fill[3])*fill[2]
    proxy=0.
    for stamp in range(1790812800000,1791158400000,28800000):
        index=(stamp-start)//60000
        if row[0]<stamp<=row[1] and np.isnan(funding[index]):proxy+=prices[index,0]*row[4]*.0001
    proxy_total+=proxy
    trades.append(dict(id=i+1,side='long' if sign==1 else 'short',entry_time=pd.Timestamp(int(row[0]),unit='ms',tz='UTC').isoformat(),exit_time=pd.Timestamp(int(row[1]),unit='ms',tz='UTC').isoformat(),entry_price=row[3],qty_btc=row[4],stop_distance_pct=row[6]/row[3]*100,gross_pnl=row[7],fees=row[8],slippage_cost=slip,funding_pnl=row[9],missing_funding_proxy_cost=proxy,net_pnl=row[10],net_R=row[10]/(row[4]*row[6]),exit_reason=reason[int(row[11])]))
assert all(tr['stop_distance_pct']>=1.2-1e-10 for tr in trades)
assert abs(sum(tr['net_pnl'] for tr in trades)-winner['full']['net_profit'])<1e-7
(OUT/'winner_trades.json').write_text(json.dumps(trades,indent=2))
annual=[]
for year in range(2021,2027):
    group=[x for x in trades if x['exit_time'].startswith(str(year))]
    annual.append(dict(year=year,trades=len(group),longs=sum(x['side']=='long' for x in group),shorts=sum(x['side']=='short' for x in group),net_pnl=sum(x['net_pnl'] for x in group),fees=sum(x['fees'] for x in group)))
(OUT/'annual_results.json').write_text(json.dumps(annual,indent=2))
year_rows=''.join('<tr>'+''.join('<td>'+esc(str(r[k]) if k in ['year','trades','longs','shorts'] else fmt(r[k]))+'</td>' for k in ['year','trades','longs','shorts','net_pnl','fees'])+'</tr>' for r in annual)
def monthly_points(series):
    values=series.resample('ME').last()
    limit=pd.Timestamp(m['end_exclusive_utc'])
    values.index=pd.DatetimeIndex([min(x,limit) for x in values.index])
    return values
fig,ax=plt.subplots(figsize=(11,5.4),layout='constrained')
for family,label,color in [('ICHI_BREAKOUT','Ichimoku breakout (fails eligibility)','#b77b2d'),('ICHI_PULLBACK','Fixed Ichimoku pullback','#5a67b5'),('EMA_PULLBACK','EMA20 pullback (fails eligibility)','#8595a6'),('DONCHIAN','Donchian / Kumo selected','#257657')]:
    data=np.load(OUT/f'{family}_leader_ledger.npz')['equity'][:,0]
    idx=pd.date_range(m['start_utc'],periods=len(data),freq='h');s=pd.Series(data,index=idx).ffill().fillna(10000);s=s[s.index<=pd.Timestamp(m['end_exclusive_utc'])]
    ax.plot(monthly_points(s),label=label,color=color,linestyle='--' if family in ['ICHI_BREAKOUT','EMA_PULLBACK'] else '-',linewidth=1.7)
be=pd.DataFrame(json.loads((BASE/'execution_costs_equity.json').read_text()));be['date']=pd.to_datetime(be.timestamp,format='ISO8601',utc=True)
ax.plot(monthly_points(be.set_index('date').equity_usd),label='Original baseline',color='#b6425a',linewidth=1.2)
ax.axhline(10000,color='#7c8595',linestyle=':',linewidth=1);ax.set_title('Four clean BTCUSDT archetypes — all execution costs',loc='left');ax.set_ylabel('Equity USD');ax.grid(alpha=.18);ax.legend(frameon=False,fontsize=8,loc='upper left');ax.spines[['right','top']].set_visible(False)
fig.savefig(OUT/'equity_comparison.png',dpi=150);plt.close(fig)
image=base64.b64encode((OUT/'equity_comparison.png').read_bytes()).decode()
trade_keys=['id','side','entry_time','exit_time','stop_distance_pct','gross_pnl','fees','slippage_cost','funding_pnl','net_pnl','net_R','exit_reason']
trade_heads=['#','جهت','ورود UTC','خروج UTC','فاصله استاپ ٪','ناخالص $','کارمزد $','اثر لغزش $','Funding $','خالص $','خالص R','خروج']
trade_rows=''.join('<tr>'+''.join('<td dir="ltr">'+esc(fmt(x[k]) if isinstance(x[k],float) else x[k])+'</td>' for k in trade_keys)+'</tr>' for x in trades)
eligible=[x for x in m['matrix'] if x['eligible']];pf_leader=max(eligible,key=lambda x:x['full']['profit_factor'] or 0);train_leader=max(m['matrix'],key=lambda x:x['train']['net_profit'])
full_detail=''.join('<details><summary>'+esc(label)+' · '+('پذیرفته' if case['eligible'] else 'بدون پیکربندی واجد شرایط')+'</summary><p dir="ltr">'+esc(case['id'])+'</p>'+metric_table([(periods[p],case[p]) for p in periods])+'</details>' for label,case,count in leaders)
page=f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بنچمارک چهار خانوادهٔ تمیز بیت‌کوین</title><style>
body{{font-family:Tahoma,Arial,sans-serif;line-height:1.9;background:#f4f6fa;color:#172238;margin:0}}main{{max-width:1450px;margin:auto;padding:26px}}section{{background:white;border:1px solid #dce1ea;border-radius:12px;padding:24px;margin:20px 0}}h1{{margin:0}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:10px;border-bottom:1px solid #dce1ea;text-align:right;white-space:nowrap}}th{{background:#edf2f9}}.scroll{{overflow:auto;max-height:700px}}.warning{{background:#fff1d5;padding:16px;border-radius:8px}}.muted{{color:#4a5871}}img{{width:100%;height:auto}}input[type=search]{{padding:10px;width:min(90%,600px);border:1px solid #ccd3df;border-radius:8px}}details{{padding:14px;border-bottom:1px solid #ddd}}summary{{cursor:pointer}}a{{color:#285cb2}}code{{direction:ltr;unicode-bidi:embed}}</style></head><body><main>
<h1>بنچمارک چهار خانوادهٔ تمیز BTCUSDT</h1><p>۵ اکتبر ۲۰۲۱ تا ابتدای ۵ اکتبر ۲۰۲۶ UTC · ۲٬۶۲۹٬۴۴۰ کندل یک‌دقیقه‌ای · قرارداد دائمی بایننس · سرمایه اولیه هر اجرای مستقل ۱۰٬۰۰۰ دلار</p>
<section><h2>برنده طبق معیارهای درخواستی</h2><p>۱۱۲ پیکربندی از چهار خانواده × سه دوره = ۳۳۶ اجرا. {m['eligible_count']} پیکربندی شرط حداقل ۴۰ معامله در کل دوره و سود خالص مثبت در هر دو دوره را گذراندند. رتبه‌بندی بین واجدشرایط‌ها بر اساس سود خالص کل دوره و سپس PF است.</p><p dir="ltr">{esc(winner['id'])}</p>{metric_table([(periods[p],winner[p]) for p in periods])}
<p>تنظیم انتخاب‌شده: SINGLE چهار‌ساعته؛ ایچیموکو استاندارد (۹،۲۶،۵۲،۲۶) برای Kumo و Kijun؛ بسته‌شدن قیمت بالاتر از بالاترین High بیست کندل قبلی و بالای Kumo برای خرید، و معکوس آن برای فروش؛ ورود بازار در اولین دقیقه بعد از بسته‌شدن. استاپ اولیه Kijun(26)؛ رد فاصله کمتر از ۱٫۲٪؛ تریل استاپ روی کمترین Low ده کندل بسته اخیر برای خرید و بیشترین High ده کندل بسته اخیر برای فروش. بدون RSI، ADX، H2/L2، Barb Wire، خروج جزئی، سربه‌سر اجباری یا هدف سخت.</p>
<p>{winner['full']['long_trades']} خرید و {winner['full']['short_trades']} فروش در این اجرا ثبت شد. معیار صریح شما سقف تعداد معامله ندارد؛ برنده {winner['full']['trades']} معامله دارد. هیچ پیکربندی واجدشرایطی در بازه هدف ۴۰ تا ۶۰ معامله پیدا نشد، بنابراین هدف فرکانس پایین ۲۵–۶۰ معامله در این شبکه محقق نشده است.</p>
<p class="warning">سود دوره ۲۰۲۵–۲۰۲۶ فقط {fmt(winner['oos']['net_profit'])} دلار و PF آن {fmt(winner['oos']['profit_factor'])} است؛ حاشیه مثبت ضعیف‌تر از آموزش است. چون از این دوره برای فیلتر و انتخاب استفاده شده، این نتیجه یک آزمون مستقل دست‌نخورده نیست. «پذیرفته» صرفاً یعنی عبور از شروط تعیین‌شده، نه اثبات سود آینده.</p></section>
<section><h2>بهترین پیکربندی هر خانواده در SINGLE و MTF</h2><p>اگر گروه واجدشرایط دارد، بهترین سود خالص بین همان‌ها نمایش داده می‌شود؛ در غیر این صورت، بهترین سود کل دوره نمایش داده و صریحاً «رد» علامت زده می‌شود.</p><div class="scroll"><table><thead><tr><th>خانواده / حالت</th><th>شناسه</th><th>معامله کل</th><th>خالص کل $</th><th>خالص آموزش $</th><th>خالص دوره بعدی $</th><th>وضعیت</th><th>تعداد واجدشرایط گروه</th></tr></thead><tbody>{leader_rows}</tbody></table></div>{full_detail}</section>
<section><h2>مقایسه با دو مرجع قبلی</h2>{metric_table([('مبنای اولیه، همه هزینه‌ها',baseline['full']),('اصلاح مستقل: رد استاپ کوچک',micro['full']),('برنده چهار خانواده',winner['full'])])}<p>در معیار جدید، برنده قدیمی با هشت معامله خودبه‌خود حذف می‌شود. فیلترهای قبلی ورود را محدود می‌کردند؛ اما تماس با Kijun و RSI≥۵۰ تناقض ریاضی قطعی ندارند: RSI از تغییرات Close محاسبه می‌شود، در حالی که تماس ممکن است فقط با سایه Low رخ دهد. این هم‌زمانی با تست عددی بررسی شده است. <a href="https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/">فرمول RSI</a></p></section>
<section><h2>تعریف ثابت خانواده‌ها و گزینه‌ها</h2><ul>
<li>خانواده ۱: تنظیم استاندارد و Crypto، شکست تازه Kumo یا بازپس‌گیری Tenkan بیرون Kumo، Tenkan/Kijun و ابر آینده هم‌جهت، Close فعلی بالاتر از High مربوط به displacement قبلی (یا معکوس)، RSI&gt;۵۵ / &lt;۴۵. در MTF، فیلتر بالادستی صرفاً بیرون Kumo چهار‌ساعته است. خروج Kijun فقط با بسته‌شدن در سمت نامطلوب، یا هدف کامل ۳R/۴R بدون خروج جزئی و بدون سربه‌سر زودهنگام. استاپ اولیه Kijun±۰٫۵ATR.</li>
<li>خانواده ۲: روند چهار‌ساعته بیرون Kumo، Tenkan/Kijun و ابر آینده هم‌جهت؛ ورود بیرون Kumo با تماس مطابق max/min(Tenkan,Kijun)±۰٫۳ATR و بسته‌شدن در سمت مطلوب Kijun؛ RSI خرید ۳۸–۶۵ و فروش ۳۵–۶۲؛ کندل هم‌جهت. هر دو تنظیم ایچیموکو، ورود بازار یا شکست High/Low سیگنال، خروج بسته‌شدن Kijun / هدف ۳R / هدف ۴R / سربه‌سر ۲R و تریل Kijun با بافر ۰٫۵ATR. استاپ اولیه Kijun±۰٫۵ATR.</li>
<li>خانواده ۳: Close چهار‌ساعته و EMA20 چهار‌ساعته در سمت مطلوب EMA50؛ تماس EMA20 تایم‌فریم ورود و بازگشت Close در سمت مطلوب آن، با کندل برگشتی/روند مکانیکی؛ شکست High/Low سیگنال؛ با و بدون H2/L2. H2/L2 در این آزمون تعریف مکانیکیِ «تلاش قبلی، پولبک مجدد، تلاش دوم» در هشت کندل است، نه قضاوت اختیاری روی نمودار. استاپ پشت کندل سیگنال±۰٫۵ATR. خروج ۱٫۵R با بستن ۵۰٪ و تریل، یا سربه‌سر در ۲R بدون خروج جزئی؛ تریل EMA20 یا Kijun26 یا Kijun60.</li>
<li>خانواده ۴: شکست ساختاری چهار‌ساعتهٔ High/Low ده یا بیست کندل <strong>قبلی</strong> همراه بیرون Kumo؛ هر دو تنظیم ایچیموکو؛ استاپ Kijun یا ۲ATR؛ تریل بسته‌شدن Kijun یا استاپ روی extreme مخالف ده کندل بسته. سیگنال و استاپ اولیه در SINGLE و MTF چهار‌ساعته‌اند؛ MTF فقط تریل یک‌ساعته را مقایسه می‌کند تا تعریف «شکست ساختاری ۴H» حفظ شود. کندل جاری در کانال ورود وارد نمی‌شود.</li>
<li>سفارش‌های شکست ثابتِ یک‌بار انقضا ندارند؛ تا برخورد به استاپ ساختاری، لغو جهت روند، توقف ورود یا پایان دوره معتبرند. جهت روند قبل از فعال‌سازی در مرز کندل دوباره کنترل می‌شود. ورود بازار از قیمت آیندهٔ Close استفاده نمی‌کند: تأیید کندل بسته و اجرا در Open دقیقه بعد با برچسب +۳ ثانیه است.</li>
</ul></section>
<section><h2>هزینه، داده و محدودیت Funding</h2><p>همان ۱۲۶ آرشیو رسمی Binance USD-M با SHA-256 ثبت‌شده، گرم‌کردن از اوت ۲۰۲۱، بدون کندل دقیقه‌ای گمشده؛ فقط کندل‌های بسته. RSI/ATR Wilder مثل موتور قبلی از پنجره ۱۹۹ کندلی محاسبه می‌شوند؛ EMA با seed میانگین دوره و همان پنجره. ریسک ۰٫۵٪، سقف نُوشنال ۵۰٪ سرمایه، افت روزانه ۲٪، کارمزد رفت‌وبرگشت ۰٫۱۲٪ و لغزش نامطلوب ۲bps هر fill ثابت‌اند. REJECT در سیگنال و قیمت واقعی fill برای استاپ کمتر از ۱٫۲٪ اعمال می‌شود.</p>
<p>ناخالص پس از لغزش {fmt(winner['full']['gross_pnl'])} − کارمزد {fmt(winner['full']['fees'])} + Funding {fmt(winner['full']['funding_pnl'])} = خالص {fmt(winner['full']['net_profit'])} دلار. اثر مستقیم لغزش روی همین fillها {fmt(sum(x['slippage_cost'] for x in trades))} دلار است؛ در ناخالص لحاظ شده و دوباره کسر نمی‌شود. Funding مثبت دریافتی و منفی پرداختی است.</p>
<p class="warning">Funding واقعی تا سپتامبر ۲۰۲۶ موجود است؛ آرشیو چهار روز اول اکتبر در دسترس نبود. همان فرض هزینه نامطلوب ۰٫۰۱٪ نُوشنال هر هشت ساعتِ موتور قبلی حفظ شد. برنده {winner['full']['missing_funding_proxy_events']} رویداد فرضی با مجموع هزینه {fmt(proxy_total)} دلار دارد؛ بنابراین همه Funding دوره واقعی نیست. با دو برابر کردن این هزینه فرضی، سود کل {fmt(v['winner_double_missing_funding_cost']['net_profit'])} دلار شد. دسترسی API مسدود دور زده نشده است.</p>
<p>مسیر OHLC دقیقه‌ای برای خرید O-L-H-C و برای فروش O-H-L-C است؛ tick پانزده‌ثانیه‌ای قابل بازیابی نیست. مسیر معکوس برای برنده {v['winner_reversed']['trades']} معامله و سود {fmt(v['winner_reversed']['net_profit'])} دلار داد. نتایج قرارداد بایننس‌اند و هزینه‌های واقعی LBank را اثبات نمی‌کنند.</p></section>
<section><h2>مسیر سرمایه و نتایج سالانه برنده</h2><img src="data:image/png;base64,{image}" alt="Four family leaders and original baseline equity"><p class="muted">نمودار آخرین نمونهٔ موجود هر ماه است؛ اکتبر ۲۰۲۶ ناقص است؛ Max DD از مسیر داخل دقیقه محاسبه شده است. دو خط نقطه‌چین خانواده‌های فاقد پیکربندی واجدشرایط را نشان می‌دهند. سال معامله، سال خروج کامل است؛ سال‌های ۲۰۲۱ و ۲۰۲۶ کامل نیستند.</p><table><thead><tr><th>سال</th><th>معامله</th><th>خرید</th><th>فروش</th><th>خالص $</th><th>کارمزد $</th></tr></thead><tbody>{year_rows}</tbody></table></section>
<section><h2>انتخاب، دوره‌ها و کنترل پیاده‌سازی</h2><p>آموزش از ۲۰۲۱/۱۰/۰۵ تا ابتدای ۲۰۲۵/۰۱/۰۱ و دوره بعدی تا ابتدای ۲۰۲۶/۱۰/۰۵ است. هر اجرای مستقل سرمایه ۱۰٬۰۰۰ دلار دارد و پوزیشن انتهای دوره بسته می‌شود؛ مجموع سود دو بخش لزوماً با اجرای پیوسته یکسان نیست. سود و PF از خالص معامله پس از تمام هزینه‌ها محاسبه می‌شوند؛ خروج جزئی یک معامله جدید محسوب نمی‌شود.</p><p>بیشترین PF بین واجدشرایط‌ها متعلق به <span dir="ltr">{esc(pf_leader['id'])}</span> با PF={fmt(pf_leader['full']['profit_factor'])} و سود {fmt(pf_leader['full']['net_profit'])} دلار است. انتخاب اصلی طبق بیشترین سود خالص انجام شد.</p><p>انتخاب صرفاً بر اساس سود آموزش، <span dir="ltr">{esc(train_leader['id'])}</span> را انتخاب می‌کرد؛ سود آن در دوره بعدی {fmt(train_leader['oos']['net_profit'])} دلار بود. این انتخاب جداگانه است و در صورت رد شدن شروط، در config استفاده نمی‌شود.</p><p>نتیجه موتور هزینه مبنا برای تعداد، سود، کارمزد، Funding و DD با موتور قدیمی دقیقاً تطبیق داده شد. {v['parity_cases']} تعریف در {v['parity_windows']} پنجره واقعی برای اندیکاتور، رژیم و ورود با runtime تطبیق داشت. دفتر معاملات gross−fees+funding و حداقل استاپ واقعی کنترل شد. تست‌های اجرای هم‌زمان ربات و داشبورد، خروج‌های جدید، شکست کانال بدون داده آینده، RSI پولبک، نبود خروج جزئی در هدف سخت، close-through بدون خروج با سایه، لغو GTC قبل از fill و هر دو جهت اجرا شدند؛ جزئیات TEST_RESULTS.md.</p><p>config.json و lbank_bot.py به برنده واجدشرایط به‌روزرسانی شدند؛ تعریف‌های مشترک در strategy_archetypes.py است. پوزیشن جدید تنظیمات خود را ذخیره می‌کند و با تغییر config، اندیکاتور/تریل آن عوض نمی‌شود. حالت کاغذی حفظ شده؛ PnL نمایشی ربات فقط کارمزد دارد و Funding/لغزش این گزارش در موتور بک‌تست محاسبه شده‌اند.</p></section>
<section><h2>ماتریس کامل</h2><p>شناسه‌ها: standard=(9,26,52,26)، crypto=(20,60,120,30)، H20 یعنی H2 غیرفعال و H21 فعال. CLOSE_TRAIL یعنی خروج فقط با Close در سمت نامطلوب خط و نگه‌داشتن استاپ اولیه؛ STOP_TRAIL یعنی استاپِ قیمت روی کانال مخالف؛ HARD3/4 هدف کامل بدون تریل زودهنگام؛ PARTIAL15 خروج جزئی قدیمی؛ BE2_TRAIL بدون خروج جزئی و سربه‌سر در ۲R.</p><input id="search" type="search" placeholder="جست‌وجوی خانواده، حالت یا شناسه"> <label><input id="eligible" type="checkbox"> فقط واجدشرایط‌ها</label><div class="scroll"><table id="matrix"><thead><tr><th>خانواده</th><th>شناسه</th><th>معامله</th><th>خالص کل $</th><th>خالص آموزش $</th><th>خالص دوره بعدی $</th><th>PF کل</th><th>افت کل ٪</th><th>کارمزد کل $</th><th>Funding فرضی</th><th>وضعیت</th></tr></thead><tbody>{all_rows}</tbody></table></div><p class="muted">شاخص‌های کامل هر سه دوره و پارامترها در matrix.json و predeclared_grid.json هستند.</p></section>
<section><h2>تمام {len(trades)} معامله برنده</h2><div class="scroll"><table id="trades"><thead><tr>{''.join('<th>'+h+'</th>' for h in trade_heads)}</tr></thead><tbody>{trade_rows}</tbody></table></div></section>
</main><script>function filter(){{const q=document.getElementById('search').value.toLowerCase(),only=document.getElementById('eligible').checked;for(const row of document.querySelectorAll('#matrix tbody tr'))row.hidden=!row.textContent.toLowerCase().includes(q)||(only&&row.dataset.eligible!=='1')}}document.getElementById('search').addEventListener('input',filter);document.getElementById('eligible').addEventListener('change',filter);</script></body></html>'''
(OUT/'report_fa.html').write_text(page);(BASE/'report_fa.html').write_text(page)
(OUT/'selection.json').write_text(json.dumps(dict(rule='Maximum full-period net PnL among full trades>=40, train net>0, oos net>0; PF breaks ties',winner_id=winner['id'],pf_leader_id=pf_leader['id'],train_only_leader_id=train_leader['id'],winner_missing_funding_cost=proxy_total,eligible_count=m['eligible_count']),indent=2))
print('Generated',len(page),'characters; trades',len(trades),'proxy cost',proxy_total)
