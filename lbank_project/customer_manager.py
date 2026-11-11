"""Create isolated, signed, Docker-ready customer distributions. No real orders."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import uuid
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import license_access

HERE = Path(__file__).resolve().parent
CUSTOMER_ID = re.compile(r'^[a-z][a-z0-9-]{1,39}$')
APP_FILES = ('frontend/public/portal-assets/titanium.css', 'frontend/public/portal-assets/appearance.js',
             'lbank_bot.py', 'strategy_archetypes.py', 'dashboard_server.py',
             'c3_sleeve.py', 'pa_sleeve.py', 'shared_paper_account.py',
             'lbank_candles.py', 'fetch_funding.py', 'license_access.py', 'capital_plans.py', 'signal_feed.py',
             'lbank_official_candles.py',
             'deployment_security.py', 'customer_entrypoint.py', 'requirements.txt',
             'Dockerfile', 'config.json', 'c3_config.json', 'pa_config.json',
             'momentum.py', 'performance.py', 'lbank_account.py', 'exchanges.py', 'live_mirror.py')


def validate_id(customer: str):
    if not CUSTOMER_ID.fullmatch(customer):
        raise ValueError('Customer ID must be 2..40 lowercase letters/digits/hyphens, starting with a letter')


def private_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)


def keygen(private: Path, public: Path):
    if private.resolve() == public.resolve() or private.exists() or public.exists():
        raise ValueError('Use distinct new paths; issuer keys are never overwritten')
    key = Ed25519PrivateKey.generate()
    private_write(private, key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_write(public, key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))


def issue(private: Path, customer: str, days: int, plan: str, now=None) -> bytes:
    validate_id(customer)
    if type(days) is not int or not 1 <= days <= 3660 or not plan.strip() or len(plan) > 80:
        raise ValueError('License duration must be 1..3660 days; plan must be 1..80 characters')
    key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Issuer key must be Ed25519')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('License issue time must include timezone')
    payload = dict(schema=1, customer_id=customer, license_id=str(uuid.uuid4()),
                   issued_at=now.isoformat(), not_before=now.isoformat(),
                   expires_at=(now + timedelta(days=days)).isoformat(), plan=plan.strip())
    return (json.dumps(dict(payload=payload, signature=base64.b64encode(
        key.sign(license_access.canonical(payload))).decode('ascii')), indent=2) + '\n').encode()


def checked_customer(root: Path, customer: str) -> Path:
    validate_id(customer)
    parent = root.resolve()
    path = parent / customer
    if path.is_symlink() or path.resolve().parent != parent:
        raise ValueError('Customer directory must not be a symlink')
    return path


def create(root: Path, customer: str, private: Path, public: Path, port: int,
           capital: float, days=30, plan='beta', data_mode='demo') -> Path:
    destination = checked_customer(root, customer)
    if destination.exists():
        raise ValueError('Customer already exists; use renew to preserve runtime data')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Dashboard port must be 1024..65535')
    if not math.isfinite(capital) or not 0 < capital <= 1e9:
        raise ValueError('Paper capital must be finite, positive and <= 1e9')
    if data_mode not in ('demo', 'csv-lbank'):
        raise ValueError('Only demo or csv-lbank paper data is supported')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for meta in root.glob('*/customer.json'):
        if json.loads(meta.read_text())['dashboard_port'] == port:
            raise ValueError('Dashboard port is already assigned to another customer')
    document = issue(private, customer, days, plan)
    signing = serialization.load_pem_private_key(private.read_bytes(), password=None)
    if signing.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo) != public.read_bytes():
        raise ValueError('Issuer private and public keys do not match')
    staging = Path(tempfile.mkdtemp(prefix='.new-customer-', dir=root))
    try:
        app = staging / 'app';app.mkdir()
        for name in APP_FILES:
            (app / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / name, app / name)
        shutil.copyfile(HERE / 'customer-compose.yml', staging / 'compose.yml')
        shutil.copyfile(HERE / 'CUSTOMER_QUICKSTART_FA.md', staging / 'README_FA.md')
        runtime = staging / 'runtime';runtime.mkdir(mode=0o700)
        for name in ('config.json', 'c3_config.json', 'pa_config.json'):
            config = json.loads((HERE / name).read_text())
            if name == 'config.json':
                config['bot_control'].update(dry_run_mode=True, auto_trade_enabled=False)
            else:
                config.update(dry_run_mode=True, enabled=False, paper_capital=capital)
            (runtime / name).write_text(json.dumps(config, indent=2) + '\n')
        for sub in ('ohlcv', 'funding'):(runtime / sub).mkdir()
        private_write(staging / 'secrets' / 'dashboard_pin', (secrets.token_urlsafe(24)+'\n').encode())
        private_write(staging / 'license' / 'license.json', document)
        private_write(staging / 'license' / 'license_public.pem', public.read_bytes())
        profile = dict(customer_id=customer, dashboard_port=port, paper_capital=capital,
                       data_mode=data_mode, execution='paper', schema=1)
        (staging / 'customer.json').write_text(json.dumps(profile, indent=2)+'\n')
        env = f'CUSTOMER_ID={customer}\nDASHBOARD_PORT={port}\nPAPER_EQUITY={capital}\nPAPER_DATA_MODE={data_mode}\n'
        private_write(staging / '.env', env.encode())
        staging.rename(destination)
    finally:
        if staging.exists():shutil.rmtree(staging)
    return destination


def renew(root: Path, customer: str, private: Path, days=30, plan='beta') -> Path:
    directory = checked_customer(root, customer)
    current = license_access.verify_document((directory / 'license' / 'license.json').read_text(),
                                             (directory / 'license' / 'license_public.pem').read_bytes())
    if current['schema'] == 2:
        raise ValueError('Capital licenses must be renewed through portal billing; legacy renew cannot remove capital limits')
    public = serialization.load_pem_public_key((directory / 'license' / 'license_public.pem').read_bytes())
    key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    if key.public_key().public_bytes(serialization.Encoding.Raw,
            serialization.PublicFormat.Raw) != public.public_bytes(serialization.Encoding.Raw,
            serialization.PublicFormat.Raw):
        raise ValueError('Renewal key does not match this installation')
    document = issue(private, customer, days, plan)
    with tempfile.NamedTemporaryFile(dir=directory / 'license', delete=False) as f:
        f.write(document);temporary = Path(f.name)
    temporary.chmod(0o600);temporary.replace(directory / 'license' / 'license.json')
    return directory / 'license' / 'license.json'


def install_license(root: Path, customer: str, source: Path) -> Path:
    """Install an issuer-approved license without changing configs, balances or positions."""
    directory = checked_customer(root, customer)
    document = source.read_text(encoding='utf-8')
    public = (directory / 'license' / 'license_public.pem').read_bytes()
    payload = license_access.verify_document(document, public)
    if payload.get('schema') != 2 or payload.get('customer_id') != customer:
        raise ValueError('Expected a capital license issued for this customer')
    if payload.get('product','autotrade')!='autotrade':
        raise ValueError('Signal-only licenses are used in the portal, not a trading installation')
    from capital_plans import money, price_cents
    price_cents(payload['cap_usd'], payload['months'])
    if money(payload['capital_at_activation_usd'], positive=True) > payload['cap_usd']:
        raise ValueError('Activation capital exceeds license tier')
    if license_access.timestamp(payload['not_before']) >= license_access.timestamp(payload['expires_at']):
        raise ValueError('Invalid license period')
    account = payload['account_id']
    if not re.fullmatch(r'[a-z0-9][a-z0-9:._-]{2,119}', account):
        raise ValueError('Invalid account binding')
    binding = directory / 'license' / 'account_id'
    if binding.exists() and binding.read_text().strip() != account:
        raise ValueError('Customer installation is bound to another exchange account')
    if not binding.exists():private_write(binding, (account + '\n').encode())
    with tempfile.NamedTemporaryFile(dir=directory / 'license', delete=False) as out:
        out.write(document.encode('utf-8'));out.flush();os.fsync(out.fileno());temporary = Path(out.name)
    temporary.chmod(0o600);temporary.replace(directory / 'license' / 'license.json')
    return directory / 'license' / 'license.json'


def export(root: Path, customer: str, output: Path) -> Path:
    """Initial handoff only: allowlist code + bootstrap config, never databases or issuer keys."""
    directory = checked_customer(root, customer)
    names = ['compose.yml', 'README_FA.md', 'customer.json', '.env', 'license/license.json',
             'license/license_public.pem', 'secrets/dashboard_pin']
    names += ['app/' + name for name in APP_FILES]
    if (directory / 'license' / 'account_id').is_file():names.append('license/account_id')
    names += ['runtime/' + name for name in ('config.json', 'c3_config.json', 'pa_config.json')]
    configs = [json.loads((directory / 'runtime' / n).read_text())
               for n in ('config.json', 'c3_config.json', 'pa_config.json')]
    if configs[0]['bot_control']['dry_run_mode'] is not True or any(c['dry_run_mode'] is not True for c in configs[1:]):
        raise ValueError('Only paper execution can be exported')
    if configs[0]['bot_control']['auto_trade_enabled'] or any(c['enabled'] for c in configs[1:]):
        raise ValueError('Export is for an inactive bootstrap, not an active customer deployment')
    if any((directory / 'runtime').glob('*.db*')):
        raise ValueError('Do not export an initialized customer account as a new installation')
    for name in names:
        item = directory / name
        if item.is_symlink() or not item.is_file() or not item.resolve().is_relative_to(directory):
            raise ValueError('Package contains an unsafe or missing file')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as f, zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(directory / name, name)
    output.chmod(0o600)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    keys = actions.add_parser('keygen');keys.add_argument('--private-key', type=Path, required=True);keys.add_argument('--public-key', type=Path, required=True)
    install = actions.add_parser('install-license');install.add_argument('customer')
    install.add_argument('--root', type=Path, default=Path('customers'));install.add_argument('--file', type=Path, required=True)
    for action in ('create', 'renew', 'export'):
        sub = actions.add_parser(action);sub.add_argument('customer');sub.add_argument('--root', type=Path, default=Path('customers'))
        if action != 'export':
            sub.add_argument('--private-key', type=Path, required=True);sub.add_argument('--days', type=int, default=30);sub.add_argument('--plan', default='beta')
        if action == 'create':
            sub.add_argument('--public-key', type=Path, required=True);sub.add_argument('--port', type=int, required=True)
            sub.add_argument('--paper-capital', type=float, default=10000.);sub.add_argument('--data-mode', choices=('demo','csv-lbank'), default='demo')
        if action == 'export':sub.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'keygen':keygen(args.private_key,args.public_key);print('Issuer keys created; keep the private key private.')
        elif args.action == 'install-license':print(install_license(args.root,args.customer,args.file))
        elif args.action == 'create':print(create(args.root,args.customer,args.private_key,args.public_key,args.port,args.paper_capital,args.days,args.plan,args.data_mode))
        elif args.action == 'renew':print(renew(args.root,args.customer,args.private_key,args.days,args.plan))
        else:print(export(args.root,args.customer,args.output))
    except (ValueError, OSError) as exc:parser.exit(2, str(exc)+'\n')


if __name__ == '__main__':main()
