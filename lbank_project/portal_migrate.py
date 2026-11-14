"""Offline copy of an existing SQLite portal to an EMPTY PostgreSQL/SQLite target."""
import json
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet
from portal_store import PortalStore


TABLES={
 'users':('id','username','password','disabled','runtime','role','email'),
 'sessions':('token_hash','user_id','csrf','expires'),
 'connections':('user_id','encrypted','market','revision','updated','exchange_id'),
 'account_cache':('user_id','revision','snapshot','checked','status'),
 'attempts':('client','start','count'),
 'audit':('id','user_id','event','at'),
 'account_jobs':('user_id','revision','state','lease_token','lease_until','not_before','attempts','updated'),
 'service_gate':('name','next_at'),
 'license_orders':('id','user_id','cap_usd','months','kind','price_cents','price_version','status','created','updated','request_key','payment_ref','product'),
 'product_pricing':('product','prices','enabled','version','updated'),
 'capital_licenses':('user_id','account_id','document','updated'),
 'admin_events':('id','actor_id','action','target','details','at'),
 'license_approvals':('id','order_id','requested_by','payload','payment_ref','state','lease_token','lease_until','attempts','created','updated','error_code'),
 'license_cashflows':('user_id','event_id','amount_usd','at'),
 'blog_posts':('id','slug','title','description','keywords','body','status','published_on','created','updated','lang'),
 'blog_images':('id','name','width','height','size','data','created'),
 'site_settings':('name','value','updated'),
 'telegram_links':('user_id','chat_id','username','lang','signals','notices','linked'),
 'payment_invoices':('id','order_id','user_id','network','token','address','amount_micro','status','created','expires','paid_at','tx_ref'),
 'payment_transfers':('tx_ref','network','token','from_address','to_address','amount_micro','block_time','seen','invoice_id','status'),
}


def migrate_sqlite(source,target,key):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('Source database missing')
    if not str(target).startswith(('postgres://','postgresql://')) and Path(target).resolve()==source:
        raise ValueError('Source and target must differ')
    destination=PortalStore(target,key)
    counts={}
    try:
        # Read-write connection solely for a lock. Source records are never modified.
        with sqlite3.connect(source,timeout=10) as src,destination.db() as dst:
            src.row_factory=sqlite3.Row;src.execute('BEGIN IMMEDIATE')
            destination.database.begin_write(dst,'portal-offline-migration')
            for table in TABLES:
                if dst.execute('SELECT COUNT(*) AS count FROM '+table).fetchone()['count']:
                    raise ValueError('Target must be completely empty; stop portal and workers before migration')
            existing={r['name'] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'users','sessions','connections','account_cache','attempts','audit'}<=existing:
                raise ValueError('Source is not a portal database')
            vault=Fernet(key)
            for table,columns in TABLES.items():
                if table not in existing:continue
                fields=','.join(columns)
                select_fields=fields
                if table=='users':
                    present={r['name'] for r in src.execute('PRAGMA table_info(users)')}
                    select_fields=','.join(c if c in present else {'role':"'customer' AS role",'email':'NULL AS email'}[c] for c in columns)
                if table=='blog_posts' and 'lang' not in {r['name'] for r in src.execute('PRAGMA table_info(blog_posts)')}:
                    select_fields=','.join(columns[:-1])+",'fa' AS lang"
                if table=='connections' and 'exchange_id' not in {r['name'] for r in src.execute('PRAGMA table_info(connections)')}:
                    select_fields=','.join(columns[:-1])+",'lbank' AS exchange_id"
                if table=='license_orders' and 'product' not in {r['name'] for r in src.execute('PRAGMA table_info(license_orders)')}:
                    select_fields=','.join(columns[:-1])+",'autotrade' AS product"
                rows=src.execute('SELECT '+select_fields+' FROM '+table).fetchall()
                counts[table]=len(rows)
                query='INSERT INTO '+table+' ('+fields+') VALUES('+','.join('?' for _ in columns)+')'
                for row in rows:
                    values=list(row)
                    if table=='service_gate' and row['name']=='lbank-read':
                        values[0]='account-read:lbank'
                    if table=='connections':
                        payload=json.loads(vault.decrypt(row['encrypted']))
                        if payload['owner']!=row['user_id']:raise ValueError('Source credential owner mismatch')
                        if payload.get('exchange_id','lbank')!=row['exchange_id'] or ('market' in payload and payload['market']!=row['market']):
                            raise ValueError('Source credential exchange/market mismatch')
                    if table=='license_approvals' and row['state']=='running':
                        values[5]='queued';values[6]=None;values[7]=0;values[8]=0
                    if table=='account_jobs' and row['state']=='running':
                        values[2]='queued';values[3]=None;values[4]=0;values[6]=0
                    dst.execute(query,values)
                actual=dst.execute('SELECT COUNT(*) AS count FROM '+table).fetchone()['count']
                if actual!=len(rows):raise ValueError('Migration count mismatch')
            if destination.database.postgres:
                dst.execute("SELECT setval(pg_get_serial_sequence('audit','id'),COALESCE(MAX(id),1),MAX(id) IS NOT NULL) FROM audit")
        return counts
    finally:destination.close()
