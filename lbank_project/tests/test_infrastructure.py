"""Deployment files: least-privilege secrets, non-root images, lean dependencies, backups, logging and CI. Static checks only;
nothing here builds an image or starts Caddy."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
LOCAL = {p.stem for p in ROOT.glob('*.py')}
PACKAGE = {'PIL': 'pillow', 'ccxt': 'ccxt', 'cryptography': 'cryptography', 'fastapi': 'fastapi', 'starlette': 'fastapi', 'uvicorn': 'uvicorn',
           'pydantic': 'pydantic', 'psycopg': 'psycopg', 'psycopg_pool': 'psycopg-pool', 'pandas': 'pandas', 'numpy': 'numpy'}


def compose(*names):
    merged = {}
    for name in names:
        data = yaml.safe_load((ROOT / name).read_text())
        for key, value in data.items():
            if isinstance(value, dict):merged.setdefault(key, {}).update(value)
            else:merged[key] = value
    return merged


def requirements(name):
    out = {}
    for line in (ROOT / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith(('#', '-r')):
            package, version = re.split(r'==', line)
            out[re.sub(r'\[.*\]', '', package)] = version
    return out


def closure(*entries):
    """(local modules, third-party packages) reachable from the entry modules, including imports inside functions."""
    seen, third, stack = set(), set(), list(entries)
    while stack:
        module = stack.pop()
        if module in seen:continue
        seen.add(module)
        for node in ast.walk(ast.parse((ROOT / f'{module}.py').read_text())):
            names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            for name in names:
                if name in LOCAL:stack.append(name)
                elif name not in sys.stdlib_module_names:third.add(name)
    return seen, third


def copied(dockerfile):
    files = set()
    for line in (ROOT / dockerfile).read_text().splitlines():
        if line.startswith('COPY ') and '--from' not in line:
            files |= {Path(w).stem for w in line.split()[1:-1] if w.endswith('.py')}
    return files


def installed(dockerfile):
    return requirements(re.search(r'-r (requirements[\w-]*\.txt)', (ROOT / dockerfile).read_text()).group(1))


IMAGES = {'Dockerfile.portal': ('portal_server', 'portal_worker', 'portal_admin', 'portal_migrate', 'portal_setup'),
          'Dockerfile.worker': ('portal_payments', 'portal_telegram'),
          'Dockerfile.issuer': ('portal_issuer',)}


@pytest.mark.parametrize('dockerfile,entries', IMAGES.items())
def test_each_image_copies_every_module_it_imports_and_installs_every_package_it_needs_and_no_more(dockerfile, entries):
    modules, third = closure(*entries)
    assert modules <= copied(dockerfile), sorted(modules - copied(dockerfile))
    needed = {PACKAGE[name] for name in third}
    assert needed == set(installed(dockerfile)), (sorted(needed), sorted(installed(dockerfile)))   # Nothing missing and nothing extra.
    assert 'pandas' not in installed(dockerfile) and 'numpy' not in installed(dockerfile)


def test_no_portal_module_imports_pandas_or_numpy_and_only_the_web_and_account_worker_need_ccxt():
    for module in LOCAL:
        if module.startswith('portal_') or module in ('product_pricing', 'signal_feed', 'exchanges', 'license_access', 'capital_plans'):
            assert not {'pandas', 'numpy'} & closure(module)[1], module
    assert 'ccxt' in closure('portal_server')[1] and 'ccxt' in closure('portal_worker')[1]
    for entry in ('portal_payments', 'portal_telegram', 'portal_issuer', 'portal_admin', 'portal_migrate', 'portal_setup'):
        assert 'ccxt' not in closure(entry)[1], entry
    assert set(installed('Dockerfile.worker')) == {'cryptography', 'psycopg', 'psycopg-pool'} == set(installed('Dockerfile.issuer'))
    assert 'ccxt' in installed('Dockerfile.portal')


def test_requirement_files_agree_with_the_shared_pins():
    shared = {**requirements('requirements.txt'), **requirements('requirements-portal.txt')}
    for name in ('requirements-web.txt', 'requirements-worker.txt'):
        for package, version in requirements(name).items():
            assert shared[package] == version, (name, package)


@pytest.mark.parametrize('dockerfile', ['Dockerfile.portal', 'Dockerfile.worker', 'Dockerfile.issuer'])
def test_images_run_as_the_fixed_non_root_user_and_use_pinned_bases(dockerfile):
    text = (ROOT / dockerfile).read_text()
    assert '--gid 10001' in text and '--uid 10001' in text and text.rstrip().splitlines()[-2] == 'USER 10001:10001'
    assert re.findall(r'^FROM (\S+)', text, re.M)[-1] == 'python:3.11-slim-bookworm'
    assert 'COPY --chown' not in text and 'chmod' not in text      # Code stays root-owned and read-only for the process.
    assert text.index('USER 10001') > text.rindex('COPY ') and text.index('USER 10001') > text.index('pip install')
    assert 'node:26-bookworm-slim' in (ROOT / 'Dockerfile.portal').read_text()
    assert re.search(r'^FROM python:3\.11-slim-bookworm AS customer$', (ROOT / 'Dockerfile').read_text(), re.M)


def test_workers_get_only_the_settings_key_and_the_database_secret():
    services = compose('portal-postgres-compose.yml')['services']
    for name in ('payment-worker', 'telegram-worker'):
        service = services[name]
        assert sorted(service['secrets']) == ['portal_database_url', 'settings_key'], name
        assert 'PORTAL_KEY_FILE' not in service['environment'] and service['environment']['PORTAL_SETTINGS_KEY_FILE'] == '/run/secrets/settings_key'
        assert service['build']['dockerfile'] == 'Dockerfile.worker' and service['read_only'] and service['cap_drop'] == ['ALL']
    assert 'portal_key' not in services['issuer']['secrets'] and 'license_private' in services['issuer']['secrets']
    assert sorted(services['portal']['secrets']) == ['portal_database_url', 'portal_key', 'settings_key']
    assert sorted(services['account-worker']['secrets']) == ['portal_database_url', 'portal_key']
    assert services['payment-worker']['environment']['HTTPS_PROXY'] == '${PAYMENT_HTTPS_PROXY:-}'
    assert services['telegram-worker']['environment']['HTTPS_PROXY'] == '${TELEGRAM_HTTPS_PROXY:-}'
    assert {'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_FROM'} <= set(services['telegram-worker']['environment'])
    assert not any('ports' in s for n, s in services.items() if n != 'portal')
    mail = compose('portal-postgres-compose.yml', 'portal-mail-compose.yml')
    assert mail['services']['telegram-worker']['environment']['SMTP_PASSWORD_FILE'] == '/run/secrets/smtp_password' and 'smtp_password' in mail['secrets']


def test_setup_secrets_named_in_compose_are_the_ones_setup_creates():
    declared = compose('portal-postgres-compose.yml')['secrets']
    assert declared['settings_key']['file'] == './issuer-keys/settings.key' and declared['portal_key']['file'] == './issuer-keys/portal.key'


def test_backup_service_dumps_daily_keeps_fourteen_and_publishes_nothing(tmp_path):
    backup = compose('portal-postgres-compose.yml')['services']['backup']
    assert backup['image'] == 'postgres:17' and 'ports' not in backup and backup['user'] == '10001:10001'
    assert backup['volumes'] == ['./runtime/backups:/backups'] and backup['secrets'] == ['postgres_password']
    assert backup['logging']['options'] == {'max-size': '10m', 'max-file': '3'} and backup['read_only'] and backup['cap_drop'] == ['ALL']
    assert backup['environment']['BACKUP_KEEP'] == '14' and backup['environment']['BACKUP_INTERVAL_SECONDS'] == '86400'
    script = backup['command'][2].replace('$$', '$')                       # Compose turns $$ into $.
    assert backup['command'][:2] == ['bash', '-c'] and 'pipefail' in script and 'pg_dump -h db -U trade_portal' in script and 'gzip' in script
    assert 'PGPASSWORD="$(cat /run/secrets/postgres_password)"' in script and 'tail -n +$((BACKUP_KEEP + 1))' in script
    assert subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True).returncode == 0


def run_loop_once(tmp_path, dump_command, keep=3):
    """Execute the backup script body with a fake pg_dump so the retention and failure handling are exercised for real."""
    backup = compose('portal-postgres-compose.yml')['services']['backup']
    script = backup['command'][2].replace('$$', '$')
    script = script.replace('/run/secrets/postgres_password', str(tmp_path / 'pw')).replace('/backups', str(tmp_path / 'out'))
    script = script.replace('sleep "$BACKUP_INTERVAL_SECONDS"', 'exit 0')
    (tmp_path / 'pw').write_text('secret\n');(tmp_path / 'out').mkdir(exist_ok=True)
    (tmp_path / 'bin').mkdir(exist_ok=True)
    (tmp_path / 'bin' / 'pg_dump').write_text('#!/bin/sh\n' + dump_command + '\n');(tmp_path / 'bin' / 'pg_dump').chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path / "bin"}:{os.environ["PATH"]}', BACKUP_KEEP=str(keep), BACKUP_INTERVAL_SECONDS='1')
    return subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True), sorted((tmp_path / 'out').glob('*'))


def test_backup_loop_keeps_the_newest_files_and_never_keeps_a_failed_dump(tmp_path):
    out = tmp_path / 'out';out.mkdir()
    for index in range(5):
        old = out / f'portal-2026010{index + 1}T000000Z.sql.gz';old.write_text('x');os.utime(old, (1000 + index, 1000 + index))
    done, files = run_loop_once(tmp_path, 'echo "SELECT 1;"')
    assert 'backup written' in done.stdout and len(files) == 3 and not any(f.name.startswith('.') for f in files)
    newest = max(files, key=lambda f: f.stat().st_mtime)
    import gzip
    assert gzip.decompress(newest.read_bytes()) == b'SELECT 1;\n' and oct(newest.stat().st_mode & 0o777) == '0o600'
    before = {f.name for f in files}
    done, files = run_loop_once(tmp_path, 'echo partial; exit 3')            # pg_dump fails: the pipeline status is what counts.
    assert 'backup FAILED' in done.stdout and {f.name for f in files} == before


@pytest.mark.skipif(not (shutil.which('runuser') and shutil.which('pg_dump') and os.getenv('PORTAL_TEST_DATABASE_URL')), reason='needs a local PostgreSQL superuser')
def test_restore_check_script_restores_the_newest_dump_into_a_throwaway_database(tmp_path):
    from urllib.parse import urlsplit
    url = urlsplit(os.environ['PORTAL_TEST_DATABASE_URL'])
    probe = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-tA', '-c', 'select 1'], capture_output=True, text=True)
    if probe.returncode:pytest.skip('no local postgres superuser')
    dump = subprocess.run(['pg_dump', '-h', url.hostname, '-U', url.username, '-d', url.path[1:], '--no-owner'], env=dict(os.environ, PGPASSWORD=url.password),
                          capture_output=True)
    assert dump.returncode == 0
    import gzip
    (tmp_path / 'portal-20260101T000000Z.sql.gz').write_bytes(gzip.compress(dump.stdout))
    (tmp_path / 'portal-20250101T000000Z.sql.gz').write_bytes(b'not gzip')
    os.utime(tmp_path / 'portal-20250101T000000Z.sql.gz', (1, 1))
    env = dict(os.environ, PORTAL_BACKUP_CHECK_RUN='runuser -u postgres --', PORTAL_BACKUP_CHECK_USER='postgres')
    done = subprocess.run([str(ROOT / 'tools' / 'portal_backup_check.sh'), 'unused.yml', str(tmp_path)], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert re.search(r'^users \d+$', done.stdout, re.M) and re.search(r'^license_orders \d+$', done.stdout, re.M)
    leftovers = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-tA', '-c', "select datname from pg_database where datname like 'portal_restore_check%'"],
                               capture_output=True, text=True)
    assert leftovers.stdout.strip() == ''                                    # The throwaway database was dropped.
    empty = tmp_path / 'empty';empty.mkdir()
    assert subprocess.run([str(ROOT / 'tools' / 'portal_backup_check.sh'), 'unused.yml', str(empty)], env=env, capture_output=True).returncode == 1


def test_backup_check_script_is_valid_bash_and_executable():
    path = ROOT / 'tools' / 'portal_backup_check.sh'
    assert os.access(path, os.X_OK) and subprocess.run(['bash', '-n', str(path)]).returncode == 0


def test_caddy_logs_json_to_a_rolling_file_without_cookies_or_authorization():
    text = (ROOT / 'Caddyfile').read_text()
    for needle in ('output file /data/logs/access.log', 'roll_size 10MB', 'roll_keep 10', 'roll_keep_for 720h', 'format filter', 'wrap json',
                   'request>headers>Cookie delete', 'request>headers>Authorization delete', 'resp_headers>Set-Cookie delete'):
        assert needle in text, needle
    image = compose('portal-public-compose.yml')['services']['caddy']['image']
    assert re.fullmatch(r'caddy:2\.\d+(\.\d+)?', image) and image != 'caddy:2.8.4'


def test_ci_runs_the_new_tests_audits_dependencies_without_blocking_and_dependabot_covers_every_ecosystem():
    workflow = REPO / '.github' / 'workflows' / 'portal-tests.yml'
    dependabot = REPO / '.github' / 'dependabot.yml'
    if not workflow.exists():pytest.skip('Repository metadata is not part of a sparse checkout')
    text = workflow.read_text()
    for name in ('test_settings_key', 'test_edge', 'test_withdrawal', 'test_operations', 'test_mail', 'test_infrastructure'):
        assert f'lbank_project/tests/{name}.py' in text
    steps = yaml.safe_load(text)['jobs']['portal']['steps']
    audit = next(s for s in steps if 'pip_audit' in s.get('run', ''))
    assert audit['continue-on-error'] is True and 'requirements-web.txt' in audit['run'] and 'requirements-worker.txt' in audit['run']
    updates = yaml.safe_load(dependabot.read_text())['updates']
    assert {u['package-ecosystem']: u['directory'] for u in updates} == {'pip': '/lbank_project', 'npm': '/lbank_project/frontend',
                                                                         'docker': '/lbank_project', 'github-actions': '/'}
    assert all(u['schedule']['interval'] == 'weekly' for u in updates)


def test_release_packager_lists_every_module_the_portal_imports():
    from tools.prepare_portal_release import MODULES
    modules, _ = closure('portal_server', 'portal_worker', 'portal_admin', 'portal_migrate')
    assert {f'{m}.py' for m in modules} <= set(MODULES)
