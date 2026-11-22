"""Offline, post-signal paper execution benchmark. Requires a Linux cgroup-v2 container."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import csv
import json
import math
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import lbank_bot as bot

BAR = SimpleNamespace(close=100.0, high=102.0, low=98.0, kijun=100.0,
                      atr=1.0, timestamp=1_800_000_000_000)
SYMBOL = 'BTC/USDT:USDT'
BATCH = 256
CGROUP = Path('/sys/fs/cgroup')


class FixedMarket:
    def market(self, symbol):
        return {'contractSize': 1.0}

    def precision(self, symbol, quantity):
        return math.floor(quantity * 1_000_000) / 1_000_000

    def tradable(self, symbol, quantity, price):
        return quantity >= 0.001 and price > 0


class Settings:
    def __init__(self):
        self.value = bot.validate_config(json.loads((PROJECT / 'config.json').read_text()))
        self.value['portfolio_risk']['shared_c3_account'] = False
        self.value['strategy_settings']['momentum_sizing_enabled'] = False

    def read(self):
        return self.value


class ReplayDatabase(bot.Database):
    """Reuse one single-account SQL workspace per worker, committing the archive in batches."""
    def __init__(self, path):
        schema = bot.Database(path)
        self.path, self.trade_lock = schema.path, schema.trade_lock
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def connect(self):
        yield self.connection


def balance(owner):
    return (100_000 + owner * 3) / 100


def open_position(engine, equity, side):
    pos = bot.size_position(engine.data, SYMBOL, side, BAR, equity, engine.config.read(), '4h')
    if pos is None:
        raise RuntimeError('Eligible test position rejected at sizing')
    engine._insert(pos)
    if not engine._activate(pos, BAR.close, BAR.timestamp / 1000 + 3):
        raise RuntimeError('Pending test position was not activated')
    row = engine.db.position(SYMBOL)
    validate_fill(row, equity, side)
    return row


def validate_fill(row, equity, side):
    # Independent oracle for this market: two ATR stop, 1% risk, fee and slip on notional.
    expected = math.floor(equity * 0.01 / (2 + 100 * (0.0012 + 0.0004)) * 1e6) / 1e6
    if not (row and row['dry_run'] == 1 and row['state'] == bot.TRAILING and row['side'] == side
            and row['entry_price'] == 100 and row['active_sl'] == (98 if side == 'long' else 102)
            and math.isclose(row['risk_budget'], equity * 0.01, rel_tol=1e-12)
            and abs(row['qty'] - expected) <= 0.0000011):
        raise AssertionError('Owner balance, quantity, side, stop or state mismatch')


def shard(directory, total, worker, workers):
    settings = Settings()
    database = ReplayDatabase(directory / f'shard-{worker}.db')
    sql = database.connection
    sql.executescript("""
        CREATE TABLE accounts(owner INTEGER PRIMARY KEY, equity REAL NOT NULL, side TEXT NOT NULL);
        CREATE TABLE opened(owner INTEGER PRIMARY KEY REFERENCES accounts, side TEXT NOT NULL,
            entry_price REAL NOT NULL, qty REAL NOT NULL, active_sl REAL NOT NULL,
            state TEXT NOT NULL, risk_budget REAL NOT NULL, dry_run INTEGER NOT NULL);
    """)
    owners = range(worker + 1, total + 1, workers)
    with sql:
        sql.executemany('INSERT INTO accounts VALUES(?,?,?)',
                        ((i, balance(i), 'long' if i % 2 else 'short') for i in owners))
    engine = bot.Engine(settings, database, FixedMarket(), paper_equity=balance(owners.start))
    for start in range(0, len(owners), BATCH):
        with sql:
            for account in sql.execute('SELECT * FROM accounts WHERE owner>=? ORDER BY owner LIMIT ?',
                                       (owners[start], BATCH)):
                engine.paper_seed = account['equity']
                pos = open_position(engine, account['equity'], account['side'])
                sql.execute('INSERT INTO opened VALUES(?,?,?,?,?,?,?,?)',
                            (account['owner'], pos['side'], pos['entry_price'], pos['qty'],
                             pos['active_sl'], pos['state'], pos['risk_budget'], pos['dry_run']))
                sql.execute('DELETE FROM positions')
                sql.execute('DELETE FROM scanned_candles')
    sql.close()
    # Reopen after commit and check ownership and sizing for every persisted row.
    readback = sqlite3.connect(database.path)
    readback.row_factory = sqlite3.Row
    count = 0
    for row in readback.execute('SELECT a.owner, a.equity, o.* FROM accounts a LEFT JOIN opened o USING(owner) ORDER BY a.owner'):
        owner = row['owner']
        if owner != owners[count] or row['equity'] != balance(owner):
            raise AssertionError('Wrong owner or starting balance')
        validate_fill(row, balance(owner), 'long' if owner % 2 else 'short')
        count += 1
    if count != len(owners) or readback.execute('SELECT count(*) FROM opened').fetchone()[0] != count:
        raise AssertionError('Incorrect persisted count')
    readback.close()
    return count


def separate_accounts(directory, total):
    settings = Settings()
    for owner in range(1, total + 1):
        path = directory / f'owner-{owner}.db'
        equity = balance(owner)
        side = 'long' if owner % 2 else 'short'
        engine = bot.Engine(settings, bot.Database(path), FixedMarket(), paper_equity=equity)
        open_position(engine, equity, side)
    for owner in range(1, total + 1):
        with sqlite3.connect(directory / f'owner-{owner}.db') as db:
            db.row_factory = sqlite3.Row
            validate_fill(db.execute('SELECT * FROM positions').fetchone(), balance(owner),
                          'long' if owner % 2 else 'short')
    return total


def block_counters(directory):
    device = directory.stat().st_dev
    path = Path('/sys/dev/block') / f'{os.major(device)}:{os.minor(device)}' / 'stat'
    if not path.exists():
        return None
    # Linux reports 512-byte sectors and milliseconds busy for the entire backing device.
    fields = list(map(int, path.read_text().split()))
    return fields[2] * 512, fields[6] * 512, fields[9]


def metrics(directory):
    cpu = dict(line.split() for line in (CGROUP / 'cpu.stat').read_text().splitlines())
    disk = sum(p.stat().st_size for p in directory.glob('*') if p.is_file() and p.exists())
    return (time.monotonic(), int(cpu['usage_usec']),
            int((CGROUP / 'memory.current').read_text()), disk, block_counters(directory))


def stage(root, report, total, workers, native):
    profile = 'separate-db' if native else 'batched-replay'
    key = f'{profile}-{total}'
    directory = root / key
    directory.mkdir()
    readings = [metrics(directory)]
    stopped = threading.Event()
    def sample():
        while not stopped.wait(0.2):
            try:
                readings.append(metrics(directory))
            except FileNotFoundError:
                pass  # SQLite may unlink a WAL between glob and stat.
    thread = threading.Thread(target=sample)
    thread.start()
    try:
        if native:
            opened = separate_accounts(directory, total)
        else:
            with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context('forkserver')) as pool:
                futures = [pool.submit(shard, directory, total, i, workers) for i in range(workers)]
                opened = sum(job.result() for job in futures)
    finally:
        stopped.set()
        thread.join()
    readings.append(metrics(directory))
    start, cpu_start, _, _, first_io = readings[0]
    end, cpu_end, _, _, last_io = readings[-1]
    elapsed = end - start
    with (report / f'{key}.csv').open('w', newline='') as out:
        writer = csv.writer(out)
        writer.writerow(('elapsed_s', 'cpu_seconds_since_start', 'container_memory_bytes', 'database_bytes',
                         'device_read_bytes', 'device_write_bytes', 'device_busy_ms'))
        for stamp, cpu, memory, disk, io in readings:
            counters = [v-base for v, base in zip(io, first_io)] if io and first_io else [None] * 3
            writer.writerow((stamp-start, (cpu-cpu_start)/1e6, memory, disk, *counters))
    result = dict(profile=profile, users=total, opened_verified=opened, workers=1 if native else workers,
                  elapsed_s=elapsed, verified_per_second=opened/elapsed,
                  mean_cpu_cores=(cpu_end-cpu_start)/1e6/elapsed,
                  peak_memory_mib=max(v[2] for v in readings)/2**20,
                  peak_db_mib=max(v[3] for v in readings)/2**20, samples=len(readings))
    if first_io and last_io:
        read, written, busy = [v-base for v, base in zip(last_io, first_io)]
        result.update(device_read_mib=read / 2**20, device_written_mib=written / 2**20,
                      device_busy_pct=busy / (10 * elapsed))
    if opened != total:
        raise AssertionError(result)
    checkpoint = report / f'{key}.json'
    tmp = checkpoint.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, indent=2))
    tmp.replace(checkpoint)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    args.report.mkdir(parents=True, exist_ok=True)
    for native, totals in ((True, (10, 100)), (False, (10, 100, 1000, 10000, 100000, 1000000))):
        for total in totals:
            key = f'{"separate-db" if native else "batched-replay"}-{total}'
            if (args.report/f'{key}.json').is_file():
                continue
            # A fresh attempt directory keeps interrupted data available for inspection.
            run = args.data / str(time.time_ns())
            run.mkdir()
            stage(run, args.report, total, min(4, total), native)


if __name__ == '__main__':
    main()
