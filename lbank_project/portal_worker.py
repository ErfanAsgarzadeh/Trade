"""Separate process for read-only exchange sync. This is not a live order executor."""
import os
from pathlib import Path
import signal
import threading

import ccxt
from cryptography.fernet import InvalidToken
from portal_database import configured_target
from portal_jobs import AccountQueue
from portal_lbank import FuturesNotValidated
from portal_exchanges import MultiExchangeReader,UnsupportedAccount,PROFILES
import json
import math
from portal_store import PortalStore


class AccountWorker:
    def __init__(self,store,reader=None,lease_seconds=60,interval=.25,intervals=None):
        self.store=store;self.reader=reader or MultiExchangeReader();self.queue=AccountQueue(store)
        self.lease_seconds=lease_seconds;self.interval=interval
        self.intervals=intervals

    def once(self):
        job=self.queue.claim(self.lease_seconds,self.interval,self.intervals)
        if not job:return False
        try:
            connection=self.store.connection(job['user_id'],decrypt=True)
        except (InvalidToken,ValueError,KeyError):
            self.queue.finish(job,None,'verification_failed')
            return True
        if not connection or connection['revision']!=job['revision']:return True
        snapshot=None;status='verified_read_only';retry=False
        try:snapshot=self.reader.snapshot(connection)
        except FuturesNotValidated:status='futures_not_validated'
        except UnsupportedAccount:status='capability_unavailable'
        except (ccxt.NetworkError,ccxt.RateLimitExceeded):status='verification_failed';retry=True
        except Exception:status='verification_failed'
        # Database failures propagate to the process retry loop. They are not exchange/auth failures.
        self.queue.finish(job,snapshot,status,retry=retry)
        return True


def main():
    interval=float(os.getenv('PORTAL_EXCHANGE_READ_INTERVAL',os.getenv('PORTAL_LBANK_READ_INTERVAL','0.25')))
    intervals=json.loads(os.getenv('PORTAL_EXCHANGE_READ_INTERVALS') or '{}')
    if (not math.isfinite(interval) or not .01<=interval<=60 or not isinstance(intervals,dict)
        or any(k not in PROFILES or type(v) not in (int,float) or not math.isfinite(v) or not .01<=v<=60 for k,v in intervals.items())):
        raise ValueError('Read intervals must be finite .01..60 seconds for enabled exchange IDs')
    key=Path(os.environ['PORTAL_KEY_FILE']).read_bytes().strip()
    store=PortalStore(configured_target(),key)
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    worker=AccountWorker(store,interval=interval,intervals=intervals)
    try:
        while not stop.is_set():
            try:worked=worker.once()
            except Exception:
                print('Account worker could not reach durable state; retrying.',flush=True)
                stop.wait(1);continue
            if not worked:stop.wait(.25)
    finally:store.close()


if __name__=='__main__':main()
