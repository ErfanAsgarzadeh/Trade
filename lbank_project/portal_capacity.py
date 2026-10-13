"""Synthetic capacity probe: disposable SQLite only, no exchange requests or orders."""
import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time
import uuid

from cryptography.fernet import Fernet
import httpx

from portal_server import create_app
from portal_store import PortalStore
from portal_worker import AccountWorker
from portal_jobs import AccountQueue
from portal_exchanges import PROFILES


def percentile(values,p):return sorted(values)[min(len(values)-1,int((len(values)-1)*p))]


async def probe(users,requests,concurrency,drain,mix_exchanges=False,mix_markets=False,workers=1):
    with tempfile.TemporaryDirectory(prefix='trade-portal-capacity-') as directory:
        store=PortalStore(Path(directory)/'synthetic.db',Fernet.generate_key())
        clients=[];now=time.time();distribution=Counter()
        venues=list(PROFILES) if mix_exchanges else ['lbank']
        with store.db() as db:
            for i in range(users):
                owner=str(uuid.uuid4());token=secrets.token_urlsafe(32);revision=str(uuid.uuid4())
                venue=venues[i%len(venues)]
                market='futures' if mix_markets and i%2 and 'futures' in PROFILES[venue] else 'spot'
                clients.append((owner,token,i,venue,market));distribution[venue+':'+market]+=1
                db.execute('INSERT INTO users VALUES(?,?,?,0,NULL)',(owner,'tenant-'+str(i),store.dummy_password))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,'synthetic-csrf',now+86400))
                encrypted=store.vault.encrypt(json.dumps(dict(owner=owner,exchange_id=venue,market=market,api_key='synthetic-'+str(i),secret='synthetic-not-a-real-key',passphrase='synthetic-passphrase')).encode())
                db.execute('INSERT INTO connections(user_id,encrypted,market,revision,updated,exchange_id) VALUES(?,?,?,?,?,?)',(owner,encrypted,market,revision,now,venue))
                db.execute("INSERT INTO account_cache VALUES(?,?,NULL,0,'queued')",(owner,revision))
                db.execute("INSERT INTO account_jobs VALUES(?,?,'queued',NULL,0,?,0,?)",(owner,revision,now,now))
        class SyntheticReader:
            def snapshot(self,connection):
                # It is impossible for this adapter to contact the exchange.
                i=int(connection['api_key'].removeprefix('synthetic-'))
                return dict(exchange_id=connection['exchange_id'],market=connection['market'],balances=[dict(asset='USDT',free=i,locked=0,total=i)])
        def worker_batch(count):
            worker=AccountWorker(store,SyntheticReader(),interval=0)
            return sum(worker.once() for _ in range(count))
        start=time.perf_counter()
        # SQLite has one writer. Multiple workers are an explicit contention diagnostic,
        # not the deployment profile for this development-only database.
        counts=[drain//workers+(i<drain%workers) for i in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as pool:completed=sum(pool.map(worker_batch,counts))
        worker_seconds=time.perf_counter()-start
        app=create_app(store,origin='https://portal.test',secure=True)
        latencies=[];codes=Counter();leaks=0;verified_reads=0
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://portal.test') as client:
                semaphore=asyncio.Semaphore(concurrency)
                async def read(i):
                    nonlocal leaks,verified_reads
                    # Spread samples across all 10k tenants, rather than only the first accounts.
                    index=(i*7919)%users;_,token,expected,venue,market=clients[index]
                    async with semaphore:
                        stamp=time.perf_counter()
                        response=await client.get('/api/me/connection',headers={'Cookie':'trade_session='+token})
                        latencies.append((time.perf_counter()-stamp)*1000);codes[response.status_code]+=1
                        if response.status_code==200:
                            view=response.json();snap=view['account']['snapshot']
                            if view['exchange_id']!=venue or view['market']!=market:leaks+=1
                            if snap:
                                verified_reads+=1
                                if snap['balances'][0]['free']!=expected or snap['exchange_id']!=venue or snap['market']!=market:leaks+=1
                start=time.perf_counter()
                await asyncio.gather(*(read(i) for i in range(requests)))
                http_seconds=time.perf_counter()-start
        summary=AccountQueue(store).summary();done=summary['states'].get('done',0);failed=summary['states'].get('failed',0)
        result=dict(profile='synthetic SQLite / in-process ASGI; NOT live trading or production capacity certification',
                    users=users,queued_jobs_initial=users,workers=workers,synthetic_jobs_claimed=completed,
                    synthetic_jobs_completed=done,synthetic_jobs_failed=failed,
                    worker_seconds=round(worker_seconds,3),worker_jobs_per_second=round(completed/worker_seconds,2),
                    http_requests=requests,http_concurrency=concurrency,http_seconds=round(http_seconds,3),
                    http_requests_per_second=round(requests/http_seconds,2),
                    latency_ms=dict(p50=round(percentile(latencies,.5),2),p95=round(percentile(latencies,.95),2),p99=round(percentile(latencies,.99),2)),
                    http_status_codes=dict(codes),verified_account_reads=verified_reads,owner_mismatches=leaks,
                    queue_remaining=summary,exchange_requests=0,live_orders=0)
        result['connections_by_exchange_and_market']=dict(distribution)
        store.close()
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users',type=int,default=10000);parser.add_argument('--requests',type=int,default=2000)
    parser.add_argument('--concurrency',type=int,default=40);parser.add_argument('--drain',type=int,default=1000)
    parser.add_argument('--workers',type=int,default=1,help='SQLite local profile: 1; higher values diagnose write contention')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mix-exchanges',action='store_true');parser.add_argument('--mix-markets',action='store_true')
    args=parser.parse_args()
    if not 1<=args.users<=100000 or not 1<=args.requests<=100000 or not 1<=args.concurrency<=200 or not 1<=args.drain<=args.users or not 1<=args.workers<=64:
        parser.error('Invalid capacity profile')
    if args.output.exists():parser.error('Output already exists; choose a new file')
    result=asyncio.run(probe(args.users,args.requests,args.concurrency,args.drain,args.mix_exchanges,args.mix_markets,args.workers))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps(result,indent=2))
    if (result['owner_mismatches'] or result['http_status_codes'].get(200,0)!=args.requests
        or result['synthetic_jobs_failed'] or result['synthetic_jobs_completed']!=args.drain):raise SystemExit(1)


if __name__=='__main__':main()
