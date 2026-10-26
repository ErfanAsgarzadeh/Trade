# سرویس مرکزی: PostgreSQL، صف حساب‌ها و مسیر مقیاس

## تغییر اجرا

پنل، درخواست بررسی حساب را در یک صف پایدار ثبت می‌کند و فوراً پاسخ ۲۰۲ می‌دهد.
workerهای جدا با همان پایگاه داده و master key کار را می‌گیرند و نتیجهٔ فقط‌خواندنی
را ذخیره می‌کنند. اطلاعات صفحه از کش مالک همان session خوانده می‌شود؛ دریافت
صرافی در مسیر درخواست HTTP نیست. نتیجهٔ queued/refreshing/retrying در صفحه
هر ۱۵ تا ۲۰ ثانیه با GET تازه می‌شود؛ این poll درخواست صرافی جدید ایجاد نمی‌کند.

PostgreSQL و SQLite هر دو پشتیبانی می‌شوند. PostgreSQL pool محدود دارد: پیش‌فرض
۸ اتصال برای هر پردازش و ۶۴ درخواست منتظر؛ اندازهٔ کل باید با تعداد پردازش‌ها و
ظرفیت DB تنظیم شود. کوئری و قفل timeout دارند. اگر pool پر شود، پنل پاسخ ۵۰۳
می‌دهد. prepared statements خودکار برای سازگاری با پراکسی‌های pooling خاموش‌اند.
schema version ۱، ۲ و ۳ ثبت می‌شود؛ نسخهٔ ۳ صرافی مستقل هر حساب را اضافه می‌کند.

## قرارداد صف

- برای هر حساب، فقط یک کار queued/running وجود دارد؛ درخواست تکراری همان کار را برمی‌گرداند.
- lease پیش‌فرض ۶۰ ثانیه و token مستقل است. پاسخ worker با lease منقضی‌شده یا token قبلی رد می‌شود.
- بعد از crash، کار دوباره قابل دریافت است. خطای شبکه حداکثر سه تلاش دارد و فاصلهٔ retry برابر ۳۰/۶۰ ثانیه است.
- تغییر/حذف کلید، کار و نتیجهٔ قبلی را پاک می‌کند؛ revision و مالک هنگام انتشار دوباره بررسی می‌شوند.
- شروع کارها برای هر صرافی gate مشترک در DB دارد؛ پیش‌فرض فاصلهٔ ۰٫۲۵ ثانیه، یعنی حداکثر ۴ شروع در ثانیه برای همان صرافی در مجموع workerها.
- سقف کارهای pending پیش‌فرض ۲۰ هزار است؛ صف پر، پاسخ ۵۰۳ می‌دهد.
- در PostgreSQL قفل transaction با scope ثابت گرفته می‌شود؛ ترتیب قفل مالک برای claim/rotation/finish یکی است.

نرخ ۴/ثانیه انتخاب محافظه‌کارانهٔ پایلوت است، نه نرخ تضمین‌شدهٔ مجاز صرافی.
شروع ۱۰ هزار بررسی با این نرخ حداقل حدود ۴۲ دقیقه طول می‌کشد. افزایش تعداد
worker به‌تنهایی gate را دور نمی‌زند. برای ۱۰ هزار مشتری واقعی، باید سقف API،
تعداد حساب هم‌زمان، WebSocket و فاصلهٔ sync با LBank مشخص شود.

## راه‌اندازی PostgreSQL با Docker

از پوشه lbank_project و پس از نصب وابستگی‌ها:

```bash
python -m pip install -r requirements-portal.txt
python portal_setup.py
export PORTAL_ORIGIN=http://127.0.0.1:8080
export PORTAL_ALLOW_LOCAL_HTTP=1
docker compose -f portal-postgres-compose.yml up -d --build
docker compose -f portal-postgres-compose.yml exec portal python portal_admin.py create-user alice
docker compose -f portal-postgres-compose.yml exec portal python portal_admin.py create-user bob
docker compose -f portal-postgres-compose.yml exec portal python portal_admin.py queue-status
```

در PowerShell دو متغیر بالا با `$env:PORTAL_ORIGIN=...` و
`$env:PORTAL_ALLOW_LOCAL_HTTP="1"` تنظیم می‌شوند. رمز کاربر تعاملی گرفته می‌شود.
portal_setup راز DB و URL را می‌سازد، بدون چاپ آن‌ها؛ master key قبلی را حفظ
می‌کند و هیچ راز DB موجود را بازنویسی نمی‌کند. برای نصب جدید master key ساخته
می‌شود. DB پورت عمومی ندارد و کلید رمزگشایی حساب‌ها را mount نمی‌کند.

