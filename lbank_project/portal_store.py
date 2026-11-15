"""Pilot portal repository. Every private lookup is scoped to its authenticated owner."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from portal_database import PortalDatabase


SCRYPT_R=8
SCRYPT_P=1
LEGACY_LOG_N=14              # Hashes stored as 'salt:digest' were made with n=16384.
HASHING=threading.BoundedSemaphore(max(1,int(os.getenv('PORTAL_HASH_CONCURRENCY','4'))))  # n=2**17 needs ~128 MB per hash.
SESSION_SECONDS={'customer':43200,'admin':7200}
LOGIN_FAILURES=5
LOGIN_WINDOW=900
LOGIN_MAX_LOCK=900
FORM_MIN_AGE=3
FORM_MAX_AGE=7200


def scrypt_log_n():
    """log2 of the scrypt cost for NEW hashes. PORTAL_SCRYPT_LOG_N exists so the test suite can create many users quickly."""
    try:value=int(os.getenv('PORTAL_SCRYPT_LOG_N','17'))
    except ValueError:value=17
    return min(20,max(10,value))


def _scrypt(password,salt,log_n):
    n=2**log_n
    with HASHING:
        return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=n,r=SCRYPT_R,p=SCRYPT_P,maxmem=192*n*SCRYPT_R).hex()


def password_hash(password,salt=None,log_n=None):
    """'scrypt:<log2 n>:<r>:<p>:<salt>:<digest>'. Older hashes are 'salt:digest' with n=16384 and still verify."""
    salt=salt or secrets.token_hex(16);log_n=log_n or scrypt_log_n()
    return f'scrypt:{log_n}:{SCRYPT_R}:{SCRYPT_P}:{salt}:{_scrypt(password,salt,log_n)}'


def verify_password(password,stored):
    """(matches, needs_rehash): a correct password on an older or cheaper hash should be re-hashed at the current cost."""
    parts=stored.split(':')
    if len(parts)==2:log_n,salt,digest=LEGACY_LOG_N,parts[0],parts[1]
    elif len(parts)==6 and parts[0]=='scrypt' and parts[2:4]==[str(SCRYPT_R),str(SCRYPT_P)]:log_n,salt,digest=int(parts[1]),parts[4],parts[5]
    else:raise ValueError('Unknown password hash format')
    ok=hmac.compare_digest(_scrypt(password,salt,log_n),digest)
    return ok,ok and log_n<scrypt_log_n()


class LoginLocked(Exception):
    """Too many failures for this username; `wait` seconds remain."""

    def __init__(self,wait):
        super().__init__('Login locked');self.wait=wait


class TwoFactorRequired(Exception):
    """The password was right but the account needs a valid two-step code."""


EMAIL=re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$')


class EmailTaken(ValueError):
    """Another account already uses this email address."""


def normal_email(value):
    """Trimmed, lower-cased address; ValueError when it is not a plain email address."""
    email=str(value or '').strip().lower()
    if len(email)>254 or not EMAIL.match(email):raise ValueError('Invalid email')
    return email

SECRET_SETTINGS=('telegram.token',)  # site_settings rows holding secrets: sealed with the settings key, never the customer vault key.


class NoVault:
    """Stand-in for the customer vault in processes that were given only the settings key."""
    def encrypt(self,data):raise PermissionError('This process has no customer encryption key')
    decrypt=encrypt


def read_key(variable):
    path=os.getenv(variable)
    return Path(path).read_bytes().strip() if path else None


def keys_from_env(portal=True):
    """(portal key, settings key) from PORTAL_KEY_FILE / PORTAL_SETTINGS_KEY_FILE. `portal=False` is for services that never touch customer
    credentials: they may run with the settings key alone. Without a settings key the portal key serves both purposes."""
    key,settings=read_key('PORTAL_KEY_FILE'),read_key('PORTAL_SETTINGS_KEY_FILE')
    if key is None and (portal or settings is None):raise KeyError('PORTAL_KEY_FILE')
    return key,settings


class PortalStore:
    def __init__(self, path, key=None, settings_key=None):
        """`key` protects customers' exchange credentials and per-user secrets (the vault); `settings_key` protects site-level
        secrets such as the Telegram bot token. Without a settings key the portal key does both. Without a portal key
        (workers that only need site settings) the vault refuses to decrypt anything."""
        if not key and not settings_key:raise ValueError('An encryption key is required')
        self.vault = Fernet(key) if key else NoVault()
        self._settings=Fernet(settings_key or key)
        # Site secrets sealed before the settings key existed are still readable with the portal key.
        self._legacy=Fernet(key) if key and settings_key and settings_key!=key else None
        self.token_key=hmac.new(bytes(key or settings_key),b'avina-form-token',hashlib.sha256).digest()
        self.database=PortalDatabase(path)
        self.path=self.database.path
        # Equal work for absent usernames; no fast account-enumeration path.
        self.dummy_password = password_hash(secrets.token_urlsafe(24))

    def db(self):
        return self.database.db()

    # ---- Site-level secrets (settings key) ----------------------------------------------------------------------
    def seal_setting(self,value):
        return self._settings.encrypt(value.encode()).decode()

    def open_setting(self,value):
        """(plaintext, sealed_with_old_key). InvalidToken when neither key opens it."""
        try:return self._settings.decrypt(value.encode()).decode(),False
        except InvalidToken:
            if not self._legacy:raise
            return self._legacy.decrypt(value.encode()).decode(),True

    def rekey_settings(self,db=None):
        """Re-seal site secrets still under the portal key with the settings key. Needs both keys; returns how many changed."""
        if not self._legacy:return 0
        if db is None:
            with self.db() as db:return self.rekey_settings(db)
        changed=0
        for name in SECRET_SETTINGS:
            row=db.execute('SELECT value FROM site_settings WHERE name=?',(name,)).fetchone()
            if not row or not row['value']:continue
            try:plain,old=self.open_setting(row['value'])
            except InvalidToken:continue
            if old:
                db.execute('UPDATE site_settings SET value=? WHERE name=?',(self.seal_setting(plain),name));changed+=1
        return changed

    def close(self):self.database.close()

    def create_user(self, username, password, email=None):
        user = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO users(id,username,password,email) VALUES(?,?,?,?)',
                       (user,username,password_hash(password),normal_email(email) if email else None))
        return user

    def register(self,username,password,email,referral_code=None):
        """Create the user, session and audit event in one transaction."""
        user=str(uuid.uuid4());token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        hashed=password_hash(password);email=normal_email(email)
        with self.db() as db:
            # One lock for all sign-ups: usernames and emails are both unique.
            self.database.begin_write(db,'register')
            if db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone():
                raise ValueError('Username unavailable')
            if db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():
                raise EmailTaken('Email unavailable')
            db.execute('INSERT INTO users(id,username,password,email) VALUES(?,?,?,?)',(user,username,hashed,email))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),user,csrf,time.time()+SESSION_SECONDS['customer']))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'registered',time.time()))
            if referral_code:
                from portal_referrals import Referrals
                referrals=Referrals(self)
                # An invalid code fails the sign-up so the visitor can fix it; disabled programs are ignored.
                if referrals.settings(db)['enabled']:referrals.attach(db,user,referral_code)
        return token,csrf

    def set_admin(self,username,enabled=True):
        """Operator CLI only. No public route grants roles; all sessions are revoked."""
        from portal_audit import record
        with self.db() as db:
            self.database.begin_write(db,'admin-authority')
            user=db.execute('SELECT id,role FROM users WHERE username=?',(username,)).fetchone()
            if not user:raise ValueError('Unknown user')
            role='admin' if enabled else 'customer'
            db.execute('UPDATE users SET role=? WHERE id=?',(role,user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            record(db,None,'role_changed',user['id'],dict(role=role,source='operator_cli'))

    def attempt(self, client, limit=10):
        """Shared across processes. Count all logins before expensive password hashing."""
        with self.db() as db:
            self.database.begin_write(db,'login:'+client)
            now=self.database.clock(db)
            db.execute('DELETE FROM attempts WHERE start < ?', (now-60,))
            row=db.execute('SELECT count FROM attempts WHERE client=?',(client,)).fetchone()
            if row and row['count'] >= limit:return False
            db.execute('INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(client) DO UPDATE SET count=attempts.count+1',
                       (client,now))
            return True

    # ---- Per-username login limiter (shared through the database, so it holds across processes) -----------------
    def lock_wait(self,username):
        """Seconds until this username may try again (0 when free). Unknown usernames are treated identically."""
        with self.db() as db:
            row=db.execute('SELECT locked_until FROM login_limits WHERE username=?',(username,)).fetchone()
            now=self.database.clock(db)
            return int(row['locked_until']-now)+1 if row and row['locked_until']>now else 0

    def login_failed(self,username):
        """Five failures within 15 minutes lock the username for 1, 2, 4, 8, then at most 15 minutes."""
        with self.db() as db:
            self.database.begin_write(db,'userlimit:'+username)
            now=self.database.clock(db)
            db.execute('DELETE FROM login_limits WHERE updated<? AND locked_until<?',(now-86400,now))
            row=db.execute('SELECT * FROM login_limits WHERE username=?',(username,)).fetchone()
            if not row:failures,start,strikes,locked=1,now,0,0
            else:
                strikes=row['strikes'] if now-row['updated']<3600 else 0
                if now-row['window_start']>LOGIN_WINDOW:failures,start=1,now
                else:failures,start=row['failures']+1,row['window_start']
                locked=row['locked_until']
            if failures>=LOGIN_FAILURES:
                strikes+=1;locked=now+min(LOGIN_MAX_LOCK,60*2**(strikes-1));failures,start=0,now
            db.execute('INSERT INTO login_limits(username,failures,window_start,strikes,locked_until,updated) VALUES(?,?,?,?,?,?) '
                       'ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,window_start=excluded.window_start,'
                       'strikes=excluded.strikes,locked_until=excluded.locked_until,updated=excluded.updated',
                       (username,failures,start,strikes,locked,now))

    def login_ok(self,username):
        with self.db() as db:db.execute('DELETE FROM login_limits WHERE username=?',(username,))

    def _open_session(self,db,user,role):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(),user,csrf,time.time()+SESSION_SECONDS.get(role,SESSION_SECONDS['customer'])))
        return token,csrf

    def login(self, username, password, totp=None):
        """(token, csrf), None for bad credentials. Raises LoginLocked, or TwoFactorRequired once the password is right
        but the two-step code is missing or wrong. Every failure counts against the username, whether or not it exists."""
        from portal_security import accept_login_code
        wait=self.lock_wait(username)
        if wait:raise LoginLocked(wait)
        result=None;needs_code=False
        with self.db() as db:
            user=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            ok,rehash=verify_password(password,user['password'] if user else self.dummy_password)
            if ok and user and not user['disabled']:
                if rehash:db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),user['id']))
                needs_code=bool(user['totp_secret'])
                if not needs_code or (totp and accept_login_code(self,db,user,totp)):
                    result=self._open_session(db,user['id'],user['role'])
                    db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user['id'],'login',time.time()))
        if result:
            self.login_ok(username);return result
        self.login_failed(username)
        if needs_code:raise TwoFactorRequired()
        return None

    def password_matches(self,user,password):
        with self.db() as db:
            row=db.execute('SELECT password FROM users WHERE id=?',(user,)).fetchone()
        return bool(row) and verify_password(password,row['password'])[0]

    def change_password(self,user,password):
        """Set the password, end every session of this user and open a fresh one."""
        hashed=password_hash(password)
        with self.db() as db:
            role=db.execute('SELECT role FROM users WHERE id=?',(user,)).fetchone()['role']
            db.execute('UPDATE users SET password=? WHERE id=?',(hashed,user))
            db.execute('DELETE FROM sessions WHERE user_id=?',(user,))
            from portal_audit import record
            from portal_telegram import notify
            record(db,user,'password_changed',user)
            notify(db,user,'رمز عبور حساب آوینای شما تغییر کرد و همهٔ دستگاه‌ها خارج شدند. اگر کار شما نبود فوراً با پشتیبانی تماس بگیرید.',
                   'Your Avina password was changed and every device was signed out. If this was not you, contact support immediately.',force=True)
            return self._open_session(db,user,role)

    def revoke_others(self,user,token):
        with self.db() as db:
            return db.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',
                              (user,hashlib.sha256(token.encode()).hexdigest())).rowcount

    # ---- Sign-up form token: proves the form was open for a while without any third party -----------------------
    def form_token(self,now=None):
        stamp=str(int(time.time() if now is None else now))
        return stamp+'.'+hmac.new(self.token_key,('register:'+stamp).encode(),hashlib.sha256).hexdigest()

    def form_token_valid(self,token,now=None):
        try:
            stamp,mac=str(token or '').split('.',1);age=(time.time() if now is None else now)-int(stamp)
        except ValueError:return False
        expected=hmac.new(self.token_key,('register:'+stamp).encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac,expected) and FORM_MIN_AGE<=age<=FORM_MAX_AGE

    def set_email(self,user,email):
        email=normal_email(email)
        with self.db() as db:
            self.database.begin_write(db,'register')
            other=db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
            if other and other['id']!=user:raise EmailTaken('Email unavailable')
            # A different address is unverified again; submitting the same one leaves the flag alone.
            db.execute('UPDATE users SET email_verified=CASE WHEN email=? THEN email_verified ELSE 0 END,email=? WHERE id=?',(email,email,user))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'email_changed',time.time()))
        return email

    def session(self, token):
        with self.db() as db:
            row=db.execute('SELECT users.id,users.username,users.runtime,users.role,users.email,users.email_verified,(users.totp_secret IS NOT NULL) AS totp_enabled,sessions.csrf FROM sessions '
                           'JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>? AND disabled=0',
                           (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            return dict(row,totp_enabled=bool(row['totp_enabled']),email_verified=bool(row['email_verified'])) if row else None

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

    def save_connection(self, user, market, api_key, secret,exchange_id='lbank',passphrase='',uid='',no_withdrawal_ack=False):
        revision=str(uuid.uuid4())
        document=json.dumps(dict(owner=user,exchange_id=exchange_id,market=market,
                                 api_key=api_key,secret=secret,passphrase=passphrase,uid=uid)).encode()
        encrypted=self.vault.encrypt(document)
        with self.db() as db:
            self.database.begin_write(db,'account:'+user)
            db.execute('INSERT INTO connections(user_id,encrypted,market,revision,updated,exchange_id) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET '
                       'encrypted=excluded.encrypted,market=excluded.market,revision=excluded.revision,updated=excluded.updated,exchange_id=excluded.exchange_id',
                       (user,encrypted,market,revision,time.time(),exchange_id))
            db.execute('DELETE FROM account_cache WHERE user_id=?',(user,))
            db.execute('DELETE FROM account_jobs WHERE user_id=?',(user,))
            # The customer's confirmation that the key has no withdrawal permission is kept with the audit event.
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'connection_saved'+(':no_withdrawal_ack' if no_withdrawal_ack else ''),time.time()))

    def connection(self, user, decrypt=False):
        with self.db() as db:
            row=db.execute('SELECT * FROM connections WHERE user_id=?',(user,)).fetchone()
        if not row:return None
        result=dict(exchange_id=row['exchange_id'],market=row['market'],revision=row['revision'],updated=row['updated'])
        if decrypt:
            payload=json.loads(self.vault.decrypt(row['encrypted']))
            if payload.pop('owner') != user:raise ValueError('Credential owner mismatch')
            if 'exchange_id' in payload:
                if payload.pop('exchange_id')!=row['exchange_id'] or payload.pop('market')!=row['market']:
                    raise ValueError('Credential exchange/market mismatch')
            elif row['exchange_id']!='lbank':raise ValueError('Legacy credentials belong to LBank')
            result.update(payload)
        return result

    def wipe_connection(self, user, revision):
        """Replace a refused key (withdrawal permission) by an empty credential record. The connection stays so the customer sees why."""
        with self.db() as db:
            self.database.begin_write(db,'account:'+user)
            row=db.execute('SELECT exchange_id,market FROM connections WHERE user_id=? AND revision=?',(user,revision)).fetchone()
            if not row:return False
            blank=self.vault.encrypt(json.dumps(dict(owner=user,exchange_id=row['exchange_id'],market=row['market'],
                                                    api_key='',secret='',passphrase='',uid='')).encode())
            db.execute('UPDATE connections SET encrypted=? WHERE user_id=? AND revision=?',(blank,user,revision))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'connection_refused_withdrawal',time.time()))
            return True

    def disconnect(self, user):
        with self.db() as db:
            self.database.begin_write(db,'account:'+user)
            db.execute('DELETE FROM connections WHERE user_id=?',(user,))
            db.execute('DELETE FROM account_cache WHERE user_id=?',(user,))
            db.execute('DELETE FROM account_jobs WHERE user_id=?',(user,))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'disconnected',time.time()))

    def cache(self, user):
        with self.db() as db:
            row=db.execute('SELECT account_cache.* FROM account_cache JOIN connections USING(user_id) '
                           'WHERE user_id=? AND account_cache.revision=connections.revision',(user,)).fetchone()
        if not row:return None
        return dict(status=row['status'],checked_at=row['checked'],snapshot=json.loads(row['snapshot']) if row['snapshot'] else None)

    def public_connection(self,user):
        # One database snapshot: a rotation cannot mix an old market with a new balance.
        with self.db() as db:
            row=db.execute('SELECT c.exchange_id,c.market,c.revision,a.status,a.checked,a.snapshot FROM connections c '
                           'LEFT JOIN account_cache a ON a.user_id=c.user_id AND a.revision=c.revision WHERE c.user_id=?',(user,)).fetchone()
        if not row:return dict(configured=False,exchange_id=None,market=None,revision=None,account=None)
        account=None if row['status'] is None else dict(status=row['status'],checked_at=row['checked'],
                        snapshot=json.loads(row['snapshot']) if row['snapshot'] else None)
        return dict(configured=True,exchange_id=row['exchange_id'],market=row['market'],revision=row['revision'],account=account)

    def set_cache(self, user, revision, snapshot, status):
        with self.db() as db:
            self.database.begin_write(db,'account:'+user)
            # A rotated/deleted connection must never receive an in-flight old account response.
            db.execute('INSERT INTO account_cache SELECT user_id,revision,?,?,? FROM connections '
                       'WHERE user_id=? AND revision=? ON CONFLICT(user_id) DO UPDATE SET '
                       'revision=excluded.revision,snapshot=excluded.snapshot,checked=excluded.checked,status=excluded.status',
                       (json.dumps(snapshot) if snapshot is not None else None,time.time(),status,user,revision))

    def bind_runtime(self, user, runtime):
        runtime=Path(runtime).resolve()
        if not (runtime/'customer_identity.json').is_file():
            raise ValueError('Runtime must have a recorded customer identity')
        with self.db() as db:
            row=db.execute('SELECT username FROM users WHERE id=?',(user,)).fetchone()
            if not row:raise ValueError('Unknown user')
            if json.loads((runtime/'customer_identity.json').read_text()) != {'customer_id':row['username']}:
                raise ValueError('Runtime customer identity does not match the user')
            if db.execute('UPDATE users SET runtime=? WHERE id=?',(str(runtime),user)).rowcount != 1:
                raise ValueError('Unknown user')
