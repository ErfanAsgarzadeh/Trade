"""Real SQLite reports and access-control tests; no Telegram traffic or trading."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telegram_bot import Reports, Telegram, TelegramError, handle_update, PAGE_SIZE


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paths = {}
        for source, name in [('main', 'شاهین'), ('c3', 'موج‌سوار'), ('pa', 'ققنوس')]:
            path = self.root / (source + '.db')
            paths[name] = (source, path)
            with sqlite3.connect(path) as db:
                if source == 'main':
                    db.executescript('''CREATE TABLE positions(symbol TEXT,side TEXT,entry_price REAL,qty REAL,active_sl REAL,tp1_price REAL,state TEXT,signal_ts INTEGER);
                    CREATE TABLE trade_history(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,entry_price REAL,exit_price REAL,qty REAL,pnl_usd REAL,closed_at INTEGER,reason TEXT,dry_run INTEGER);''')
                    db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?)',
                               ('BTC/USDT', 'long', 100, 2, 90, 120, 'STATE_INITIAL', 1700000000000))
                    db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?)',
                               ('ETH/USDT', 'short', 100, 2, 110, 80, 'STATE_PENDING_TRIGGER', 0))
                    for i in range(1, 9):
                        db.execute('INSERT INTO trade_history VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (i, 'BTC/USDT', 'long', 100, 110, 1, 9.7, 1700000000 + i * 3, 'TP1', 1))
                else:
                    db.executescript('''CREATE TABLE positions(symbol TEXT,side TEXT,entry REAL,qty REAL,stop REAL,signal_ts INTEGER);
                    CREATE TABLE trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,entry REAL,exit REAL,qty REAL,opened REAL,closed REAL,pnl REAL,reason TEXT);''')
                    db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?)', ('SOL/USDT', 'short', 100, 1, 110, 1700000000000))
                    for i in range(1, 9):
                        db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (i, 'SOL/USDT', 'short', 100, 110, 1, 1699990000, 1700000000 + i * 3 + (1 if source == 'c3' else 2), -10.2, 'STOP'))
        self.reports = Reports(paths)

    def test_open_filters_pending_and_formats_all_sources(self):
        text = self.reports.reply('/open')
        for name in ('شاهین', 'موج‌سوار', 'ققنوس'):
            self.assertIn(name, text)
        self.assertIn('تعداد: 3', text)
        self.assertNotIn('ETH/USDT', text)
        self.assertIn('2023-11-14 22:13 UTC', text)
        self.assertIn('هدف اول: 120', text)

    def test_closed_global_pagination_no_duplicates(self):
        rows = []
        for page in range(1, 6):
            selected, total, pnl, warnings = self.reports.snapshot('closed', page)
            self.assertEqual(total, 24)
            self.assertAlmostEqual(pnl, 8 * (9.7 - 20.4))
            self.assertEqual(warnings, [])
            self.assertLessEqual(len(selected), PAGE_SIZE)
            rows.extend(selected)
        self.assertEqual(len({(r['bot'], r['id']) for r in rows}), 24)
        self.assertEqual([r['closed'] for r in rows], sorted([r['closed'] for r in rows], reverse=True))
        text = self.reports.reply('/closed@TradeBot 2')
        self.assertIn('صفحه: 2', text)
        self.assertIn('/closed 3', text)
        self.assertIn('خروج کامل یا جزئی', text)

    def test_missing_database_warns_without_creating_file(self):
        missing = self.root / 'missing.db'
        reports = Reports({'آزمون': ('main', missing)})
        self.assertIn('ناقص', reports.reply('/status'))
        self.assertFalse(missing.exists())

    def test_reading_does_not_change_database(self):
        before = {p: p.read_bytes() for _, p in self.reports.paths.values()}
        self.reports.reply('/open')
        self.reports.reply('/closed')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_report_reads_committed_positions_while_engine_writes_wal(self):
        path = self.reports.paths['شاهین'][1]
        with sqlite3.connect(path, timeout=0.2) as engine:
            self.assertEqual(engine.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            engine.execute('BEGIN IMMEDIATE')
            engine.execute("UPDATE positions SET active_sl=95 WHERE symbol='BTC/USDT'")
            # Reporting sees the last committed stop, without interfering with the writer.
            rows, total, _, warnings = self.reports.snapshot('open', 1)
            self.assertEqual(warnings, [])
            self.assertEqual(total, 3)
            self.assertEqual(next(r for r in rows if r['bot'] == 'شاهین')['stop'], 90)
            engine.commit()
            rows, _, _, warnings = self.reports.snapshot('open', 1)
            self.assertEqual(warnings, [])
            self.assertEqual(next(r for r in rows if r['bot'] == 'شاهین')['stop'], 95)
            p = engine.execute("SELECT qty,entry_price,tp1_price,state FROM positions WHERE symbol='BTC/USDT'").fetchone()
            self.assertEqual(p, (2, 100, 120, 'STATE_INITIAL'))

    def test_menu_status_and_invalid_commands(self):
        self.assertIn('تعداد: 3', self.reports.reply('📈 معاملات باز'))
        self.assertIn('پوزیشن باز: 3', self.reports.reply('/status'))
        self.assertIn('/open', self.reports.reply('/closed -1'))


class SecurityTests(unittest.TestCase):
    def test_only_allowlisted_private_sender_can_get_reports(self):
        api, reports = Mock(), Mock()
        reports.reply.return_value = 'report'
        for sender, chat, kind in [(8, 8, 'private'), (7, -7, 'group'), (7, 8, 'private')]:
            handle_update(api, reports, {7}, {'message': {'from': {'id': sender}, 'chat': {'id': chat, 'type': kind}, 'text': '/open'}})
        handle_update(api, reports, {7}, {'edited_message': {}})
        reports.reply.assert_not_called()
        handle_update(api, reports, {7}, {'message': {'from': {'id': 7}, 'chat': {'id': 7, 'type': 'private'}, 'text': '/open'}})
        api.send.assert_called_once_with(7, 'report')

    def test_messages_split_and_token_not_in_errors(self):
        api = Telegram('123:secret')
        api.call = Mock()
        api.send(7, '😀' * 5000)
        self.assertEqual(api.call.call_count, 3)
        self.assertTrue(all(len(c.kwargs['text'].encode('utf-16-le')) // 2 <= 4096 for c in api.call.call_args_list))
        api = Telegram('123:secret')
        with patch('telegram_bot.request.urlopen', side_effect=URLError('https://secret')):
            with self.assertRaises(TelegramError) as raised:
                api.call('getUpdates')
        self.assertNotIn('secret', str(raised.exception))

    def test_rate_limit_preserves_retry_after(self):
        import io
        exc = HTTPError('https://secret', 429, '', {}, io.BytesIO(json.dumps({'parameters': {'retry_after': 12}}).encode()))
        with patch('telegram_bot.request.urlopen', side_effect=exc):
            with self.assertRaises(TelegramError) as raised:
                Telegram('123:secret').call('getUpdates')
        self.assertEqual(raised.exception.retry_after, 12)


if __name__ == '__main__':
    unittest.main()
