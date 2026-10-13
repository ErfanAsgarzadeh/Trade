"""Bounded PostgreSQL pool, explicit transactions and versioned portal schema."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3


SCHEMA_V1='''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, runtime TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL,expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
CREATE TABLE IF NOT EXISTS connections(user_id TEXT PRIMARY KEY REFERENCES users(id),
 encrypted BLOB NOT NULL,market TEXT NOT NULL,revision TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS account_cache(user_id TEXT PRIMARY KEY REFERENCES users(id),
 revision TEXT NOT NULL,snapshot TEXT,checked REAL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(client TEXT PRIMARY KEY,start REAL NOT NULL,count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id TEXT REFERENCES users(id),
 event TEXT NOT NULL,at REAL NOT NULL);
'''
SCHEMA_V2='''
CREATE TABLE IF NOT EXISTS account_jobs(user_id TEXT PRIMARY KEY REFERENCES users(id),
 revision TEXT NOT NULL,state TEXT NOT NULL,lease_token TEXT,lease_until REAL NOT NULL DEFAULT 0,
 not_before REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS account_jobs_due ON account_jobs(state,not_before,lease_until);
CREATE TABLE IF NOT EXISTS service_gate(name TEXT PRIMARY KEY,next_at REAL NOT NULL);
'''
SCHEMA_V3='''
ALTER TABLE connections ADD COLUMN exchange_id TEXT NOT NULL DEFAULT 'lbank';
CREATE INDEX IF NOT EXISTS connections_exchange ON connections(exchange_id);
UPDATE service_gate SET name='account-read:lbank' WHERE name='lbank-read';
'''


class PostgresConnection:
    def __init__(self,connection):self.connection=connection
    def execute(self,query,params=()):
        # Repository SQL uses positional ? parameters; values are always driver-bound.
        return self.connection.execute(query.replace('?','%s'),params)


class PortalDatabase:
    def __init__(self,target,pool_max=None):
        target=str(target)
        self.postgres=target.startswith(('postgresql://','postgres://'))
        self.pool=None
        self.path=None
        if self.postgres:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            maximum=int(pool_max or os.getenv('PORTAL_DB_POOL_MAX','8'))
            if not 1<=maximum<=64:raise ValueError('Database pool size must be 1..64')
            self.pool=ConnectionPool(target,min_size=1,max_size=maximum,open=False,timeout=5,max_waiting=64,
                                    kwargs=dict(row_factory=dict_row,connect_timeout=5,prepare_threshold=None,
                                                options='-c statement_timeout=10000 -c lock_timeout=5000'))
            try:
                self.pool.open();self.pool.wait(timeout=10)
            except Exception:
                self.pool.close();raise
        else:
            self.path=Path(target).resolve()
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with self.db() as db:db.execute('PRAGMA journal_mode=WAL')
        try:self.migrate()
        except Exception:
            self.close();raise
        if self.path:self.path.chmod(0o600)

    @contextmanager
    def db(self):
        if self.pool:
            with self.pool.connection() as connection:
                yield PostgresConnection(connection)
        else:
            connection=sqlite3.connect(self.path,timeout=10)
            connection.row_factory=sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback();raise
            finally:connection.close()

    def begin_write(self,db,scope):
        if self.postgres:
            lock=int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8],'big',signed=True)
            db.execute('SELECT pg_advisory_xact_lock(?)',(lock,))
        else:db.execute('BEGIN IMMEDIATE')

    def clock(self,db):
        if self.postgres:return float(db.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now').fetchone()['now'])
        import time
        return time.time()

    def migrate(self):
        with self.db() as db:
            self.begin_write(db,'portal-schema')
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)')
            versions={row['version'] for row in db.execute('SELECT version FROM schema_migrations').fetchall()}
            if versions-{1,2,3}:raise ValueError('Portal schema newer than this application')
            for version,script in ((1,SCHEMA_V1),(2,SCHEMA_V2),(3,SCHEMA_V3)):
                if version in versions:continue
                if self.postgres:
                    script=script.replace(' BLOB ',' BYTEA ').replace(' REAL',' DOUBLE PRECISION')
                    script=script.replace('id INTEGER PRIMARY KEY,user_id','id BIGSERIAL PRIMARY KEY,user_id')
                for statement in script.split(';'):
                    if statement.strip():db.execute(statement)
                db.execute('INSERT INTO schema_migrations VALUES(?)',(version,))

    def close(self):
        if self.pool:self.pool.close()


def configured_target():
    """A file-backed DSN avoids putting the database password into container environment."""
    filename=os.getenv('PORTAL_DATABASE_URL_FILE')
    if filename:
        target=Path(filename).read_text().strip()
        if not target.startswith(('postgresql://','postgres://')):raise ValueError('Expected PostgreSQL URL in secret file')
        return target
    return os.getenv('PORTAL_DATABASE_URL') or os.getenv('PORTAL_DB','runtime/portal/portal.db')
