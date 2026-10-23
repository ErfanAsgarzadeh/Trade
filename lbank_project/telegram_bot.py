"""Private, read-only Telegram reports for the three trading databases (stdlib only)."""
from __future__ import annotations

from contextlib import closing
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib import request, error, parse

LOG = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
PAGE_SIZE = 5
PENDING = 'STATE_PENDING_TRIGGER'
KEYBOARD = {'keyboard': [['📈 معاملات باز', '📕 معاملات بسته'], ['📊 خلاصه']],
            'resize_keyboard': True}


def number(value):
    return '—' if value is None else f'{float(value):,.6f}'.rstrip('0').rstrip('.')


def date(value):
    if not value:
        return '—'
    value = float(value)
    if value > 100_000_000_000:
        value /= 1000
    return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


class Reports:
    def __init__(self, paths=None):
        self.paths = paths or {
            'شاهین': ('main', Path(os.getenv('BOT_DB', HERE / 'data/lbank_ichimoku_bot.db'))),
            'موج‌سوار': ('c3', Path(os.getenv('C3_DB', HERE / 'data/c3_sleeve.db'))),
            'ققنوس': ('pa', Path(os.getenv('PA_DB', HERE / 'data/pa_sleeve.db'))),
        }

    def snapshot(self, kind, page):
        rows, warnings = [], []
        total, pnl = 0, 0.0
        for name, (source, path) in self.paths.items():
            try:
                # mode=ro prevents creating an empty database or changing the trading state.
                with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True,
                                             timeout=3)) as db:
                    db.row_factory = sqlite3.Row
                    db.execute('PRAGMA query_only=ON')
                    db.execute('BEGIN')
                    main = source == 'main'
                    table = 'positions' if kind == 'open' else ('trade_history' if main else 'trades')
                    where = ' WHERE state != ?' if kind == 'open' and main else ''
                    args = (PENDING,) if where else ()
                    order = 'symbol' if kind == 'open' else ('closed_at DESC, id DESC' if main else 'closed DESC, id DESC')
                    count = db.execute(f'SELECT COUNT(*) FROM {table}{where}', args).fetchone()[0]
                    local_pnl = 0.0
                    if kind == 'closed':
                        col = 'pnl_usd' if main else 'pnl'
                        local_pnl = db.execute(f'SELECT COALESCE(SUM({col}),0) FROM {table}').fetchone()[0]
                    # Fetch enough from each source to merge the requested global page.
                    selected = db.execute(f'SELECT * FROM {table}{where} ORDER BY {order} LIMIT ?',
                                          (*args, page * PAGE_SIZE + 1)).fetchall()
                    normalized = []
                    for row in selected:
                        r = dict(row)
                        normalized.append(dict(r, bot=name,
                            entry=r.get('entry_price') if main else r.get('entry'),
                            exit=r.get('exit_price') if main else r.get('exit'),
                            stop=r.get('active_sl') if main else r.get('stop'),
                            closed=r.get('closed_at', 0) if main else r.get('closed', 0),
                            pnl=r.get('pnl_usd') if main else r.get('pnl')))
                    rows.extend(normalized)
                    total += count
                    pnl += local_pnl
            except (sqlite3.Error, OSError):
                warnings.append(f'⚠️ اطلاعات {name} در دسترس نیست؛ گزارش ممکن است ناقص باشد.')
        rows.sort(key=(lambda r: (-r['closed'], r['bot'], -r['id'])) if kind == 'closed'
                  else (lambda r: (r['bot'], r['symbol'])))
        start = (page - 1) * PAGE_SIZE
        return rows[start:start + PAGE_SIZE], total, pnl, warnings

    def render(self, kind, page=1):
        rows, total, pnl, warnings = self.snapshot(kind, page)
        title = '📈 معاملات باز' if kind == 'open' else '📕 خروج‌های ثبت‌شده'
        lines = [title, f'تعداد: {total} | صفحه: {page}']
        if kind == 'closed':
            lines += [f'سود/زیان خالص ثبت‌شده: {pnl:+,.2f} USD',
                      'هر ردیف یک خروج کامل یا جزئی است.']
        else:
            lines += ['سفارش‌های معلق در این فهرست نیستند. سود لحظه‌ای محاسبه نمی‌شود.']
        for r in rows:
            side = {'long': 'خرید (Long)', 'short': 'فروش (Short)'}.get(r['side'], r['side'])
            lines += ['', f"{r['bot']} | {r['symbol']} | {side}",
                      f"ورود: {number(r['entry'])} | حجم: {number(r['qty'])}"]
            if kind == 'open':
                lines += [f"حد ضرر: {number(r['stop'])}"]
                if r.get('tp1_price') is not None:
                    lines += [f"هدف اول: {number(r['tp1_price'])}"]
                lines += [f"زمان سیگنال: {date(r.get('signal_ts'))}"]
            else:
                lines += [f"خروج: {number(r['exit'])} | سود/زیان: {r['pnl']:+,.2f} USD",
                          f"زمان خروج: {date(r['closed'])}", f"دلیل: {r['reason']}"]
        if not rows:
            lines += ['موردی در این صفحه نیست.']
        if page * PAGE_SIZE < total:
            lines += [f'صفحه بعد: /{kind} {page + 1}']
        return '\n'.join(lines + ['', *warnings])

    def reply(self, text):
        text = text.strip()
        text = {'📈 معاملات باز': '/open', '📕 معاملات بسته': '/closed',
                '📊 خلاصه': '/status'}.get(text, text)
        match = re.fullmatch(r'/(open|closed)(?:@\w+)?(?:\s+(\d{1,4}))?', text)
        if match:
            return self.render(match[1], max(1, int(match[2] or 1)))
        if re.fullmatch(r'/status(?:@\w+)?', text):
            _, opened, _, w1 = self.snapshot('open', 1)
            _, closed, pnl, w2 = self.snapshot('closed', 1)
            return '\n'.join(['📊 خلاصه معاملات', f'پوزیشن باز: {opened}',
                              f'خروج ثبت‌شده: {closed}', f'سود/زیان ثبت‌شده: {pnl:+,.2f} USD',
                              'گزارش از دیتابیس محلی است؛ وضعیت اجرای ربات را تأیید نمی‌کند.',
                              *dict.fromkeys(w1 + w2)])
        return ('گزارش معاملات شاهین، موج‌سوار و ققنوس\n'
                '/open — معاملات باز\n/closed — خروج‌های ثبت‌شده\n'
                '/status — خلاصه\nبرای صفحه بعد: /closed 2\n'
                'زمان‌ها UTC هستند. نوع paper/live مطابق اجرای ربات معاملاتی است.')


