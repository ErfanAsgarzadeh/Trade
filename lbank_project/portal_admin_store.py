"""Admin workbench queries. No password hashes, vault blobs, API keys or private paths."""
from contextlib import contextmanager
import json
import re
import time
import uuid

from capital_plans import money
from portal_audit import require_admin,record
from portal_billing import Billing,BillingConflict
from portal_jobs import AccountQueue
import product_pricing


class AdminStore:
    def __init__(self,store):self.store=store

    @contextmanager
    def write(self,actor,owner=None):
        with self.store.db() as db:
            self.store.database.begin_write(db,'admin-authority')
            if owner and self.store.database.postgres:self.store.database.begin_write(db,'billing:'+owner)
            require_admin(db,actor)
            yield db

    def overview(self):
        with self.store.db() as db:
            counts={key:db.execute(query).fetchone()['n'] for key,query in {
                'users':'SELECT COUNT(*) AS n FROM users',
                'enabled_users':'SELECT COUNT(*) AS n FROM users WHERE disabled=0',
                'pending_orders':"SELECT COUNT(*) AS n FROM license_orders WHERE status='pending'",
                'issued_licenses':'SELECT COUNT(*) AS n FROM capital_licenses',
                'queued_approvals':"SELECT COUNT(*) AS n FROM license_approvals WHERE state IN ('queued','running')",
                'failed_approvals':"SELECT COUNT(*) AS n FROM license_approvals WHERE state='failed'"}.items()}
            heartbeat=db.execute("SELECT next_at FROM service_gate WHERE name='license-issuer:heartbeat'").fetchone()
        return dict(counts=counts,pricing=product_pricing.catalog(self.store),account_queue=AccountQueue(self.store).summary(),
                    issuer_last_seen=heartbeat['next_at'] if heartbeat else None)

    def users(self,search='',offset=0,limit=30):
        where=' WHERE (u.username LIKE ? OR u.email LIKE ?)';params=('%'+search+'%','%'+search.lower()+'%')
        with self.store.db() as db:
            total=db.execute('SELECT COUNT(*) AS n FROM users u'+where,params).fetchone()['n']
            rows=db.execute('SELECT u.id,u.username,u.email,u.disabled,u.role,CASE WHEN u.runtime IS NULL THEN 0 ELSE 1 END AS has_runtime, '
                            'CASE WHEN c.user_id IS NULL THEN 0 ELSE 1 END AS has_connection FROM users u '
                            'LEFT JOIN connections c ON c.user_id=u.id'+where+' ORDER BY u.username LIMIT ? OFFSET ?',params+(limit,offset)).fetchall()
        return dict(items=[dict(r) for r in rows],total=total,offset=offset,limit=limit)

    def set_disabled(self,actor,user_id,disabled):
        with self.write(actor) as db:
            user=db.execute('SELECT role,disabled FROM users WHERE id=?',(user_id,)).fetchone()
            if not user:raise LookupError('User not found')
            if user_id==actor or user['role']=='admin':raise BillingConflict('Admin accounts are managed by the operator CLI')
            db.execute('UPDATE users SET disabled=? WHERE id=?',(int(disabled),user_id))
            if disabled:db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            record(db,actor,'user_disabled' if disabled else 'user_enabled',user_id)
        return dict(status='disabled' if disabled else 'enabled')

    def orders(self,status='pending',offset=0,limit=30):
        clause=' WHERE o.status=?' if status!='all' else ''
        args=(status,) if status!='all' else ()
        with self.store.db() as db:
            total=db.execute('SELECT COUNT(*) AS n FROM license_orders o'+clause,args).fetchone()['n']
            rows=db.execute('SELECT o.id,o.user_id,u.username,o.cap_usd,o.months,o.kind,o.product,o.price_cents,o.price_version,o.status,o.created,o.updated,'
                            'a.state AS approval_state,a.error_code FROM license_orders o JOIN users u ON u.id=o.user_id '
                            'LEFT JOIN license_approvals a ON a.order_id=o.id'+clause+' ORDER BY o.created DESC,o.id LIMIT ? OFFSET ?',args+(limit,offset)).fetchall()
        return dict(items=[dict(r) for r in rows],total=total,offset=offset,limit=limit)

    def _owner(self,oid):
        with self.store.db() as db:row=db.execute('SELECT user_id FROM license_orders WHERE id=?',(oid,)).fetchone()
        if not row:raise LookupError('Order not found')
        return row['user_id']

    def reject(self,actor,oid,reason):
        owner=self._owner(oid)
        with self.write(actor,owner) as db:
            if db.execute("UPDATE license_orders SET status='rejected',updated=? WHERE id=? AND status='pending'",(time.time(),oid)).rowcount!=1:
                raise BillingConflict('Only pending orders can be rejected')
            db.execute("UPDATE license_approvals SET state='cancelled',lease_token=NULL,lease_until=0,updated=? WHERE order_id=? AND state!='completed'",(time.time(),oid))
            record(db,actor,'order_rejected',oid,dict(reason=reason))
        return dict(status='rejected')

    def request_approval(self,actor,oid,payment_ref,account_id=None,equity_usd=None):
        owner=self._owner(oid);now=time.time()
        with self.write(actor,owner) as db:
            order=db.execute('SELECT o.*,u.disabled FROM license_orders o JOIN users u ON u.id=o.user_id WHERE o.id=?',(oid,)).fetchone()
            if order['status']!='pending' or order['disabled']:raise BillingConflict('Order or user is not eligible')
            existing=db.execute('SELECT * FROM license_approvals WHERE order_id=?',(oid,)).fetchone()
            payload=dict(account_id=account_id,equity_usd=equity_usd,payment_ref=payment_ref)
            if existing and existing['state'] in ('queued','running'):
                if json.loads(existing['payload'])!=payload:raise BillingConflict('A different approval is already queued')
                return dict(id=existing['id'],status=existing['state'],already_pending=True)
            quote=Billing(self.store)._quote(db,owner,order['cap_usd'],order['months'],order['kind'],now,order['product'])
            if quote['price_version']!=order['price_version']:raise BillingConflict('Tariff version changed; request a new order')
            if order['product']=='autotrade':
                if not account_id or not re.fullmatch(r'[a-z0-9][a-z0-9:._-]{2,119}',account_id):raise ValueError('Verified account UID required')
                equity=money(equity_usd,positive=True)
                if order['kind']=='subscription' and equity>order['cap_usd']:raise BillingConflict('Capital exceeds tier')
            elif account_id is not None or equity_usd is not None:raise ValueError('Signal subscriptions do not need exchange details')
            previous=db.execute('SELECT order_id FROM license_approvals WHERE payment_ref=?',(payment_ref,)).fetchone()
            paid=db.execute('SELECT id FROM license_orders WHERE payment_ref=?',(payment_ref,)).fetchone()
            if paid or (previous and previous['order_id']!=oid):raise BillingConflict('Payment reference already used')
            jid=existing['id'] if existing else str(uuid.uuid4())
            db.execute("INSERT INTO license_approvals(id,order_id,requested_by,payload,payment_ref,state,created,updated) VALUES(?,?,?,?,?,'queued',?,?) "
                       "ON CONFLICT(order_id) DO UPDATE SET requested_by=excluded.requested_by,payload=excluded.payload,payment_ref=excluded.payment_ref,"
                       "state='queued',lease_token=NULL,lease_until=0,attempts=0,updated=excluded.updated,error_code=NULL",
                       (jid,oid,actor,json.dumps(payload),payment_ref,now,now))
            record(db,actor,'approval_requested',oid,dict(job_id=jid))
        return dict(id=jid,status='queued',already_pending=False)

    def events(self,offset=0,limit=30):
        with self.store.db() as db:
            total=db.execute('SELECT COUNT(*) AS n FROM admin_events').fetchone()['n']
            rows=db.execute('SELECT e.id,e.action,e.target,e.details,e.at,u.username AS actor FROM admin_events e '
                            'LEFT JOIN users u ON u.id=e.actor_id ORDER BY e.at DESC,e.id LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        return dict(items=[dict(r,details=json.loads(r['details'])) for r in rows],total=total,offset=offset,limit=limit)
