"""Pilot portal repository. Every private lookup is scoped to its authenticated owner."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet
from portal_database import PortalDatabase


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


class PortalStore:
    def __init__(self, path, key):
        self.vault = Fernet(key)
        self.database=PortalDatabase(path)
        self.path=self.database.path
        # Equal work for absent usernames; no fast account-enumeration path.
        self.dummy_password = password_hash(secrets.token_urlsafe(24))

    def db(self):
        return self.database.db()

    def close(self):self.database.close()

    def create_user(self, username, password):
        user = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO users(id,username,password) VALUES(?,?,?)',
                       (user,username,password_hash(password)))
        return user

    def attempt(self, client):
        """Shared across processes. Count all logins before expensive password hashing."""
        with self.db() as db:
            self.database.begin_write(db,'login:'+client)
            now=self.database.clock(db)
            db.execute('DELETE FROM attempts WHERE start < ?', (now-60,))
            row=db.execute('SELECT count FROM attempts WHERE client=?',(client,)).fetchone()
            if row and row['count'] >= 10:return False
            db.execute('INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(client) DO UPDATE SET count=attempts.count+1',
                       (client,now))
            return True

    def login(self, username, password):
        with self.db() as db:
            user=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            stored=user['password'] if user else self.dummy_password
            salt=stored.split(':')[0]
            if not hmac.compare_digest(password_hash(password,salt),stored) or not user or user['disabled']:
                return None
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,time.time()+43200))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user['id'],'login',time.time()))
            return token,csrf

    def session(self, token):
        with self.db() as db:
            row=db.execute('SELECT users.id,users.username,users.runtime,sessions.csrf FROM sessions '
                           'JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>? AND disabled=0',
                           (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

    def save_connection(self, user, market, api_key, secret,exchange_id='lbank',passphrase='',uid=''):
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
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(user,'connection_saved',time.time()))

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
