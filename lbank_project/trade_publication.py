"""Private, read-only evidence for operator-created trade publication cards.

No database constructors/migrations, exchange orders, public URLs, or persistent credentials.
A closed row is an exit execution, potentially a partial exit, not an inferred round trip.
"""
from __future__ import annotations
from collections import OrderedDict
import copy
import csv
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

NAMES = {'main': 'Shahin', 'c3': 'Wave Rider', 'pa': 'Phoenix'}
BASE = Path(__file__).resolve().parent


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def read_rows(path, table):
    # table is a constant supplied by this module, never request input.
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        return [dict(r) for r in connection.execute('SELECT * FROM ' + table)]
    finally:
        connection.close()


def read_paper_tables(path, history_table):
    """One SQLite read transaction prevents a close being both open and realized.

    Tables are internal constants. Cross-bot snapshots are sampled sequentially.
    """
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        positions = [dict(r) for r in connection.execute('SELECT * FROM positions')]
        trades = [dict(r) for r in connection.execute('SELECT * FROM ' + history_table)]
        return positions, trades
    finally:
        connection.close()


def price_move(entry, price, side):
    entry, price = finite(entry), finite(price)
    if entry is None or entry <= 0 or price is None or price <= 0 or side not in ('long', 'short'):
        return None
    return (price / entry - 1) * (1 if side == 'long' else -1) * 100


def record(bot, kind, raw):
    main = bot == 'main'
    entry = finite(raw.get('entry_price' if main else 'entry'))
    closed = finite(raw.get('closed_at' if main else 'closed')) if kind == 'closed' else None
    opened = finite(raw.get('opened'))  # main history does not retain entry execution timestamps
    return dict(id=f"{bot}:{kind}:{raw['id'] if kind == 'closed' else raw['symbol']}",
                mode='paper', bot=bot, strategy=NAMES[bot], symbol=raw['symbol'], side=raw['side'],
                status=kind, entry=entry, exit=finite(raw.get('exit_price' if main else 'exit')),
                opened_at=opened, closed_at=closed, stop=finite(raw.get('active_sl' if main else 'stop')),
                target=finite(raw.get('hard_tp_price') or raw.get('tp1_price')),
                timeframe=raw.get('timeframe', '4h'), pnl_usd=finite(raw.get('pnl_usd' if main else 'pnl')),
                pnl_basis='net modeled costs' if kind == 'closed' else 'unrealized, modeled exit costs',
                reason=str(raw.get('reason', '')), price_move_pct=None)


