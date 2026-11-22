"""Real HTTP service sampled against a fresh PostgreSQL database of synthetic portal identities."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import uuid

import httpx
import psycopg
import uvicorn
from cryptography.fernet import Fernet
from psycopg import sql

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from portal_server import create_app
from portal_store import PortalStore

TOTAL = 1_000_000
REQUESTS = 2048
CONCURRENCY = 32


async def sample(port, salt):
    latencies = []
    codes = Counter()
    mismatches = 0
    jobs = iter(range(REQUESTS))
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=60, trust_env=False) as client:
        async def worker():
            nonlocal mismatches
            for i in jobs:
                owner = (i * 7919) % TOTAL + 1
                start = time.monotonic()
                response = await client.get('/api/me', headers={'Cookie': f'trade_session={salt}-{owner}'})
                latencies.append(1000 * (time.monotonic() - start))
                codes[response.status_code] += 1
                if response.status_code == 200 and response.json()['username'] != f'tenant-{owner}':
                    mismatches += 1
        start = time.monotonic()
        await asyncio.gather(*(worker() for _ in range(CONCURRENCY)))
        elapsed = time.monotonic() - start
    latencies.sort()
    return dict(requests=REQUESTS, concurrency=CONCURRENCY, statuses=dict(codes), mismatches=mismatches,
                seconds=elapsed, rps=REQUESTS/elapsed, latency_ms={
                    str(p):latencies[math_index(p, len(latencies))] for p in (50,95,99)})


def math_index(p, n):
    return (p*n+99)//100-1


def run():
    server_dsn = os.environ['DISPOSABLE_PG_URL']
    name = 'avina_benchmark_' + uuid.uuid4().hex
    with psycopg.connect(server_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    # The admin URL designates the temporary container only. Always create a new database.
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(server_dsn)
    url = urlunsplit(parsed._replace(path='/' + name))
    store = PortalStore(url, Fernet.generate_key())
    salt = secrets.token_hex(32)
    try:
        with psycopg.connect(url) as seed:
            seed.execute("""INSERT INTO users(id,username,password)
                         SELECT i::text, 'tenant-'||i, %s FROM generate_series(1,%s) AS i""",
                         (store.dummy_password,TOTAL))
            seed.execute("""INSERT INTO sessions(token_hash,user_id,csrf,expires)
                         SELECT encode(sha256(convert_to(%s||'-'||i,'UTF8')),'hex'), i::text,
                                'fixture', extract(epoch from now())+86400
                         FROM generate_series(1,%s) AS i""", (salt,TOTAL))
            seed.execute('ANALYZE users')
            seed.execute('ANALYZE sessions')
            accounts = seed.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            sessions = seed.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
            storage = seed.execute('SELECT pg_database_size(current_database())').fetchone()[0]
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port = sock.getsockname()[1]
            origin = f'http://127.0.0.1:{port}'
            app = create_app(store,origin=origin,secure=False)
            server = uvicorn.Server(uvicorn.Config(app,access_log=False,log_level='warning'))
            thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]})
            thread.start()
            try:
                deadline = time.monotonic()+45
                while not server.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError('Local portal failed to start')
                    time.sleep(.05)
                results = asyncio.run(sample(port, salt))
            finally:
                server.should_exit = True
                thread.join()
        results.update(users=accounts, sessions=sessions, postgres_bytes=storage, path='/api/me')
        print(json.dumps(results),flush=True)
        Path('/results/portal-million.json').write_text(json.dumps(results,indent=2))
        if accounts != TOTAL or sessions != TOTAL or results['statuses'] != {200:REQUESTS} or results['mismatches']:
            raise RuntimeError('Population or HTTP verification failed')
    finally:
        store.close()
        with psycopg.connect(server_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__ == '__main__':
    run()
