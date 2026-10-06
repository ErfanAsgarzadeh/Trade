# پرتفوی Donchian + Kumo و افزایش ریسک

بازه ثابت همان مرجع: 2021-10-05 تا 2026-10-05 UTC، انتها غیرشامل. چهار SINGLE واجدشرایط قبلی با بیشترین سود کل، بدون تغییر شبکه بر اساس نتایج جدید، انتخاب شده‌اند؛ یک کانال 10 کندلی و سه کانال 20 کندلی. 40 ترکیب و 120 اجرای مستقل Full/Train/OOS؛ سرمایه مشترک $10,000.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r archetypes/requirements.txt
PYTHONPATH=lbank_project python portfolio/download_data.py
PYTHONPATH=lbank_project python portfolio/prepare_data.py
PYTHONPATH=lbank_project python portfolio/run_suite.py --verify-reference
PYTHONPATH=lbank_project python portfolio/run_suite.py
PYTHONPATH=lbank_project python portfolio/verify_results.py
PYTHONPATH=lbank_project python portfolio/make_report.py
PYTHONPATH=lbank_project python -m pytest portfolio/test_portfolio.py lbank_project/tests btc_backtest/test_backtest.py -q
node lbank_project/tests/test_ui.cjs
```

دانلود با SHA-256 رسمی و ثبت اتمیک manifest پس از هر آرشیو است؛ cache موجود بازاستفاده می‌شود. آماده‌سازی هر نماد manifest جداگانه دارد. اجرای هر ترکیب بعد از هر دوره JSON و NPZ ذخیره می‌کند و اجرای دوباره دوره کامل‌شده را رد می‌کند. برای توقف و ادامه، manifest، cache و prepared را حفظ کنید؛ فایل‌های `.tmp` و `.part` خروجی نهایی نیستند.

برنده فقط در صورت حداقل 40 معامله کل، سود مثبت Train و OOS و افت حداکثر 25% در هر سه دوره انتخاب می‌شود. انتخاب بیشترین سود کل و سپس PF است. مرحله بعدی در انتخاب دخالت دارد؛ آزمون مستقل دست‌نخورده نیست.

ریسک BTC 1/1.5/2% با سقف نُوشنال150% و پرتفوی 0.75/1/1.5% با 3/4 پوزیشن و سقف نُوشنال125% هر پوزیشن است. مارجین اولیه ورود مجموعاً از سرمایه MTM بیشتر نمی‌شود. سیگنال‌های هم‌زمان با فاصله درصدی شکست از مرز سخت‌تر Kumo/Donchian مرتب می‌شوند؛ ترتیب نمادها تساوی را حل می‌کند.

کارمزد0.12% رفت‌وبرگشت، لغزش2bps هر Fill، Funding مشاهده‌شده تا سپتامبر و Funding فرضی نامطلوب0.01% هر8h در Oct1-4، حداقل استاپ1.2% با REJECT و توقف ورود پس از زیان تحقق‌یافته خروج2%/24h حفظ شده‌اند. گام سفارش انتزاعی0.0001 واحد پایه و حداقل$5 همان مدل قبلی است؛ precision تاریخی صرافی و Mark Price/maintenance/liquidation بازسازی نشده‌اند. سقف DD نتیجه همین مدل است. ربات paper همچنان زنده معامله نمی‌کند و Funding و لغزش بک‌تست را در paper بازسازی نمی‌کند.

داده خامBTC در btc_backtest/cache، سایر نمادها در portfolio/cache و ویژگی‌های قابل بازتولید محلی در portfolio/prepared هستند. اطلاعات checksum در output/data_manifest.json است. دفتر هر دوره شامل شماره نماد، ورود/خروج، جهت، قیمت، مقدار، استاپ، Gross/Fees/Funding/Net و ریسک ورود است.