def paper_snapshot(engine):
    """Read all three stores independently. Missing stores make account totals unknown."""
    from lbank_bot import PENDING, net_pnl
    source_started_at = time.time()
    warnings, records = [], []
    seed = finite(engine.paper_seed)
    realized, floating = 0., 0.
    complete = bool(engine.config.read()['portfolio_risk']['shared_c3_account'])
    if not complete:
        warnings.append('Shared paper account is disabled; combined account return is unavailable.')
    sources = [('main', Path(engine.db.path))]
    for bot, prefix in [('c3', 'C3'), ('pa', 'PA')]:
        sources.append((bot, Path(os.getenv(prefix + '_DB', str(BASE / 'data' / (bot + '_sleeve.db'))))))
    for bot, path in sources:
        try:
            positions, trades = read_paper_tables(path, 'trade_history' if bot == 'main' else 'trades')
        except (sqlite3.Error, OSError, ValueError):
            warnings.append(f'{NAMES[bot]} database unavailable; account totals withheld.')
            complete = False
            continue
        for raw in trades:
            if bot == 'main' and raw.get('dry_run') != 1:
                continue  # never relabel a real row as paper
            r = record(bot, 'closed', raw)
            r['price_move_pct'] = price_move(r['entry'], r['exit'], r['side'])
            if r['pnl_usd'] is None:
                complete = False
            else:
                realized += r['pnl_usd']
            records.append(r)
        for raw in positions:
            if bot == 'main' and (raw.get('state') == PENDING or raw.get('dry_run') != 1):
                continue
            r = record(bot, 'open', raw)
            try:
                quote_started_at = time.time()
                price = finite(engine.data.price(r['symbol'], cached=True))
                if price is None or price <= 0:
                    raise ValueError('price unavailable')
                if bot == 'main':
                    pnl = finite(net_pnl(raw, price, raw['qty']))
                else:
                    config_path = Path(os.getenv(bot.upper() + '_CONFIG', str(BASE / (bot + '_config.json'))))
                    config = json.loads(config_path.read_text())
                    fee = float(config['round_trip_fee']) / 2
                    pnl = finite((1 if r['side'] == 'long' else -1) * (price - raw['entry']) * raw['qty']
                                 - (price + raw['entry']) * raw['qty'] * fee)
                r.update(current_price=price, pnl_usd=pnl, price_move_pct=price_move(r['entry'], price, r['side']),
                         valuation_at=time.time(), quote_time_basis='Ticker may be cached for up to 5 seconds; exchange tick time is unavailable.')
                if pnl is None:
                    complete = False
                else:
                    floating += pnl
            except Exception:
                complete = False
                warnings.append(f"{NAMES[bot]} {r['symbol']}: current valuation unavailable.")
            records.append(r)
    equity = seed + realized + floating if complete and seed is not None and seed > 0 else None
    account = dict(equity_usd=equity, pnl_usd=equity-seed if equity is not None else None,
                   return_pct=(equity/seed-1)*100 if equity is not None else None,
                   basis='Current whole paper account, including floating P&L; not equity at trade exit.',
                   as_of=time.time())
    mode = getattr(engine.data, 'mode', 'unknown')
    return dict(records=sorted(records, key=lambda r: r['closed_at'] or float('inf'), reverse=True),
                account=account, warnings=warnings, data_mode=mode,
                publishable=mode == 'csv-lbank', generated_at=time.time(), source_started_at=source_started_at,
                notice='Each closed card is one recorded exit; partial exits are not grouped into a complete trade.')


def real_snapshot():
    """Fresh GET-only TTT reads. Never infer realized P&L from mirror events or paper fills."""
    from portal_thetruetrade import CustomerReader
    import live_mirror
    source_started_at = time.time()
    cfg = live_mirror.read_config()
    empty = dict(records=[], account=dict(equity_usd=None, pnl_usd=None, return_pct=None,
                 basis='Real account return needs an audited starting balance and cash-flow history.', as_of=time.time()),
                 warnings=[], data_mode='thetruetrade-account-api', publishable=False, generated_at=time.time(), source_started_at=source_started_at)
    empty['notice'] = ('Real closed-trade history and net P&L are not recorded by this mirror version. '
                       'Only current exchange positions are listed. No paper values are substituted.')
    if cfg['mode'] != 'live' or cfg['exchange'] != 'thetruetrade':
        empty['warnings'] = ['Real TheTrueTrade source is not configured in live mode.']
        return empty
    try:
        reader = CustomerReader(os.environ.get('TTT_API_KEY', ''), os.environ.get('TTT_API_SECRET', ''))
        # CustomerReader permits only assets and active positions GETs, with a fixed host and no redirects.
        # Reuse the same GET response for validation, optional quoted fields and legacy
        # equity fallback. No second position read can introduce a mixed snapshot.
        raw_method = getattr(reader, '_raw_positions', None)
        raw_positions = raw_method() if callable(raw_method) else None
        if raw_positions is not None:
            reader._raw_positions = lambda: raw_positions
        positions = reader.positions()
        equity = finite(reader.equity())
        if equity is None or equity < 0:
            raise ValueError('invalid equity')
        empty['account']['equity_usd'] = equity
        for symbol, pos in positions.items():
            source_rows = [p for p in (raw_positions or []) if p.get('symbol') == symbol]
            marks = [finite(p.get('markPrice')) for p in source_rows]
            # An aggregated symbol may contain several fills. Use a mark only if
            # every constituent reports the same positive mark, never its fill price.
            mark = (marks[0] if marks and all(v is not None and v > 0 and
                    math.isclose(v, marks[0], rel_tol=1e-9) for v in marks) else None)
            pnls = [finite(p.get('unrealizedPnL')) for p in source_rows]
            pnl = sum(pnls) if pnls and all(v is not None for v in pnls) else None
            empty['records'].append(dict(id='real:open:'+symbol, mode='real', bot='exchange', strategy='TheTrueTrade',
                symbol=symbol, side=pos.side, status='open', entry=finite(pos.entry), exit=None,
                opened_at=None, closed_at=None, stop=None, target=None, timeframe='4h', pnl_usd=pnl,
                pnl_basis='Exchange-reported floating P&L; fee/funding coverage unknown' if pnl is not None else 'Exchange net P&L unavailable',
                reason='', price_move_pct=price_move(pos.entry, mark, pos.side), current_price=mark,
                valuation_at=source_started_at, quote_time_basis='Mark price from the active-position response; exchange tick time unavailable.'))
        empty['warnings'] = ['Entry, mark price and floating P&L are shown only when reported by the exchange. Fee/funding coverage and realized net P&L are unverified.']
        empty['publishable'] = True
        empty['generated_at'] = time.time()
    except Exception:
        empty['warnings'] = ['Real account read failed; no cached, simulated or paper result is shown.']
    return empty


