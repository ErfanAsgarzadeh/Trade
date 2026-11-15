"""Least privilege: site secrets use settings.key; payment/telegram workers start without the customer vault key."""
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import pytest

import portal_telegram
from portal_store import PortalStore, keys_from_env
from portal_telegram import Telegram
from db_targets import TARGETS, fresh_store
from totp_helpers import enable_totp

TOKEN='123456789:'+'A'*35
ROOT=Path(__file__).resolve().parents[1]


def bot(token,method,params=None,timeout=15):
    return {'is_bot':True,'username':'AvinaTestBot'} if method=='getMe' else True


def two_stores(tmp_path):
    portal,settings=Fernet.generate_key(),Fernet.generate_key()
    web=PortalStore(tmp_path/'p.db',portal,settings)
    worker=PortalStore(tmp_path/'p.db',None,settings)
    return web,worker,portal,settings


def test_bot_token_is_sealed_with_settings_key_not_portal_key(tmp_path):
    web,worker,portal,settings=two_stores(tmp_path)
    try:
        admin=web.create_user('manager','disposable-test-password','m@example.com');web.set_admin('manager');enable_totp(web,'manager')
        Telegram(web,bot).configure(admin,TOKEN)
        with web.db() as db:sealed=db.execute("SELECT value FROM site_settings WHERE name='telegram.token'").fetchone()['value']
        assert Fernet(settings).decrypt(sealed.encode()).decode()==TOKEN
        with pytest.raises(InvalidToken):Fernet(portal).decrypt(sealed.encode())
        assert Telegram(worker).token()==TOKEN and Telegram(web).token()==TOKEN
    finally:web.close();worker.close()


def test_worker_without_portal_key_cannot_decrypt_customer_connections(tmp_path):
    web,worker,_,_=two_stores(tmp_path)
    try:
        user=web.create_user('alice','disposable-test-password','a@example.com')
        web.save_connection(user,'spot','alice-api-key','alice-secret-value')
        assert web.connection(user,decrypt=True)['secret']=='alice-secret-value'
        with pytest.raises(PermissionError):worker.connection(user,decrypt=True)
        with pytest.raises(PermissionError):worker.save_connection(user,'spot','x'*8,'y'*8)
        with pytest.raises(PermissionError):worker.vault.decrypt(b'anything')
        assert worker.connection(user)['market']=='spot'   # Metadata without the secret stays readable.
    finally:web.close();worker.close()


def test_legacy_token_is_rekeyed_when_web_holds_both_keys(tmp_path):
    portal,settings=Fernet.generate_key(),Fernet.generate_key()
    old=PortalStore(tmp_path/'p.db',portal)          # Deployment from before the settings key existed.
    with old.db() as db:db.execute("INSERT INTO site_settings(name,value,updated) VALUES('telegram.token',?,1)",(Fernet(portal).encrypt(TOKEN.encode()).decode(),))
    old.close()
    worker=PortalStore(tmp_path/'p.db',None,settings)
    assert Telegram(worker).token()==''              # The worker cannot open it yet; it never touches the portal key.
    worker.close()
    web=PortalStore(tmp_path/'p.db',portal,settings)
    try:
        assert Telegram(web).token()==TOKEN          # Read works and re-seals transparently.
        with web.db() as db:sealed=db.execute("SELECT value FROM site_settings WHERE name='telegram.token'").fetchone()['value']
        assert Fernet(settings).decrypt(sealed.encode()).decode()==TOKEN
        with pytest.raises(InvalidToken):Fernet(portal).decrypt(sealed.encode())
        assert web.rekey_settings()==0
    finally:web.close()
    worker=PortalStore(tmp_path/'p.db',None,settings)
    try:assert Telegram(worker).token()==TOKEN
    finally:worker.close()


