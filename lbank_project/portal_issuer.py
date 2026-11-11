"""Isolated signing worker: the web process never receives the issuer private key."""
import argparse
import json
import os
from pathlib import Path
import signal
import threading
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from portal_billing import Billing
from portal_store import PortalStore
from portal_database import configured_target
from portal_audit import record


class Issuer:
    def __init__(self,store,private):
        self.store=store;self.private=Path(private)
        key=serialization.load_pem_private_key(self.private.read_bytes(),password=None)
        if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 signing key required')

    def claim(self,lease_seconds=60):
        with self.store.db() as db:
            self.store.database.begin_write(db,'issuer-queue')
            now=self.store.database.clock(db)
            db.execute('INSERT INTO service_gate VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',('license-issuer:heartbeat',now))
            db.execute("UPDATE license_approvals SET state='cancelled',lease_token=NULL,lease_until=0,updated=? WHERE state IN ('queued','running') AND id IN ("
                       "SELECT a.id FROM license_approvals a JOIN license_orders o ON o.id=a.order_id JOIN users u ON u.id=a.requested_by JOIN users c ON c.id=o.user_id "
                       "WHERE u.role!='admin' OR u.disabled=1 OR c.disabled=1 OR o.status!='pending')",(now,))
            db.execute("UPDATE license_approvals SET state='failed',lease_token=NULL,error_code='lease_exhausted',updated=? WHERE state='running' AND lease_until<=? AND attempts>=3",(now,now))
            row=db.execute("SELECT * FROM license_approvals WHERE attempts<3 AND (state='queued' OR (state='running' AND lease_until<=?)) ORDER BY created,id LIMIT 1",(now,)).fetchone()
            if not row:return None
            token=str(uuid.uuid4())
            db.execute("UPDATE license_approvals SET state='running',lease_token=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",(token,now+lease_seconds,now,row['id']))
            return dict(row,lease_token=token)

    def once(self):
        job=self.claim()
        if not job:return False
        try:
            payload=json.loads(job['payload'])
            Billing(self.store).approve(job['order_id'],self.private,payload.get('account_id'),payload.get('equity_usd'),payload['payment_ref'],approval_job=job)
        except Exception:
            # No exception strings or key paths are persisted in the web-visible queue.
            with self.store.db() as db:
                self.store.database.begin_write(db,'issuer-queue')
                changed=db.execute("UPDATE license_approvals SET state='failed',lease_token=NULL,lease_until=0,error_code='issuance_failed',updated=? WHERE id=? AND state='running' AND lease_token=?",(time.time(),job['id'],job['lease_token']))
                if changed.rowcount:record(db,job['requested_by'],'issuance_failed',job['order_id'])
        return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-key',type=Path,required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    store=PortalStore(configured_target(),Path(os.environ['PORTAL_KEY_FILE']).read_bytes().strip())
    try:
        worker=Issuer(store,args.private_key)
        if args.once:worker.once();return
        stop=threading.Event()
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
        while not stop.is_set():
            if not worker.once():stop.wait(5)
    finally:store.close()


if __name__=='__main__':main()