def candles_for(engine, trade):
    """Read actual futures CSVs only, without generating demo candles or calling execution adapters.

    A real TTT position is deliberately not overlaid on LBank candles.
    """
    if trade['mode'] == 'real':
        return [], 'Matching TheTrueTrade candles are not available in this version.'
    if getattr(engine.data, 'mode', None) != 'csv-lbank':
        return [], 'Verified futures candle source required; synthetic candles are excluded.'
    symbol, tf = trade['symbol'], trade['timeframe']
    from lbank_bot import TIMEFRAMES
    if tf not in TIMEFRAMES or any(c in symbol for c in ('\\', '..')):
        return [], 'Invalid candle source.'
    folder = Path(engine.data.ohlcv_dir)
    name = symbol.replace('/', '_').replace(':', '_') + '_' + tf + '.csv'
    path = folder / name
    end = trade['closed_at'] or time.time()
    try:
        # Official store has its own aggregation path; ordinary CSVs may contain much longer histories.
        if os.getenv('LBANK_OFFICIAL_CANDLES') == '1':
            from lbank_official_candles import _published
            if tf != '4h':
                return [], 'Official futures candles support 4h only.'
            bars, _ = _published(folder, symbol)
        else:
            with path.open(newline='') as stream:
                bars = [[r[k] for k in ('timestamp','open','high','low','close','volume')]
                        for r in csv.DictReader(stream)]
        checked = {}
        seconds = TIMEFRAMES[tf]
        for b in bars:
            values = [finite(v) for v in b[:6]]
            if len(values) != 6 or any(v is None for v in values):
                raise ValueError('Invalid candle fields')
            ts, o, h, l, c, vol = values
            if ts <= 0 or min(o,h,l,c) <= 0 or h < max(o,l,c) or l > min(o,h,c) or vol < 0 or ts in checked:
                raise ValueError('Invalid or duplicate candles')
            if ts/1000 + seconds > end:
                continue
            checked[ts] = values
        selected = [checked[k] for k in sorted(checked)][-180:]
        if not selected:
            return [], 'No completed verified candles cover this period.'
        age = end - (selected[-1][0]/1000 + seconds)
        note = 'LBank USDT futures • completed candles • UTC'
        if any(b[0] - a[0] != seconds * 1000 for a, b in zip(selected, selected[1:])):
            note += ' • GAPS IN CANDLE SOURCE'
        if trade['bot'] == 'main' and trade['status'] == 'closed':
            note += ' • 4h context; historical execution timeframe not retained'
        if age > seconds * 2:
            note += ' • STALE / historical coverage gap'
        if trade['opened_at'] is None:
            note += ' • Entry time not recorded; entry line is a price level only'
        elif trade['opened_at'] < selected[0][0]/1000:
            note += ' • Entry is earlier than the displayed window'
        return selected, note
    except (OSError, ValueError, KeyError, TypeError):
        return [], 'Verified candle file unavailable for this trade.'


