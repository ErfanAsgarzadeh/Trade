"""Read public LBank Futures chart candles; never use spot or repair exchange data.

This is the public web-chart route observed in LBank's own shipped JavaScript,
not a documented/stable OpenAPI contract. No account credentials are sent.
"""
import csv
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request

H4 = 14400
URL = 'https://uuapi.lbank.com/cfd/query/v1.0/KLinelst'
SOURCE = 'lbank-futures-web-klines-v1'
HEADER = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
LOG = logging.getLogger('official-candles')


class ClosedCandles(list):
    """Explicit closed-only batch; consumers must not discard its last real bar."""
    closed_only = True


def instrument(symbol):
    if not re.fullmatch(r'[A-Z0-9]+/USDT:USDT', symbol):
        raise ValueError('Only explicit USDT perpetual symbols are supported')
    return symbol.split('/')[0] + 'USDT'


def fetch(symbol, now, count=1000):
    params = dict(instrumentID=instrument(symbol), exchangeID='Exchange',
                  startDatetime=int(now), count=count, type='4h', isUsd=1)
    request = urllib.request.Request(URL + '?' + urllib.parse.urlencode(params),
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.lbank.com/',
                 'source': '4', 'businessVersionCode': '202'})
    with urllib.request.urlopen(request, timeout=20) as response:
        # Prevent unexpectedly large/malformed replies consuming unbounded memory.
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Candle response too large')
    return json.loads(data)


def validate_rows(rows, now, minimum=999):
    if len(rows) < minimum:
        raise ValueError(f'Not enough closed candles: {len(rows)} < {minimum}')
    boundary = int(now) // H4 * H4 * 1000
    previous = None
    for row in rows:
        if len(row) != 6 or not all(math.isfinite(float(x)) for x in row):
            raise ValueError('Non-finite/invalid candle fields')
        ts, o, h, l, c, v = map(float, row)
        if ts % (H4 * 1000) or ts >= boundary:
            raise ValueError('Candle is unaligned, forming or in the future')
        if not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
            raise ValueError('Invalid OHLCV geometry; no automatic repair permitted')
        if previous is not None and ts - previous != H4 * 1000:
            raise ValueError('Duplicate, unsorted or gapped futures history')
        previous = ts
    if previous != boundary - H4 * 1000:
        raise ValueError('Latest closed candle is missing/stale')
    return rows


def parse(body, symbol, now):
    # Both envelopes have been used by the public chart service.
    if body.get('success') is True and body.get('status') == 0:
        raw = body.get('dataWrapper')
    elif body.get('code') == 200:
        raw = body.get('data')
    else:
        raise ValueError('LBank chart service did not return success')
    if not isinstance(raw, list) or len(raw) > 1001:
        raise ValueError('Unexpected candle payload')
    boundary = int(now) // H4 * H4
    rows = []
    for item in raw:
        r = {k[:1].lower() + k[1:]: v for k, v in item.items()}
        if (r.get('instrumentID') != instrument(symbol) or r.get('periodID') != '4h'
                or r.get('exchangeID') != 'Exchange'):
            raise ValueError('Unexpected instrument, period or exchange')
        ts = float(r['beginTime'])
        if not math.isfinite(ts) or ts > boundary or ts % H4:
            raise ValueError('Invalid/future exchange timestamp')
        if ts == boundary:
            continue  # Never use the forming candle, even when the API includes it.
        rows.append([int(ts * 1000)] + [float(r[k]) for k in
                     ('openPrice', 'highestPrice', 'lowestPrice', 'closePrice', 'volume')])
    return validate_rows(rows, now)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def paths(root, symbol):
    instrument(symbol)
    path = Path(root) / 'official' / (symbol.replace('/', '_').replace(':', '_') + '_4h.csv')
    return path, path.with_suffix('.source.json')


def publish(root, symbol, rows, now):
    validate_rows(rows, now)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(HEADER)
    writer.writerows(rows)
    data = output.getvalue().encode()
    path, receipt = paths(root, symbol)
    metadata = dict(source=SOURCE, endpoint=URL, symbol=symbol, period='4h',
                    closed_only=True, fetched_at=now, count=len(rows),
                    volume_unit='exchange_reported', sha256=hashlib.sha256(data).hexdigest())
    # A reader during the two renames sees a checksum mismatch and fails closed.
    atomic_write(path, data)
    atomic_write(receipt, json.dumps(metadata).encode())


def read_history(root, symbol, timeframe, limit, now):
    if timeframe != '4h' or not 2 <= limit <= 1000:
        raise ValueError('Official candle feed currently supports 4h, limit 2..1000')
    path, receipt = paths(root, symbol)
    metadata = json.loads(receipt.read_text())
    data = path.read_bytes()
    if (metadata.get('source') != SOURCE or metadata.get('endpoint') != URL
            or metadata.get('symbol') != symbol or metadata.get('period') != '4h'
            or metadata.get('closed_only') is not True
            or metadata.get('sha256') != hashlib.sha256(data).hexdigest()):
        raise ValueError('Official candle provenance/checksum mismatch')
    age = now - float(metadata['fetched_at'])
    if not 0 <= age <= 600:
        raise ValueError('Official candle refresh is stale/future dated')
    reader = csv.reader(io.StringIO(data.decode()))
    if next(reader, None) != HEADER:
        raise ValueError('Invalid official CSV header')
    rows = [[float(x) for x in row] for row in reader]
    validate_rows(rows, now)
    # Match the previous window size: `limit` formerly included one forming bar.
    return ClosedCandles(rows[-(limit - 1):])


def sync(symbols, root):
    def one(symbol):
        try:
            requested = time.time()
            rows = parse(fetch(symbol, requested), symbol, requested)
            # Re-check the boundary at publication, including a slow boundary-crossing fetch.
            publish(root, symbol, rows, time.time())
            LOG.info('%s: official Futures candles ready (%d closed)', symbol, len(rows))
            return True
        except Exception as exc:
            LOG.error('%s: official history unavailable (%s); old files not replaced', symbol, exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(one, symbols))
    LOG.info('Official Futures history: %d/%d symbols ready', sum(results), len(symbols))
    return all(results)


def run(symbols, root, once=False):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        success = sync(symbols, root)
        if once:
            return 0 if success else 1
        stop.wait(60)
    return 0
