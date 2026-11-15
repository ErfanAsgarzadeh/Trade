"""Public forward-test (paper trading) summary built from the owner's paper runtime.

Read-only. It reads only: equity_history.jsonl (next to the main bot database; {"t","equity"} about hourly, the shared
paper account valued at market, open positions included), the main database `runtime.paper_initial_equity`, the closed
trade rows (main `trade_history.closed_at,pnl_usd,dry_run`, C3 and PA `trades.closed,pnl`) and nothing else. It never
reads symbols, prices, quantities, stops, targets or reasons. The result is daily and ends at the last fully completed
UTC day; account size is never published, only an index that starts at 100 and percentages.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time

from portal_audit import record, require_admin

DAY = 86400
CACHE_SECONDS = 300
MIN_DAYS = 7
HIDDEN_KEY = 'forward_test.hidden'
DEFAULT_DIR = '/app/owner-runtime'
# Public name per internal bot id. Internal ids and database layouts never leave this module.
BOTS = (('main', 'falcon', 'شاهین', 'Falcon', 'lbank_ichimoku_bot.db', 'trade_history', 'closed_at', 'pnl_usd'),
        ('c3', 'wave_rider', 'موج‌سوار', 'Wave Rider', 'c3_sleeve.db', 'trades', 'closed', 'pnl'),
        ('pa', 'phoenix', 'ققنوس', 'Phoenix', 'pa_sleeve.db', 'trades', 'closed', 'pnl'))
# The complete set of keys that may appear in the public JSON (tests assert this).
PUBLIC_KEYS = {'available', 'collecting', 'days', 'start_date', 'data_through', 'computed_at', 'paper', 'equity_basis',
               'start_index', 'current_index', 'total_return_pct', 'max_drawdown_pct', 'trades', 'win_rate_pct',
               'profit_factor', 'best_day_pct', 'worst_day_pct', 'series', 'monthly', 'bots'}
BOT_KEYS = {'id', 'name_fa', 'name_en', 'trades', 'win_rate_pct', 'contribution_pct'}


def configured_directory(directory=None):
    """The runtime directory, or None when the feature is not configured or the directory does not exist."""
    value = directory if directory is not None else os.getenv('PORTAL_FORWARD_TEST_DIR')
    if value is None or value == '':
        value = DEFAULT_DIR
    path = Path(value)
    return path if path.is_dir() else None


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _db_paths(root):
    try:
        data = json.loads((root / 'portal_runtime.json').read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    base = root.resolve()
    for code in ('main', 'c3', 'pa'):
        rel = data.get(code) if isinstance(data, dict) else None
        if isinstance(rel, str) and rel and not Path(rel).is_absolute():
            path = (base / rel).resolve()
            if base in path.parents:
                out[code] = path
    return out


def _connect(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.execute('PRAGMA query_only=ON')
    return db


def read_inputs(root):
    """(equity records [(t, equity)], initial equity or None, {bot: [(closed_at, pnl)]}, newest file mtime or None)."""
    mapped = _db_paths(root)
    paths = {code: mapped.get(code, root / default) for code, _, _, _, default, *_ in BOTS}
    modified = []
    records = []
    history = paths['main'].parent / 'equity_history.jsonl'
    try:
        with open(history, 'r', encoding='utf-8', errors='ignore') as handle:
            for line in handle.read().splitlines():
                try:
                    row = json.loads(line)
                    t, equity = _finite(row['t']), _finite(row['equity'])
                except (ValueError, KeyError, TypeError):
                    continue  # a half-written last line, or noise
                if t is not None and equity is not None and t > 0 and equity > 0:
                    records.append((t, equity))
        modified.append(history.stat().st_mtime)
    except OSError:
        pass
    records.sort()
    initial = None
    trades = {}
    for code, _, _, _, _, table, time_column, pnl_column in BOTS:
        trades[code] = []
        path = paths[code]
        if not path.is_file():
            continue
        try:
            db = _connect(path)
            try:
                modified.append(path.stat().st_mtime)
                if code == 'main':
                    row = db.execute("SELECT value FROM runtime WHERE key='paper_initial_equity'").fetchone()
                    number = _finite(row[0]) if row else None
                    initial = number if number and number > 0 else None
                    columns = {r[1] for r in db.execute('PRAGMA table_info(trade_history)')}
                    where = ' WHERE dry_run=1' if 'dry_run' in columns else ''
                else:
                    where = ''
                for closed, pnl in db.execute(f'SELECT {time_column},{pnl_column} FROM {table}{where}'):
                    closed, pnl = _finite(closed), _finite(pnl)
                    if closed is not None and pnl is not None and closed > 0:
                        trades[code].append((closed, pnl))
            finally:
                db.close()
        except (OSError, sqlite3.Error, ValueError):
            continue  # being written or not created yet: this bot simply has no rows now
    return records, initial, trades, (max(modified) if modified else None)


def _day(ts):
    return int(ts // DAY)


def _iso_day(day):
    return datetime.fromtimestamp(day * DAY, timezone.utc).date().isoformat()


def compute(root, now):
    """The public summary dict, or None when the runtime holds no usable data yet."""
    records, initial, trades, modified = read_inputs(root)
    today = _day(now)
    last_day = today - 1  # the last fully completed UTC day
    records = [r for r in records if _day(r[0]) <= last_day]
    first_trade = min((c for rows in trades.values() for c, _ in rows), default=None)
    if records:
        basis, base_time, base_equity = 'mark_to_market', records[0][0], records[0][1]
        start_day = _day(base_time)
    elif initial and first_trade is not None:
        basis, base_equity = 'realized', initial
        start_day = _day(first_trade)
        base_time = start_day * DAY
    else:
        return None
    if start_day > last_day:
        return dict(collecting=True, days=0, start_date=_iso_day(start_day), computed_at=now)
    days = last_day - start_day + 1
    # Closed trades since the base moment and before today; per-bot realised P&L as a share of the starting equity.
    window = {code: [(c, p) for c, p in rows if base_time <= c < today * DAY] for code, rows in trades.items()}
    series = []
    if basis == 'mark_to_market':
        index, pointer, level = 0, 0, base_equity
        for day in range(start_day, last_day + 1):
            while pointer < len(records) and _day(records[pointer][0]) <= day:
                level = records[pointer][1]
                pointer += 1
            series.append((day, level / base_equity * 100))
    else:
        cumulative = {}
        for rows in window.values():
            for c, p in rows:
                cumulative[_day(c)] = cumulative.get(_day(c), 0.0) + p
        total = 0.0
        for day in range(start_day, last_day + 1):
            total += cumulative.get(day, 0.0)
            series.append((day, (base_equity + total) / base_equity * 100))
    values = [100.0] + [v for _, v in series]
    peak, drawdown = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = min(drawdown, (v / peak - 1) * 100)
    daily = [values[i] / values[i - 1] * 100 - 100 for i in range(1, len(values)) if values[i - 1] > 0]
    pnls = [p for rows in window.values() for _, p in rows]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    month_end = {}
    for day, value in series:
        month_end[_iso_day(day)[:7]] = value
    monthly, previous = [], 100.0
    for month, value in month_end.items():
        monthly.append(dict(m=month, r=round((value / previous - 1) * 100, 2)))
        previous = value
    bots = []
    for code, key, fa, en, *_ in BOTS:
        rows = window[code]
        count = len(rows)
        bots.append(dict(id=key, name_fa=fa, name_en=en, trades=count,
                         win_rate_pct=round(sum(1 for _, p in rows if p > 0) / count * 100, 1) if count else None,
                         contribution_pct=round(sum(p for _, p in rows) / base_equity * 100, 2)))
    return dict(available=True, collecting=days < MIN_DAYS, days=days, start_date=_iso_day(start_day),
                data_through=_iso_day(last_day), computed_at=now, paper=True, equity_basis=basis, start_index=100,
                current_index=round(values[-1], 2), total_return_pct=round(values[-1] - 100, 2),
                max_drawdown_pct=round(drawdown, 2), trades=len(pnls),
                win_rate_pct=round(len(wins) / len(pnls) * 100, 1) if pnls else None,
                profit_factor=round(sum(wins) / -sum(losses), 2) if losses and wins else None,
                best_day_pct=round(max(daily), 2) if daily else None, worst_day_pct=round(min(daily), 2) if daily else None,
                series=[dict(d=_iso_day(d), v=round(v, 2)) for d, v in series], monthly=monthly, bots=bots)


def public(summary):
    """Only allow-listed keys; the collecting state carries no statistics at all."""
    if not summary:
        return dict(available=False)
    if summary.get('collecting'):
        return dict(available=False, collecting=True, days=summary.get('days', 0), start_date=summary.get('start_date'))
    out = {k: v for k, v in summary.items() if k in PUBLIC_KEYS}
    out['computed_at'] = datetime.fromtimestamp(summary['computed_at'], timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    out['bots'] = [{k: v for k, v in b.items() if k in BOT_KEYS} for b in summary['bots']]
    return out


class ForwardTest:
    """Cached public summary, the hide switch and the daily snapshot. Needs the portal store, never the vault key."""

    def __init__(self, store, directory=None, clock=time.time):
        self.store, self.directory, self.clock = store, directory, clock
        self.lock = threading.Lock()
        self.cached = None  # (expires, key, summary)

    def hidden(self):
        try:
            with self.store.db() as db:
                row = db.execute('SELECT value FROM site_settings WHERE name=?', (HIDDEN_KEY,)).fetchone()
            return bool(row and row['value'] == '1')
        except Exception:
            return False

    def set_hidden(self, actor, hidden):
        """Administrator switch (the route already requires admin_mutation); audited."""
        now = self.clock()
        with self.store.db() as db:
            self.store.database.begin_write(db, 'forward-test-switch')
            require_admin(db, actor)
            db.execute('INSERT INTO site_settings(name,value,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET '
                       'value=excluded.value,updated=excluded.updated', (HIDDEN_KEY, '1' if hidden else '0', now))
            record(db, actor, 'forward_test.hide' if hidden else 'forward_test.show', 'forward_test', {'hidden': bool(hidden)})
        self.cached = None

    def _summary(self):
        root = configured_directory(self.directory)
        now = self.clock()
        key = str(root)
        with self.lock:
            if self.cached and self.cached[0] > now and self.cached[1] == key:
                return self.cached[2]
        summary = None
        if root is not None:
            try:
                summary = compute(root, now)
            except Exception:
                summary = None
        if summary and summary.get('available') and not summary.get('collecting'):
            self._snapshot(summary)
        elif root is not None:
            summary = self._last_snapshot() or summary
        with self.lock:
            self.cached = (now + CACHE_SECONDS, key, summary)
        return summary

    def _snapshot(self, summary):
        """One row per completed UTC day with the public summary, so history survives rotated runtime files."""
        payload = {k: v for k, v in public(summary).items()}
        try:
            with self.store.db() as db:
                db.execute('INSERT INTO forward_snapshots(day,payload,created) VALUES(?,?,?) ON CONFLICT(day) DO NOTHING',
                           (summary['data_through'], json.dumps(payload, ensure_ascii=False), self.clock()))
        except Exception:
            pass

    def _last_snapshot(self):
        try:
            with self.store.db() as db:
                row = db.execute('SELECT payload FROM forward_snapshots ORDER BY day DESC LIMIT 1').fetchone()
            data = json.loads(row['payload']) if row else None
        except Exception:
            return None
        if not isinstance(data, dict) or not data.get('available'):
            return None
        data['from_snapshot'] = True
        return data

    def summary(self):
        """The public JSON: {available:false} when hidden, unconfigured or still collecting."""
        if self.hidden():
            return dict(available=False)
        summary = self._summary()
        if summary and summary.get('from_snapshot'):  # already in public form; only allow-listed keys were stored
            return {k: v for k, v in summary.items() if k in PUBLIC_KEYS}
        return public(summary)

    def admin_status(self):
        root = configured_directory(self.directory)
        status = dict(directory_found=root is not None, hidden=self.hidden(), runtime_updated=None, days=0,
                      last_snapshot=None, available=False)
        if root is not None:
            try:
                records, initial, trades, modified = read_inputs(root)
                status['runtime_updated'] = (datetime.fromtimestamp(modified, timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
                                             if modified else None)
                status['equity_records'] = len(records)
            except Exception:
                pass
            summary = self._summary()
            if summary:
                status['days'] = summary.get('days', 0)
                status['available'] = bool(summary.get('available'))
        try:
            with self.store.db() as db:
                row = db.execute('SELECT MAX(day) AS day FROM forward_snapshots').fetchone()
            status['last_snapshot'] = row['day'] if row else None
        except Exception:
            pass
        return status