class TelegramError(Exception):
    def __init__(self, code, retry_after=5):
        self.code, self.retry_after = code, retry_after
        super().__init__(f'Telegram API error {code}')


class Telegram:
    def __init__(self, token):
        self.base = 'https://api.telegram.org/bot' + token + '/'

    def call(self, method, **payload):
        req = request.Request(self.base + method, data=json.dumps(payload).encode(),
                              headers={'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=45) as response:
                data = json.load(response)
        except error.HTTPError as exc:
            retry = 5
            if exc.code == 429:
                try:
                    retry = int(json.load(exc).get('parameters', {}).get('retry_after', 5))
                except (ValueError, TypeError):
                    pass
            raise TelegramError(exc.code, retry) from None
        except (error.URLError, TimeoutError, OSError):
            # Never log the URL: it contains the bot token.
            raise TelegramError(0) from None
        if not data.get('ok'):
            raise TelegramError(data.get('error_code', 0),
                                data.get('parameters', {}).get('retry_after', 5))
        return data['result']

    def send(self, chat_id, text):
        # Split by characters below Telegram's UTF-16 message limit.
        for start in range(0, len(text), 1800):
            self.call('sendMessage', chat_id=chat_id, text=text[start:start + 1800],
                      reply_markup=KEYBOARD)


def handle_update(api, reports, allowed, update):
    message = update.get('message', {})
    sender, chat = message.get('from', {}), message.get('chat', {})
    if (sender.get('id') not in allowed or chat.get('type') != 'private'
            or chat.get('id') != sender.get('id') or not isinstance(message.get('text'), str)):
        return
    api.send(chat['id'], reports.reply(message['text']))


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    try:
        allowed = {int(v.strip()) for v in os.getenv('TELEGRAM_ALLOWED_USER_IDS', '').split(',') if v.strip()}
        if not allowed or any(v <= 0 for v in allowed) or not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
            raise ValueError
    except ValueError:
        raise SystemExit('Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS (positive numeric IDs).')
    api, reports, offset = Telegram(token), Reports(), None
    LOG.info('Telegram reports started; private authorized users only.')
    while True:
        try:
            updates = api.call('getUpdates', offset=offset, timeout=30, allowed_updates=['message'])
            for update in updates:
                try:
                    handle_update(api, reports, allowed, update)
                except TelegramError as exc:
                    if exc.code != 403:
                        raise
                offset = update['update_id'] + 1
        except TelegramError as exc:
            if exc.code in (401, 404, 409):
                raise SystemExit(f'Telegram error {exc.code}: check token, webhook, and duplicate pollers.') from None
            LOG.warning('Telegram unavailable (code %s); retrying.', exc.code)
            time.sleep(min(max(exc.retry_after, 1), 60))
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
