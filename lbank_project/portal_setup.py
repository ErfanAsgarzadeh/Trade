"""Generate NEW local PostgreSQL deployment secrets; preserve any existing portal key."""
import argparse
from pathlib import Path
import secrets

from cryptography.fernet import Fernet
from customer_manager import private_write


def ensure_settings_key(directory):
    """Create issuer-keys/settings.key when missing; an existing one is validated and never replaced. True when created."""
    path=Path(directory)/'settings.key'
    if path.exists():Fernet(path.read_bytes().strip());return False
    private_write(path,Fernet.generate_key()+b'\n');return True


def prepare_secrets(directory):
    directory=Path(directory)
    password_file=directory/'postgres_password'
    url_file=directory/'portal_database_url'
    key_file=directory/'portal.key'
    settings_file=directory/'settings.key'
    if password_file.exists() or url_file.exists():raise ValueError('Database secrets exist; never overwrite them')
    if settings_file.exists():Fernet(settings_file.read_bytes().strip())
    key=key_file.read_bytes().strip() if key_file.exists() else Fernet.generate_key()
    Fernet(key)  # Validate an existing master key; never replace it during deployment/migration.
    password=secrets.token_urlsafe(36)
    created=[]
    try:
        for path,data in ((password_file,password.encode()+b'\n'),
                          (url_file,f'postgresql://trade_portal:{password}@db:5432/trade_portal\n'.encode())):
            private_write(path,data);created.append(path)
        if not key_file.exists():private_write(key_file,key+b'\n');created.append(key_file)
        # A separate key for site-level secrets (the Telegram bot token), so the workers never need the customer vault key.
        if ensure_settings_key(directory):created.append(settings_file)
    except Exception:
        for path in created:path.unlink()
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('issuer-keys'))
    args=parser.parse_args()
    try:
        if (args.directory/'postgres_password').exists() or (args.directory/'portal_database_url').exists():
            # An existing deployment only gains the settings key; its database secrets and portal key are untouched.
            created=ensure_settings_key(args.directory)
            print('Database secrets exist and were left unchanged. '+('Settings key created.' if created else 'Settings key already present.'));return
        prepare_secrets(args.directory)
    except (ValueError,OSError) as exc:parser.exit(2,str(exc)+'\n')
    print('Secrets prepared. Existing portal master key preserved. No secrets printed.')


if __name__=='__main__':main()