پنل روی localhost:8080 منتشر می‌شود. برای اینترنت، PORTAL_ORIGIN باید HTTPS
دقیق سایت باشد، HTTP محلی خاموش بماند، TLS/محدودیت درخواست روی reverse proxy
قرار بگیرد و PORTAL_TRUSTED_PROXY_IPS فقط IP/CIDR پراکسی مورداعتماد را داشته باشد.
DB نقش برنامهٔ اختصاصی دارد؛ این Compose مدل HA، KMS یا پشتیبان خودکار نیست.
Docker این فایل در محیط حاضر اجرا نشده است.

برای افزایش workerهای خواندن حساب:

```bash
docker compose -f portal-postgres-compose.yml up -d --scale account-worker=4
```

تعداد poolها را در بودجهٔ اتصال DB حساب کنید. این workerها executor سه استراتژی نیستند.
Compose به runtime مشتریان mount ندارد؛ نمایش آن‌ها نیاز به اتصال مدیریتی
read-only دارد. اجرای سه ربات برای هر مشتری روی یک موتور مشترک، مرحلهٔ بعدی است.

## انتقال پایلوت موجود

اول پنل و workerهای SQLite را متوقف و از DB همراه WAL و master key پشتیبان
سازگار بگیرید. از portal_setup با همان issuer-keys استفاده کنید تا کلید عوض نشود.
هدف PostgreSQL باید **کاملاً خالی** باشد؛ انتقال به DB دارای مشتری رد می‌شود.
برای نمونه، فایل DB قدیمی را در کانتینر موقت به مسیر source mount کنید:

```bash
docker compose -f portal-postgres-compose.yml stop portal account-worker
docker compose -f portal-postgres-compose.yml run --rm -v "${PWD}/runtime/portal:/source" portal python portal_admin.py migrate-database --source /source/portal.db
docker compose -f portal-postgres-compose.yml up -d portal account-worker
```

کاربران، password hash، sessionها، کلیدهای رمزگذاری‌شده، کش و audit با شناسه‌های
قبلی منتقل می‌شوند؛ ترتیب audit در PostgreSQL اصلاح می‌شود. کلید قبل از قبول
داده decrypt/owner-check می‌شود. شمار رکوردها بررسی و انتقال در transaction
انجام می‌شود. دادهٔ مبدا حذف نمی‌شود؛ کار running به queued برمی‌گردد. مسیرهای
runtime قبلی ممکن است در کانتینر جدید وجود نداشته باشند؛ آن‌ها را با mount و
bind-runtime درست کنید. نسخهٔ قدیمی را هم‌زمان به DB مبدا وصل و فعال نگذارید.

## آزمون و ظرفیت

آزمون قبلیِ تک‌صرافی روی ۱۰ هزار حساب ثبت‌شده با SQLite و ASGI داخل همان پردازش
انجام شده است. هیچ درخواست صرافی یا سفارش واقعی نداشت. چهار worker، ۱۰۰۰ کار
ساختگی از صف ۱۰ هزار کار را پردازش کردند؛ بقیه هنوز queued بودند. برای سنجش پنل
۲۰۰۰ درخواست با هم‌زمانی ۴۰ گرفته شد. نمونه‌های دارای موجودی نیز با صاحب حساب
تطبیق داده شدند. خروجی آن اجرا در reports/portal_capacity_10000_v2.json است.
نتایج جدید چندصرافی و محدودیت نوشتن هم‌زمان SQLite در [MULTI_EXCHANGE_FA.md](MULTI_EXCHANGE_FA.md)
آمده است؛ نسخهٔ فعلی benchmark برای SQLite پیش‌فرض یک worker دارد.

| شاخص اجرای قبلی تک‌صرافی | نتیجه |
|---|---|
| حساب ثبت‌شدهٔ مصنوعی | ۱۰٬۰۰۰ |
| درخواست پنل / هم‌زمانی | ۲۰۰۰ / ۴۰ |
| پاسخ موفق | ۲۰۰۰ از ۲۰۰۰ |
| صدک ۹۵ / صدک ۹۹ پاسخ | ۱۲۰٫۵۲ / ۱۹۳٫۴۱ میلی‌ثانیه |
| نرخ پاسخ پنل | ۵۳۶٫۴۸ درخواست در ثانیه |
| کار ساختگی پردازش‌شده / worker | ۱۰۰۰ / ۴ |
| نمونهٔ دارای موجودی که مالک آن بررسی شد | ۲۰۱ |
| مغایرت مالک در این نمونه‌ها | صفر |
| تماس صرافی / سفارش واقعی | صفر / صفر |

