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
SCHEMA_V4='''
CREATE TABLE IF NOT EXISTS license_orders(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),
 cap_usd INTEGER NOT NULL,months INTEGER NOT NULL,kind TEXT NOT NULL,
 price_cents INTEGER NOT NULL,price_version TEXT NOT NULL,
 status TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
 request_key TEXT NOT NULL,payment_ref TEXT UNIQUE,
 UNIQUE(user_id,request_key));
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_license_order ON license_orders(user_id) WHERE status='pending';
CREATE INDEX IF NOT EXISTS license_orders_owner ON license_orders(user_id,created);
CREATE TABLE IF NOT EXISTS capital_licenses(
 user_id TEXT PRIMARY KEY REFERENCES users(id),account_id TEXT UNIQUE NOT NULL,
 document TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS license_cashflows(
 user_id TEXT NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,
 amount_usd TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(user_id,event_id));
'''

SCHEMA_V5='''
ALTER TABLE license_orders ADD COLUMN product TEXT NOT NULL DEFAULT 'autotrade';
CREATE TABLE IF NOT EXISTS product_pricing(product TEXT PRIMARY KEY,prices TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0,version TEXT NOT NULL,updated REAL NOT NULL);
'''

SCHEMA_V6='''
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'customer' CHECK(role IN ('customer','admin'));
CREATE TABLE IF NOT EXISTS admin_events(id TEXT PRIMARY KEY,actor_id TEXT REFERENCES users(id),
 action TEXT NOT NULL,target TEXT NOT NULL,details TEXT NOT NULL,at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS admin_events_time ON admin_events(at);
CREATE TABLE IF NOT EXISTS license_approvals(id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL REFERENCES license_orders(id),
 requested_by TEXT NOT NULL REFERENCES users(id),payload TEXT NOT NULL,payment_ref TEXT UNIQUE NOT NULL,
 state TEXT NOT NULL,lease_token TEXT,lease_until REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL,updated REAL NOT NULL,error_code TEXT);
CREATE INDEX IF NOT EXISTS license_approvals_due ON license_approvals(state,lease_until);
'''

SCHEMA_V7='''
CREATE TABLE IF NOT EXISTS blog_posts(id TEXT PRIMARY KEY,slug TEXT UNIQUE NOT NULL,title TEXT NOT NULL,
 description TEXT NOT NULL,keywords TEXT NOT NULL,body TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','published')),published_on TEXT,
 created REAL NOT NULL,updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS blog_posts_public ON blog_posts(status,published_on);
'''
SCHEMA_V8='''
ALTER TABLE users ADD COLUMN email TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL;
CREATE TABLE IF NOT EXISTS blog_articles(id TEXT PRIMARY KEY,lang TEXT NOT NULL CHECK(lang IN ('fa','en')),
 slug TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,keywords TEXT NOT NULL,body TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','published')),published_on TEXT,
 created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(lang,slug));
INSERT INTO blog_articles(id,lang,slug,title,description,keywords,body,status,published_on,created,updated)
 SELECT id,'fa',slug,title,description,keywords,body,status,published_on,created,updated FROM blog_posts;
DROP TABLE blog_posts;
ALTER TABLE blog_articles RENAME TO blog_posts;
CREATE INDEX IF NOT EXISTS blog_posts_public ON blog_posts(lang,status,published_on);
'''
SCHEMA_V9='''
CREATE TABLE IF NOT EXISTS blog_images(id TEXT PRIMARY KEY,name TEXT NOT NULL,width INTEGER NOT NULL,
 height INTEGER NOT NULL,size INTEGER NOT NULL,data BLOB NOT NULL,created REAL NOT NULL);
'''
SCHEMA_V10='''
CREATE TABLE IF NOT EXISTS site_settings(name TEXT PRIMARY KEY,value TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS payment_invoices(id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES license_orders(id),
 user_id TEXT NOT NULL REFERENCES users(id),network TEXT NOT NULL,token TEXT NOT NULL,address TEXT NOT NULL,
 amount_micro BIGINT NOT NULL,status TEXT NOT NULL CHECK(status IN ('open','expired','replaced','paid','cancelled')),
 created REAL NOT NULL,expires REAL NOT NULL,paid_at REAL,tx_ref TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS payment_invoices_match ON payment_invoices(network,token,amount_micro,status);
CREATE INDEX IF NOT EXISTS payment_invoices_order ON payment_invoices(order_id);
CREATE TABLE IF NOT EXISTS payment_transfers(tx_ref TEXT PRIMARY KEY,network TEXT NOT NULL,token TEXT NOT NULL,
 from_address TEXT NOT NULL,to_address TEXT NOT NULL,amount_micro BIGINT NOT NULL,block_time REAL NOT NULL,
 seen REAL NOT NULL,invoice_id TEXT,status TEXT NOT NULL CHECK(status IN ('matched','unmatched')));
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
            if versions-{1,2,3,4,5,6,7,8,9,10}:raise ValueError('Portal schema newer than this application')
            for version,script in ((1,SCHEMA_V1),(2,SCHEMA_V2),(3,SCHEMA_V3),(4,SCHEMA_V4),(5,SCHEMA_V5),(6,SCHEMA_V6),(7,SCHEMA_V7),(8,SCHEMA_V8),(9,SCHEMA_V9),(10,SCHEMA_V10)):
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
