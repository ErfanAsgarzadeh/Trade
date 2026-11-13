# راه‌اندازی سایت فروش، پنل مشتری و کارتابل مدیر (PostgreSQL)

سایت (`/`)، پنل مشتری (`/dashboard/`) و کارتابل مدیر (`/admin/`) با `portal-postgres-compose.yml` اجرا می‌شوند:
پایگاه دادهٔ PostgreSQL 17 (بدون پورت عمومی)، وب و worker خواندن حساب‌ها. این یک پروژهٔ Docker جداست و به ربات‌ها
دست نمی‌زند. `portal-owner-compose.yml` runtime ربات‌های مالک را فقط‌خواندنی به وب می‌دهد.
`portal-public-compose.yml` (وقتی دامنه داشتید) Caddy را جلوی سایت می‌گذارد و HTTPS را خودکار می‌گیرد.

## یک‌بار: رازها
```bash
cd /opt/Trade/lbank_project
mkdir -p issuer-keys && chmod 700 issuer-keys
docker compose -f portal-postgres-compose.yml build portal
docker run --rm -v "$PWD/issuer-keys:/app/issuer-keys" trade-portal-central-portal python portal_setup.py
chmod 644 issuer-keys/postgres_password
```
PostgreSQL فایل رمز را با کاربر خودش (نه root) می‌خواند، پس آن فایل باید قابل‌خواندن باشد؛ پوشهٔ `issuer-keys` با ۷۰۰ برای بقیهٔ کاربران سرور بسته می‌ماند.
`portal_setup.py` رمز پایگاه داده، آدرس اتصال و کلید رمزگذاری (`portal.key`) را در `issuer-keys/` می‌سازد و چاپ نمی‌کند.
از کل پوشهٔ `issuer-keys/` و از دادهٔ پایگاه داده جداگانه پشتیبان بگیرید.

## بدون دامنه (فقط برای مالک، از طریق تونل SSH)
```bash
PORTAL_ALLOW_LOCAL_HTTP=1 docker compose -f portal-postgres-compose.yml -f portal-owner-compose.yml up -d
```
روی کامپیوتر خودتان: `ssh -L 8080:127.0.0.1:8080 root@IP_SERVER` و بعد `http://127.0.0.1:8080`.

## با دامنه (عمومی، HTTPS)
```bash
PORTAL_DOMAIN=example.com docker compose -f portal-postgres-compose.yml -f portal-owner-compose.yml -f portal-public-compose.yml up -d
```

## حساب مالک، نقش مدیر و ربات‌های مالک
در سایت ثبت‌نام کنید، بعد:
```bash
C="docker compose -f portal-postgres-compose.yml -f portal-owner-compose.yml"
$C exec portal python portal_admin.py set-admin USERNAME
echo '{"customer_id": "USERNAME"}' > runtime/customer_identity.json
echo '{"main": "paper-live-lbank/shahin.db", "c3": "paper-live-lbank/mojsavar.db", "pa": "paper-live-lbank/ghoghnous.db"}' > runtime/portal_runtime.json
$C exec portal python portal_admin.py bind-runtime USERNAME /app/owner-runtime
```

## پشتیبان پایگاه داده
```bash
docker compose -f portal-postgres-compose.yml exec -T db pg_dump -U trade_portal trade_portal | gzip > /root/portal-$(date +%Y%m%d).sql.gz
```

فروش هر دو محصول تا ثبت قیمت و بازکردن صریح در کارتابل بسته می‌ماند.

## سئو و ثبت سایت در موتورهای جست‌وجو

سایت این موارد را خودش می‌سازد و همه از `PORTAL_ORIGIN` خوانده می‌شوند، پس بعد از تنظیم دامنه کار دیگری لازم نیست:

- `/robots.txt` و `/sitemap.xml` (شامل همهٔ مقاله‌های بلاگ)
- خبرخوان بلاگ در `/blog/rss.xml`
- تگ canonical، تصویر اشتراک‌گذاری (`og-image.png`) و دادهٔ ساختاریافته (Organization، WebSite، SoftwareApplication، FAQPage)
- پنل کاربر، پنل مدیریت و API با `X-Robots-Tag: noindex` از نتایج جست‌وجو بیرون می‌مانند.

بعد از بالا آمدن سایت روی دامنه:

1. دامنه را در [Google Search Console](https://search.google.com/search-console) ثبت و با رکورد DNS تأیید کنید.
2. آدرس `https://دامنه/sitemap.xml` را در بخش Sitemaps بفرستید.
3. همین کار را در [Bing Webmaster Tools](https://www.bing.com/webmasters) انجام دهید.

مقاله‌های بلاگ از «پنل مدیریت ← بلاگ» نوشته و منتشر می‌شوند و نیازی به build دوباره ندارند. مقاله‌ها در دیتابیس ذخیره می‌شوند؛ پشتیبان دیتابیس، مقاله‌ها را هم نگه می‌دارد.

رتبهٔ اول را هیچ تنظیم فنی‌ای تضمین نمی‌کند. بعد از این مرحله، رتبه به محتوای تازه (مقاله و راهنما)، لینک از سایت‌های معتبر و سابقهٔ دامنه بستگی دارد.