def test_rekey_at_web_start_and_cli(tmp_path):
    portal,settings=Fernet.generate_key(),Fernet.generate_key()
    old=PortalStore(tmp_path/'p.db',portal)
    with old.db() as db:db.execute("INSERT INTO site_settings(name,value,updated) VALUES('telegram.token',?,1)",(Fernet(portal).encrypt(TOKEN.encode()).decode(),))
    old.close()
    (tmp_path/'portal.key').write_bytes(portal+b'\n');(tmp_path/'settings.key').write_bytes(settings+b'\n')
    done=subprocess.run([sys.executable,'portal_admin.py','--db',str(tmp_path/'p.db'),'--key-file',str(tmp_path/'portal.key'),
                         '--settings-key-file',str(tmp_path/'settings.key'),'rekey-settings'],cwd=ROOT,capture_output=True,text=True)
    assert done.returncode==0 and ': 1' in done.stdout,done.stderr
    worker=PortalStore(tmp_path/'p.db',None,settings)
    try:assert Telegram(worker).token()==TOKEN
    finally:worker.close()
    missing=subprocess.run([sys.executable,'portal_admin.py','--db',str(tmp_path/'p.db'),'--key-file',str(tmp_path/'portal.key'),
                            '--settings-key-file',str(tmp_path/'nope.key'),'rekey-settings'],cwd=ROOT,capture_output=True,text=True)
    assert missing.returncode!=0


def test_without_settings_key_the_portal_key_serves_both(tmp_path):
    key=Fernet.generate_key();store=PortalStore(tmp_path/'p.db',key)
    try:
        assert store.rekey_settings()==0 and store.open_setting(store.seal_setting('x'))==('x',False)
        assert Fernet(key).decrypt(store.seal_setting('x').encode())==b'x'
    finally:store.close()
    with pytest.raises(ValueError):PortalStore(tmp_path/'q.db')


def test_keys_from_env_lets_workers_start_without_portal_key(tmp_path,monkeypatch):
    (tmp_path/'s.key').write_bytes(Fernet.generate_key())
    monkeypatch.delenv('PORTAL_KEY_FILE',raising=False);monkeypatch.setenv('PORTAL_SETTINGS_KEY_FILE',str(tmp_path/'s.key'))
    key,settings=keys_from_env(portal=False)
    assert key is None and settings
    with pytest.raises(KeyError):keys_from_env()           # The web and account worker still require the portal key.
    monkeypatch.delenv('PORTAL_SETTINGS_KEY_FILE')
    with pytest.raises(KeyError):keys_from_env(portal=False)


def test_worker_mains_start_without_portal_key(tmp_path):
    """Run the real payment and telegram worker entry points with only the settings key and the database secret."""
    settings=tmp_path/'settings.key';settings.write_bytes(Fernet.generate_key())
    env={k:v for k,v in os.environ.items() if k!='PORTAL_KEY_FILE'}
    env.update(PORTAL_SETTINGS_KEY_FILE=str(settings),PORTAL_DB=str(tmp_path/'w.db'),PYTHONPATH=str(ROOT))
    for module,line in (('portal_payments','import portal_payments as m'),('portal_telegram','import portal_telegram as m')):
        code=(f"import threading,signal,os\n{line}\n"
              "threading.Timer(3,lambda:os.kill(os.getpid(),signal.SIGTERM)).start()\nm.main()\n")
        done=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
        assert 'KeyError' not in done.stderr and 'PORTAL_KEY_FILE' not in done.stderr,(module,done.stderr)
        assert (tmp_path/'w.db').exists()


def test_setup_creates_settings_key_and_never_overwrites(tmp_path,monkeypatch):
    import portal_setup
    portal_setup.prepare_secrets(tmp_path)
    key=(tmp_path/'settings.key').read_bytes();Fernet(key.strip())
    assert (tmp_path/'settings.key').stat().st_mode&0o077==0
    # An existing deployment (database secrets present) only gains the missing settings key.
    (tmp_path/'settings.key').unlink()
    monkeypatch.setattr(sys,'argv',['portal_setup.py','--directory',str(tmp_path)])
    portal_setup.main()
    created=(tmp_path/'settings.key').read_bytes()
    portal_setup.main()
    assert (tmp_path/'settings.key').read_bytes()==created


def test_operator_init_creates_both_keys_and_never_replaces_the_settings_key(tmp_path):
    base=[sys.executable,'portal_admin.py','--db',str(tmp_path/'p.db'),'--key-file',str(tmp_path/'portal.key'),'--settings-key-file',str(tmp_path/'settings.key')]
    assert subprocess.run(base+['init'],cwd=ROOT,capture_output=True,text=True).returncode==0
    Fernet((tmp_path/'portal.key').read_bytes().strip());created=(tmp_path/'settings.key').read_bytes()
    assert Fernet(created.strip()) and (tmp_path/'settings.key').stat().st_mode&0o077==0
    assert subprocess.run(base+['init'],cwd=ROOT,capture_output=True,text=True).returncode!=0   # Existing keys are never replaced.
    assert (tmp_path/'settings.key').read_bytes()==created
