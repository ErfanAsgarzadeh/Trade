# راه‌اندازی عمومی سایت فروش، پنل مشتری و کارتابل مدیر

سایت (`/`)، پنل مشتری (`/dashboard/`) و کارتابل مدیر (`/admin/`) از `portal-compose.yml` اجرا می‌شوند.
`portal-public-compose.yml` جلوی آن‌ها Caddy می‌گذارد که گواهی HTTPS را خودکار می‌گیرد و تمدید می‌کند.

## پیش‌نیاز
- یک دامنه که رکورد A آن (و در صورت تمایل `www`) به IP سرور اشاره کند.
- پورت‌های ۸۰ و ۴۴۳ سرور باز باشند.
- حدود ۲ گیگ RAM برای ساخت image (فرانت Next.js داخل Docker ساخته می‌شود).

## یک‌بار: کلید رمزگذاری و دیتابیس پنل
```bash
cd /opt/Trade/lbank_project
mkdir -p issuer-keys runtime/portal && chmod 700 issuer-keys
docker compose -f portal-compose.yml build portal
docker run --rm -v "$PWD/issuer-keys:/app/issuer-keys" -v "$PWD/runtime/portal:/app/runtime/portal" -e PORTAL_DB=/app/runtime/portal/portal.db -e PORTAL_KEY_FILE=/app/issuer-keys/portal.key trade-portal-portal python portal_admin.py init
```
از `issuer-keys/portal.key` جداگانه و امن نسخهٔ پشتیبان بگیرید؛ بدون آن کلیدهای API ذخیره‌شدهٔ مشتریان قابل خواندن نیست.

## بالا آوردن سایت
```bash
PORTAL_DOMAIN=example.com docker compose -f portal-compose.yml -f portal-public-compose.yml up -d --build
```

## حساب مالک و نقش مدیر
در سایت ثبت‌نام کنید، بعد روی سرور:
```bash
docker compose -f portal-compose.yml -f portal-public-compose.yml exec portal python portal_admin.py set-admin USERNAME
```

## نمایش ربات‌های مالک در پنل خودش
runtime سرور فقط‌خواندنی در `/app/owner-runtime` مانت می‌شود. یک بار:
```bash
echo '{"customer_id": "USERNAME"}' > runtime/customer_identity.json
echo '{"main": "paper-live-lbank/shahin.db", "c3": "paper-live-lbank/mojsavar.db", "pa": "paper-live-lbank/ghoghnous.db"}' > runtime/portal_runtime.json
docker compose -f portal-compose.yml -f portal-public-compose.yml exec portal python portal_admin.py bind-runtime USERNAME /app/owner-runtime
```
`portal_runtime.json` به پنل می‌گوید دیتابیس‌های paper روی این سرور کجا هستند؛ مسیر بیرون از runtime نادیده گرفته می‌شود.

فروش هر دو محصول تا ثبت قیمت و بازکردن صریح در کارتابل بسته می‌ماند.