مجموعهٔ کامل پروژه در ۲۰۲۶-۱۰-۱۳: **۳۶۱ موفق، ۲۰ skipped**؛ ۱۰ مورد دادهٔ
پژوهشی نبود و ۱۰ مورد PostgreSQL به URL تست نیاز داشت. اجرای جداگانهٔ صف با
SQLite و PostgreSQL/WASM: **۲۲ موفق**. تست‌های UI، JavaScript syntax، diff-check
و ساختار YAML نیز موفق بودند. این آمار اجرای CI یا Docker native نیست.

این تست معیار محلیِ پاسخ پنل و درستی مالکیت است؛ تست ۱۰ هزار session هم‌زمان،
شبکه/پراکسی واقعی، executor Futures، محدودیت واقعی صرافی یا ظرفیت تولید نیست.

```bash
python -m pip install -r requirements-dev.txt -r requirements-portal.txt
python -m pytest tests -q
node tests/test_portal_ui.cjs
python portal_capacity.py --users 10000 --requests 2000 --concurrency 40 --drain 1000 --output reports/new-capacity-run.json
```

برای تست native PostgreSQL، یک DB **کاملاً موقت و دورریختنی** آماده کنید:

```bash
export PORTAL_TEST_DATABASE_URL='postgresql://portal_test:disposable-password@127.0.0.1:5432/portal_test'
export PORTAL_TEST_ALLOW_RESET=1
python -m pytest tests/test_portal_queue.py -q
```

این تست با TRUNCATE دادهٔ هدف تست را پاک می‌کند؛ URL تولید را به آن ندهید.
workflow `.github/workflows/portal-tests.yml` برای PostgreSQL 17 آماده شده ولی
هنوز در GitHub اجرا نشده است. در این محیط PostgreSQL native به‌علت نبود امکان
اجرای آن با کاربر غیر-root بالا نیامد؛ SQL و driver با PostgreSQL/WASM
(PGlite) آزموده شدند. PGlite تراکنش‌ها را multiplex می‌کند و معادل آزمون قفل‌ها
یا ظرفیت سرور native چندپردازشی نیست.

## مانع اتصال Futures در LBank

مسیرهای خواندن Futures برای ۷ صرافی دیگر پیاده شده‌اند؛ پوشش و محدودیت آن‌ها
در [MULTI_EXCHANGE_FA.md](MULTI_EXCHANGE_FA.md) آمده است.

صف و پنل هیچ سفارش، برداشت یا انتقالی ندارند. CCXT نصب‌شده برای عملیات حساب
خصوصی از Spot استفاده می‌کند. صفحهٔ رسمی contract و نسخهٔ چینی آن بررسی شدند؛
برای موجودی/پوزیشن/سفارش و client order ID، قرارداد کامل و قابل اعتبارسنجی
به‌دست نیامد. کلید Futures ثبت می‌شود ولی worker وضعیت futures_not_validated
می‌دهد. ساخت مسیر حدسی یا تبدیل خودکار Futures به Spot انجام نشده است.
SDK رسمی Python نیز در commit `538d465fe29c7266d9076158bb2742d7b1178f15`
بررسی شد؛ ماژول‌های Spot را داشت و آداپتور Futures موردنیاز در آن نبود.

گام بعد، دریافت مستند کامل endpointهای خصوصی از LBank و اعتبارسنجی فقط‌خواندنی
با حساب کنترل‌شده است؛ بعد از آن executor با reconcile، توقف اضطراری، حفاظت
stop و عدم تکرار سفارش اضافه می‌شود. تأیید این بخش شرط شروع معاملهٔ واقعی است.

منابع رسمی:

- https://www.lbank.com/docs/contract.html
- https://www.lbank.com/zh-CN/docs/contract.html
- https://www.psycopg.org/psycopg3/docs/advanced/pool.html
- https://www.postgresql.org/docs/current/explicit-locking.html
- https://pglite.dev/docs/pglite-socket
- https://github.com/LBank-exchange/lbank-connector-python
