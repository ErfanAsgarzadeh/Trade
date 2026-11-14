#!/usr/bin/env python3
"""Assemble an allowlisted portal preview with a prebuilt Next.js export; never deploy."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
MODULES=('portal_server.py','portal_store.py','portal_database.py','portal_jobs.py','portal_worker.py',
         'portal_exchanges.py','portal_thetruetrade.py','portal_execution.py','exchanges.py',
         'portal_migrate.py','portal_runtime.py','portal_lbank.py','portal_admin.py','portal_billing.py',
         'portal_frontend.py','portal_admin_store.py','portal_audit.py','portal_blog.py','portal_payments.py','portal_telegram.py','portal_referrals.py','product_pricing.py',
         'signal_feed.py','capital_plans.py','customer_manager.py','license_access.py',
         'requirements.txt','requirements-portal.txt')
DOCKERFILE='''FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-portal.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements-portal.txt
COPY *.py ./
COPY frontend/out ./frontend/out
COPY frontend/public ./frontend/public
COPY frontend/content/blog ./frontend/content/blog
CMD ["python", "-u", "portal_server.py"]
'''
COMPOSE='''name: trade-portal-preview
x-runtime: &runtime
  image: trade-portal-preview:${TRADE_RELEASE_TAG:?Set release tag}
  build: .
  restart: "no"
  init: true
  read_only: true
  tmpfs: [/tmp]
  cap_drop: [ALL]
  security_opt: [no-new-privileges:true]
  mem_limit: 256m
  cpus: 0.50
  pids_limit: 100
  environment: &environment
    PORTAL_DB: /app/runtime/portal.db
    PORTAL_KEY_FILE: /run/secrets/portal_key
  volumes: [./preview-runtime:/app/runtime]
  secrets: [portal_key]
  logging:
    options: {max-size: 5m, max-file: "2"}
services:
  portal:
    <<: *runtime
    environment:
      <<: *environment
      PORTAL_HOST: 0.0.0.0
      PORTAL_PORT: "8080"
      PORTAL_ORIGIN: http://127.0.0.1:18080
      PORTAL_ALLOW_LOCAL_HTTP: "1"
    ports: ["127.0.0.1:18080:8080"]
    healthcheck:
      test: [CMD, python, -c, "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/healthz',headers={'Host':'127.0.0.1:18080'}),timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
  account-worker:
    <<: *runtime
    profiles: [account-read]
    command: [python, -u, portal_worker.py]
    environment:
      <<: *environment
      PORTAL_EXCHANGE_READ_INTERVAL: "2"
secrets:
  portal_key:
    file: ./preview-secrets/portal.key
'''
INIT='''#!/usr/bin/env python3
import base64, os
from pathlib import Path
root=Path(__file__).resolve().parent
secret=root/'preview-secrets';secret.mkdir(mode=0o700,exist_ok=True)
key=secret/'portal.key'
if not key.exists():
    with key.open('xb') as stream:
        os.chmod(key,0o600);stream.write(base64.urlsafe_b64encode(os.urandom(32))+b'\\n')
    print('New preview key created; no key printed.')
else:print('Existing preview key preserved.')
(root/'preview-runtime').mkdir(mode=0o700,exist_ok=True)
print('Only preview directories initialized; no service started.')
'''
README='''# نسخهٔ آزمایشی مستقل Trade

این بسته فقط پنل، سیگنال و خواندن حساب را آماده می‌کند؛ سرویس اجرای سفارش ندارد.
فرانت از قبل ساخته شده است و برای نصب به Node روی سرور نیاز ندارد.
هنوز image پایتون باید روی ماشین دارای منابع کافی ساخته شود؛ build روی سرور فعلی ۱ گیگ توصیه نمی‌شود.

۱. بسته را در پوشهٔ جدید باز کنید؛ روی نسخهٔ فعال یا runtime موجود استخراج نکنید.
۲. `python3 initialize_preview.py` فقط کلید تصادفی تازه و دیتابیس‌دایرکتوری preview را آماده می‌کند.
۳. `docker compose --env-file release.env build` را روی ماشین ساخت دارای منابع کافی اجرا کنید.
   برای انتقال image: `docker save trade-portal-preview:TAG | gzip > preview-image.tar.gz`؛ سپس روی مقصد `gzip -dc preview-image.tar.gz | docker load`.
۴. بعد از تأمین منابع: `docker compose --env-file release.env up -d --no-build portal`.
۵. از SSH tunnel استفاده کنید: `ssh -L 18080:127.0.0.1:18080 USER@SERVER`؛ مرورگر `http://127.0.0.1:18080`.
۶. ثبت‌نام را در همین preview انجام دهید. برای مدیرکردن کاربر آزمایشی:
   `docker compose --env-file release.env exec portal python portal_admin.py set-admin USERNAME`.
۷. worker خواندن حساب اختیاری است:
   `docker compose --env-file release.env --profile account-read up -d --no-build account-worker`.
۸. توقف فقط این preview: `docker compose --env-file release.env down`؛ از `down -v`، prune یا توقف کانتینرهای قبلی استفاده نکنید.

فروش‌ها روی دیتابیس تازه بسته‌اند. کلید یا دیتابیس تولید را به preview وصل نکنید.
این بسته کاربر را به‌طور خودکار لایسنس‌دار نمی‌کند و ربات معامله‌گر را شروع نمی‌کند.
پورت ۱۸۰۸۰ فقط loopback است؛ HTTPS دامنه و انتشار عمومی در این بسته فعال نشده‌اند.
کلیدهای مشتری فقط در فرم حساب و به‌شکل رمز‌شده در دیتابیس ذخیره می‌شوند؛ کلیدها را در چت یا release.env ننویسید.
برای تست TheTrueTrade در preview فقط مجوز خواندن موجودی و پوزیشن کافی است؛ مجوز برداشت لازم نیست.
readiness و تأیید خواندن حساب هیچ مجوز معامله‌ای صادر نمی‌کنند.
حد حافظهٔ Compose بودجهٔ preview است، نه تضمین ظرفیت؛ تست بار و مانیتورینگ قبل از استفادهٔ واقعی لازم‌اند.
'''


def build(destination,root=ROOT):
    root=Path(root)
    for page in ('index.html','dashboard.html','admin.html','register.html'):
        if not (root/'frontend/out'/page).is_file():raise ValueError('Build Next.js before preparing release')
    files={name:(root/name).read_bytes() for name in MODULES}
    for folder in ('frontend/out','frontend/public','frontend/content/blog'):
        if (root/folder).is_symlink():raise ValueError('Symlink asset directory is not allowed')
        for file in sorted((root/folder).rglob('*')):
            if file.is_symlink():raise ValueError('Symlinks are not allowed in frontend assets')
            if file.is_file():
                relative=file.relative_to(root/folder)
                if any(part.startswith('.') for part in relative.parts) or file.suffix not in ('.html','.txt','.js','.css','.woff','.woff2','.ttf','.json','.csv','.md','.png','.svg','.webmanifest'):
                    raise ValueError('Unexpected file in frontend assets')
                files[file.relative_to(root).as_posix()]=file.read_bytes()
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.SubprocessError):commit='unknown'
    # Hash the exact contents, including any uncommitted implementation, rather than imply a clean source.
    hashes={name:hashlib.sha256(content).hexdigest() for name,content in sorted(files.items())}
    hashes.update({name:hashlib.sha256(content.encode()).hexdigest() for name,content in {
        'Dockerfile':DOCKERFILE,'compose.yml':COMPOSE,'initialize_preview.py':INIT,'README_FA.md':README,
        '.dockerignore':'preview-secrets\npreview-runtime\n*.db*\n*.tar*\n.env\n'}.items()})
    tag=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:16]
    files.update({'Dockerfile':DOCKERFILE.encode(),'compose.yml':COMPOSE.encode(),
                  '.dockerignore':b'preview-secrets\npreview-runtime\n*.db*\n*.tar*\n.env\n',
                  'initialize_preview.py':INIT.encode(),'README_FA.md':README.replace(':TAG', ':'+tag).encode(),
                  'release.env':('TRADE_RELEASE_TAG='+tag+'\n').encode()})
    manifest=dict(schema=1,source_commit=commit,release_tag=tag,frontend_prebuilt=True,
                  contains_credentials=False,live_execution_enabled=False,
                  sha256={name:hashlib.sha256(content).hexdigest() for name,content in sorted(files.items())})
    files['release-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents accidentally replacing a previously reviewed release.
    with destination.open('xb') as stream:
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            for name,content in sorted(files.items()):
                info=tarfile.TarInfo('trade-portal-preview/'+name);info.size=len(content);info.mode=0o644
                archive.addfile(info,io.BytesIO(content))
    return {'release_tag':tag,'files':len(files),'archive_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.output),indent=2))


if __name__=='__main__':main()
