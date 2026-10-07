from pathlib import Path
import json,zipfile,hashlib
import pandas as pd
B=Path(__file__).resolve().parents[1];O=B/'output';p=O/'report_atr_comparison_fa.html';s=p.read_text()
rows=[]
for year in range(2021,2027):
 row=[str(year)+(' (بازه ناقص)' if year in (2021,2026) else '')]
 for v in ['before','after']:
  c=pd.read_csv(O/f'{v}_full_equity.csv');c['utc']=pd.to_datetime(c.timestamp_ms,unit="ms",utc=True);d=c[c.utc.dt.year==year];prior=c[c.utc.dt.year<year];start=float(prior.iloc[-1].equity) if len(prior) else 10000.;end=float(d.iloc[-1].equity);row += [f'{(end/start-1)*100:,.2f}%',f'${end-start:,.2f}']
 rows.append('<tr>'+''.join('<td>'+x+'</td>' for x in row)+'</tr>')
t='<section><h2>بازده تقویمی روی مسیر Full</h2><div class="scroll"><table><tr><th>سال</th><th>بازده قبل</th><th>تغییر سرمایه قبل</th><th>بازده ATR</th><th>تغییر سرمایه ATR</th></tr>'+''.join(rows)+'</table></div><p>بازده سالانه از Equity شامل سود و زیان باز محاسبه شده؛ ۲۰۲۱ از ۵ اکتبر و ۲۰۲۶ تا ۵ اکتبر است. این جدول با سود معاملات بسته‌شده در سال فرق دارد.</p></section>'
s=s.replace('<section><h2>سود خالص هر نماد و هر جهت</h2>',t+'<section><h2>سود خالص هر نماد و هر جهت</h2>')
s=s.replace('<section><h2>تصمیم و فایل‌ها</h2>','<section><h2>تست کد</h2><p>۱۶۸ تست Python و تست DOM داشبورد پاس شدند. تست‌های جدید جهت حاشیه در Long/Short، ثابت‌ماندن رفتار تنظیمات قدیمی، ذخیره و بارگذاری مقدار جدید، رد مقادیر غیرمعتبر، عدم عقب‌بردن استاپ و عدم اعمال حاشیه به Close-only را پوشش می‌دهند. تنها هشدار، deprecation وابستگی test client است.</p></section><section><h2>تصمیم و فایل‌ها</h2>')
s=s.replace('کاهش تعداد برخوردهای تریل، به‌تنهایی', 'میانگین سود واحد برنده در Full از $250.80 به $210.05 کاهش یافته؛ میانه زمان باز بودن واحد از 50.29 به 56.18 ساعت افزایش یافته است. کاهش کارمزد نیز علاوه بر تعداد کمتر واحدها، از مسیر متفاوت سرمایه و حجم معاملات تأثیر می‌گیرد. کاهش تعداد برخوردهای تریل، به‌تنهایی')
p.write_text(s)
readme='''# ATR trailing ablation — 2026-10-07

Frozen Git baseline: 56fc480bd191c592e9e205bb927e8eab67823b3c.
Only tested change: Donchian stop-trail buffer 0.25 ATR, long subtract / short add.
Raw closed-channel breakdown retained. No ATR entry gate or 4B additions.
Decision: REJECT buffer 0.25; production default remains 0.0.

Results: Full CAGR 32.235064 -> 24.701389; DD 34.563348 -> 38.335956.
Data: 2021-10-05 <= UTC < 2026-10-05, five symbols, 2,629,440 minutes each.
Split 2025-01-01; independent $10,000 reset per split.
Fees .0012 round trip, adverse .0002 each fill; recorded funding plus Oct1-4 proxy.
Baseline numeric parity verified across all three periods. 168 tests + DOM smoke test pass.

Code in work/ is the updated production package; copy its changed files to
lbank_project/ in the original Git checkout. Keep original infrastructure files.
The patch applies against the frozen commit. Existing open positions retain
frozen trail_atr values; changes apply to newly sized positions.

Reproduction from a full original checkout:
1. Place atr_update/ at repository root using this archive. Install numpy pandas
   numba matplotlib and lbank_project/requirements.txt in a virtual environment.
2. python atr_update/source/high_cagr/restore_local.py
   (uses verified pinned source archive; BTC minute/funding cache must be present
   in btc_backtest/cache as in the original checkout).
3. python atr_update/source/high_cagr/prepare_local.py
4. OPENBLAS_NUM_THREADS=1 python atr_update/research/run.py
5. OPENBLAS_NUM_THREADS=1 python atr_update/research/report.py
6. python atr_update/research/final_package.py

Do not compare these baseline numbers with a different ATR-entry + 4B research
baseline. CSV equity is hourly; headline maximum DD includes intraminute phases.
The ledger slippage column is explanatory and already included in fill prices.
Reports use net PF and per-unit wins/losses; base plus add is one root position.

No minute caches are bundled. They can be retrieved from the pinned original
repository using restore_local.py; restored archives and price arrays are hashed.
Backtests assume adverse-first minute OHLC path, not actual live exchange ticks.
'''
(O/'README.md').write_text(readme)
checks={}
files=[*O.glob('*.csv'),*O.glob('*.json'),*O.glob('*.npz'),*O.glob('*.png'),p,O/'atr_update.patch',O/'README.md']
for f in files:checks[f.name]=hashlib.sha256(f.read_bytes()).hexdigest()
(O/'checksums.json').write_text(json.dumps(checks,indent=2))
with zipfile.ZipFile(O/'atr_backtest_audit.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in [*files,O/'checksums.json',B/'tests.log',B/'ui_test.log',B/'run.log']:
  z.write(f,str(f.relative_to(B.parent)))
 for f in (B/'work').rglob('*'):
  if f.is_file() and '__pycache__' not in str(f) and '.pytest_cache' not in str(f):z.write(f,str(f.relative_to(B.parent)))
 for f in (B/'research').glob('*.py'):z.write(f,str(f.relative_to(B.parent)))
 for name in ['prepare_local.py','restore_local.py','run_suite.py','kernel.py']:
  f=B/'source/high_cagr'/name;z.write(f,str(f.relative_to(B.parent)))
 for name in ['data_manifest.json','repair_manifest.json','coverage.json']:
  f=B/'source/portfolio/output'/name;z.write(f,str(f.relative_to(B.parent)))
 for name in ['config.json','lbank_bot.py','strategy_archetypes.py','dashboard_server.py']:
  f=B/'source/lbank_project'/name;z.write(f,str(f.relative_to(B.parent)))
 matrix=json.loads((B/'source/high_cagr/output/matrix.json').read_text());ref=next(x for x in matrix['matrix'] if x['id']=='HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4')
 z.writestr('atr_update/source/high_cagr/output/matrix.json',json.dumps({'matrix':[ref],'winner':ref},indent=2))
 z.write(B/'source/high_cagr/output/coverage.json','atr_update/source/high_cagr/output/coverage.json')
print('PACKAGED', (O/'atr_backtest_audit.zip').stat().st_size)