class BroadcastFeed:
    """Per-dashboard, bounded GET-only polling cache.

    The original generated_at is preserved while a snapshot is cached. Once a
    refresh fails, previous profit values are discarded rather than replayed as live.
    No API credential or request secret is included in keys or returned payloads.
    """
    def __init__(self, engine_provider, ttl=5.0, clock=None):
        self.engine_provider = engine_provider
        self.ttl = max(5.0, float(ttl))
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._snapshots = {}
        self._candles = OrderedDict()

    def _unavailable(self, mode):
        now = time.time()
        return dict(records=[], account=dict(equity_usd=None, pnl_usd=None,
                    return_pct=None, basis='Source unavailable; previous results withheld.', as_of=now),
                    warnings=['Source read failed; previous profit values are not presented as live.'],
                    notice='Broadcast is read-only; no orders or configuration changes are made.',
                    data_mode='unavailable', publishable=False, generated_at=now)

    def get(self, mode='paper', trade_id=None, bot_filter='all', scope='open'):
        if mode not in ('paper', 'real') or bot_filter not in ('all', 'main', 'c3', 'pa') or scope not in ('all', 'open', 'closed'):
            raise ValueError('Invalid broadcast selection')
        with self._lock:
            engine = self.engine_provider()
            cached = self._snapshots.get(mode)
            if cached is None or self.clock() >= cached[0]:
                try:
                    source_started_at = time.time()
                    snapshot = paper_snapshot(engine) if mode == 'paper' else real_snapshot()
                    snapshot.setdefault('source_started_at', source_started_at)
                except Exception:
                    # Keep exception bodies, database paths and upstream account errors private.
                    snapshot = self._unavailable(mode)
                self._snapshots[mode] = (self.clock() + self.ttl, snapshot)
            else:
                snapshot = cached[1]
            result = copy.deepcopy(snapshot)
            records = [r for r in result['records']
                       if (bot_filter == 'all' or r['bot'] == bot_filter)
                       and (scope == 'all' or r['status'] == scope)]
            records.sort(key=lambda r: (r['status'] != 'open', -(r.get('closed_at') or 0)))
            trade = next((r for r in records if r['id'] == trade_id), None)
            if trade is None:
                trade = records[0] if records else None
            bars, note = [], 'No recorded position or exit matches this selection.'
            if trade is not None:
                key = (mode, trade['id'], trade.get('symbol'), trade.get('timeframe'),
                       trade.get('opened_at'), trade.get('closed_at'))
                chart = self._candles.get(key)
                if chart is None or self.clock() >= chart[0]:
                    try:
                        bars, note = candles_for(engine, trade)
                    except Exception:
                        bars, note = [], 'Matching candle source unavailable.'
                    self._candles[key] = (self.clock() + self.ttl, copy.deepcopy(bars), note)
                    self._candles.move_to_end(key)
                    while len(self._candles) > 32:
                        self._candles.popitem(last=False)
                else:
                    _, bars, note = chart
                    bars = copy.deepcopy(bars)
                    self._candles.move_to_end(key)
            generated = finite(result.get('generated_at'))
            result.update(records=records, trade=trade, candles=bars, candle_note=note,
                          poll_after_seconds=self.ttl,
                          snapshot_age_seconds=max(0, time.time()-generated) if generated is not None else None,
                          source_ok=result.get('data_mode') != 'unavailable' and bool(result.get('publishable')),
                          received_at=time.time(), selection=dict(mode=mode, bot=bot_filter, scope=scope))
            return result
