"""Telegram for customers: link an Avina account to Telegram and receive signals and account notices there.

The owner creates a bot with @BotFather and enters its token in the admin panel (stored encrypted with the portal
key). A customer presses "Connect Telegram" in their panel, which opens t.me/<bot>?start=<one-time code>; pressing
Start sends that code to the bot and links the chat. The worker uses long polling (getUpdates), so no public domain or
webhook is needed. Messages are plain text, never HTML, so nothing a user or signal contains can inject formatting.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import secrets
import signal as signals_module
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from portal_audit import record, require_admin

API = 'https://api.telegram.org'
CODE_LIFETIME = 15 * 60
SIGNAL_LOOKBACK = 2 * 3600
TOKEN = re.compile(r'^\d{5,12}:[A-Za-z0-9_-]{30,64}$')
BOT_NAMES = {'main': ('شاهین', 'Falcon'), 'c3': ('موج‌سوار', 'Wave Rider'), 'pa': ('ققنوس', 'Phoenix')}
TEHRAN = timezone(timedelta(hours=3, minutes=30))


class TelegramError(Exception):
    """Telegram refused the call or could not be reached."""

    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


def call(token, method, params=None, timeout=15):
    """One Bot API call. The token never appears in error messages."""
    url = f'{API}/bot{token}/{method}'
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as response:
            reply = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        try:reply = json.loads(exc.read(100_000))
        except Exception:raise TelegramError('Telegram HTTP error', exc.code) from None
    except Exception:
        raise TelegramError('Telegram unreachable') from None
    if not reply.get('ok'):
        raise TelegramError(str(reply.get('description', 'Telegram error'))[:200], reply.get('error_code'),
                            (reply.get('parameters') or {}).get('retry_after'))
    return reply['result']


def text(lang, fa, en):return en if lang == 'en' else fa


def notify(db, user_id, fa, en):
    """Queue an account notice for a linked user who wants notices. Call inside the caller's transaction."""
    link = db.execute('SELECT chat_id,lang,notices FROM telegram_links WHERE user_id=?', (user_id,)).fetchone()
    if link and link['notices']:
        db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                   (str(uuid.uuid4()), link['chat_id'], text(link['lang'], fa, en), time.time()))


def signal_text(item, lang):
    name = BOT_NAMES.get(item.get('bot'), (item.get('bot', ''),) * 2)[1 if lang == 'en' else 0]
    side = item['side'] == 'long'
    when = datetime.fromtimestamp(item['expires_at'], TEHRAN).strftime('%Y-%m-%d %H:%M')
    number = lambda v: f'{float(v):.10g}'
    lines = [text(lang, f'📈 سیگنال تازهٔ آوینا · {name}', f'📈 New Avina signal · {name}'),
             f'{item["symbol"]} · ' + (text(lang, 'خرید (Long)', 'Long') if side else text(lang, 'فروش (Short)', 'Short'))
             + f' · {item.get("timeframe", "")}',
             text(lang, 'ورود پیشنهادی: ', 'Suggested entry: ') + number(item['entry']),
             text(lang, 'حد ضرر: ', 'Stop-loss: ') + number(item['stop'])]
    if item.get('target') is not None:lines.append(text(lang, 'هدف اول: ', 'First target: ') + number(item['target']))
    lines.append(text(lang, 'معتبر تا (به وقت تهران): ', 'Valid until (Tehran time): ') + when)
    lines.append(text(lang, 'این سیگنال پیشنهاد معاملاتی است، نه سفارش اجراشده. سطوح قیمت تضمین‌شده نیستند.',
                      'This is a trade suggestion, not an executed order. Price levels are not guaranteed.'))
    return '\n'.join(lines)


class Telegram:
    def __init__(self, store, call=None):
        # Look the client up at call time, so a stand-in installed on the module reaches the web routes too.
        self.store, self.call = store, call or (lambda *args, **kwargs: globals()['call'](*args, **kwargs))

    # Settings ------------------------------------------------------------------------------------------------------
    def _setting(self, db, name):
        row = db.execute('SELECT value FROM site_settings WHERE name=?', ('telegram.' + name,)).fetchone()
        return row['value'] if row else ''

    def token(self, db=None):
        def read(db):
            value = self._setting(db, 'token')
            return self.store.vault.decrypt(value.encode()).decode() if value else ''
        if db is not None:return read(db)
        with self.store.db() as db:return read(db)

    def bot_username(self):
        with self.store.db() as db:return self._setting(db, 'bot_username')

    def configure(self, actor, token):
        """Save (or with an empty token, remove) the bot token after Telegram confirms it."""
        token = (token or '').strip()
        username = ''
        if token:
            if not TOKEN.match(token):raise ValueError('That does not look like a bot token from @BotFather')
            me = self.call(token, 'getMe')
            if not me.get('is_bot') or not me.get('username'):raise ValueError('Telegram did not accept this token')
            username = me['username']
            self.call(token, 'deleteWebhook')  # getUpdates only works without a webhook.
        now = time.time()
        with self.store.db() as db:
            self.store.database.begin_write(db, 'telegram')
            require_admin(db, actor)
            for name, value in (('token', self.store.vault.encrypt(token.encode()).decode() if token else ''),
                                ('bot_username', username)):
                db.execute('INSERT INTO site_settings(name,value,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET '
                           'value=excluded.value,updated=excluded.updated', ('telegram.' + name, value, now))
            record(db, actor, 'telegram_configured' if token else 'telegram_removed', 'telegram', dict(bot=username))
        return self.status()

    def status(self):
        with self.store.db() as db:
            username = self._setting(db, 'bot_username')
            linked = db.execute('SELECT COUNT(*) AS n FROM telegram_links').fetchone()['n']
            queued = db.execute('SELECT COUNT(*) AS n FROM telegram_outbox WHERE sent IS NULL AND attempts<5').fetchone()['n']
            gates = {row['name']: row['next_at'] for row in db.execute(
                "SELECT name,next_at FROM service_gate WHERE name IN ('telegram:heartbeat','telegram:ok')").fetchall()}
        return dict(configured=bool(username), bot_username=username, linked=linked, queued=queued,
                    worker_seen=gates.get('telegram:heartbeat'), last_ok=gates.get('telegram:ok'))

    # Customer side -------------------------------------------------------------------------------------------------
    def link_code(self, user, lang='fa'):
        username = self.bot_username()
        if not username:raise LookupError('Telegram is not set up')
        code = secrets.token_urlsafe(18)
        with self.store.db() as db:
            db.execute('DELETE FROM telegram_link_codes WHERE user_id=? OR expires<?', (user, time.time()))
            db.execute('INSERT INTO telegram_link_codes(code_hash,user_id,lang,expires) VALUES(?,?,?,?)',
                       (hashlib.sha256(code.encode()).hexdigest(), user, lang if lang in ('fa', 'en') else 'fa',
                        time.time() + CODE_LIFETIME))
        return dict(url=f'https://t.me/{username}?start={code}', app_url=f'tg://resolve?domain={username}&start={code}',
                    bot_username=username, expires=time.time() + CODE_LIFETIME)

    def account(self, user):
        with self.store.db() as db:
            link = db.execute('SELECT username,signals,notices,linked FROM telegram_links WHERE user_id=?', (user,)).fetchone()
            available = bool(self._setting(db, 'bot_username'))
        return dict(available=available, linked=bool(link), telegram_username=link['username'] if link else None,
                    signals=bool(link['signals']) if link else True, notices=bool(link['notices']) if link else True)

    def preferences(self, user, signals, notices):
        with self.store.db() as db:
            if db.execute('UPDATE telegram_links SET signals=?,notices=? WHERE user_id=?',
                          (int(bool(signals)), int(bool(notices)), user)).rowcount != 1:raise LookupError('Not linked')
        return self.account(user)

    def unlink(self, user):
        with self.store.db() as db:
            link = db.execute('SELECT chat_id,lang FROM telegram_links WHERE user_id=?', (user,)).fetchone()
            if not link:return self.account(user)
            db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                       (str(uuid.uuid4()), link['chat_id'], text(link['lang'], 'اتصال این تلگرام به حساب آوینا قطع شد.',
                                                                'This Telegram is no longer linked to your Avina account.'),
                        time.time()))
            db.execute('DELETE FROM telegram_links WHERE user_id=?', (user,))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (user, 'telegram_unlinked', time.time()))
        return self.account(user)

    def broadcast(self, actor, message):
        message = (message or '').strip()
        if not 1 <= len(message) <= 3500:raise ValueError('Message must be 1..3500 characters')
        now = time.time()
        with self.store.db() as db:
            self.store.database.begin_write(db, 'telegram')
            require_admin(db, actor)
            chats = db.execute('SELECT chat_id FROM telegram_links WHERE notices=1').fetchall()
            for row in chats:
                db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                           (str(uuid.uuid4()), row['chat_id'], message, now))
            record(db, actor, 'telegram_broadcast', 'telegram', dict(recipients=len(chats), length=len(message)))
        return dict(recipients=len(chats))

    # Bot side ------------------------------------------------------------------------------------------------------
    def handle(self, update, site=''):
        """One incoming update: /start <code> links, /stop unlinks, anything else gets help."""
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        if chat.get('type') != 'private' or not isinstance(chat.get('id'), int):return
        chat_id, body = chat['id'], (message.get('text') or '').strip()
        sender = message.get('from') or {}
        lang = 'fa' if str(sender.get('language_code', 'fa')).startswith('fa') else 'en'
        reply = None
        with self.store.db() as db:
            self.store.database.begin_write(db, 'telegram')
            current = db.execute('SELECT user_id,lang FROM telegram_links WHERE chat_id=?', (chat_id,)).fetchone()
            match = re.fullmatch(r'/start(?:@\w+)?\s+([A-Za-z0-9_-]{16,64})', body)
            if match:
                row = db.execute('SELECT user_id,lang FROM telegram_link_codes WHERE code_hash=? AND expires>?',
                                 (hashlib.sha256(match[1].encode()).hexdigest(), time.time())).fetchone()
                if not row:
                    reply = text(lang, 'این لینک اتصال منقضی یا نامعتبر است. از پنل آوینا دوباره «اتصال تلگرام» را بزنید.',
                                 'This link has expired or is invalid. Press "Connect Telegram" in your Avina panel again.')
                else:
                    lang = row['lang']
                    db.execute('DELETE FROM telegram_link_codes WHERE user_id=?', (row['user_id'],))
                    db.execute('DELETE FROM telegram_links WHERE chat_id=? OR user_id=?', (chat_id, row['user_id']))
                    db.execute('INSERT INTO telegram_links(user_id,chat_id,username,lang,signals,notices,linked) VALUES(?,?,?,?,1,1,?)',
                               (row['user_id'], chat_id, str(sender.get('username') or '')[:64], lang, time.time()))
                    db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (row['user_id'], 'telegram_linked', time.time()))
                    name = db.execute('SELECT username FROM users WHERE id=?', (row['user_id'],)).fetchone()['username']
                    reply = text(lang, f'✅ حساب آوینای «{name}» به این تلگرام وصل شد.\nاز این پس سیگنال‌ها و اطلاع‌رسانی‌های حساب شما همین‌جا ارسال می‌شود. برای قطع اتصال /stop را بفرستید.',
                                 f'✅ Avina account "{name}" is now linked to this Telegram.\nYour signals and account notices will arrive here. Send /stop to unlink.')
            elif re.fullmatch(r'/stop(?:@\w+)?', body):
                if current:
                    db.execute('DELETE FROM telegram_links WHERE chat_id=?', (chat_id,))
                    db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)', (current['user_id'], 'telegram_unlinked', time.time()))
                reply = text(current['lang'] if current else lang, 'اتصال قطع شد؛ دیگر پیامی از آوینا اینجا نمی‌آید.',
                             'Unlinked; Avina will not message you here anymore.')
            else:
                if current:
                    reply = text(current['lang'], 'این تلگرام به حساب آوینای شما وصل است. برای قطع اتصال /stop را بفرستید.',
                                 'This Telegram is linked to your Avina account. Send /stop to unlink.')
                else:
                    panel = (site.rstrip('/') + ('/en/dashboard/' if lang == 'en' else '/dashboard/')) if site else ''
                    reply = text(lang, 'سلام! برای دریافت سیگنال‌ها و اطلاع‌رسانی‌های آوینا، وارد پنل خود شوید و «اتصال تلگرام» را بزنید.',
                                 'Hi! To receive Avina signals and notices, sign in to your panel and press "Connect Telegram".') + (
                        '\n' + panel if panel else '')
            if reply:
                db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                           (str(uuid.uuid4()), chat_id, reply, time.time()))

    def queue_signals(self, feed, now=None):
        """Queue each new active signal once for every linked user who wants signals and has an active subscription."""
        from portal_billing import public_license
        now = time.time() if now is None else now
        fresh = [s for s in feed if s.get('expires_at', 0) > now and s.get('published_at', 0) > now - SIGNAL_LOOKBACK]
        if not fresh:return 0
        queued = 0
        with self.store.db() as db:
            self.store.database.begin_write(db, 'telegram')
            links = db.execute('SELECT l.user_id,l.chat_id,l.lang,l.linked,c.document FROM telegram_links l '
                               'LEFT JOIN capital_licenses c ON c.user_id=l.user_id WHERE l.signals=1').fetchall()
            for link in links:
                if not public_license(link['document'], now).get('signals_allowed'):continue
                for item in fresh:
                    if item.get('published_at', 0) < link['linked']:continue  # nothing from before the user linked
                    key = '|'.join(str(item.get(k)) for k in ('bot', 'symbol', 'side', 'candle_ts', 'timeframe'))
                    if db.execute('SELECT 1 FROM telegram_signal_sent WHERE user_id=? AND signal_key=?',
                                  (link['user_id'], key)).fetchone():continue
                    db.execute('INSERT INTO telegram_signal_sent(user_id,signal_key,sent) VALUES(?,?,?)', (link['user_id'], key, now))
                    db.execute('INSERT INTO telegram_outbox(id,chat_id,text,created) VALUES(?,?,?,?)',
                               (str(uuid.uuid4()), link['chat_id'], signal_text(item, link['lang']), now))
                    queued += 1
        return queued

    def send_outbox(self, token, limit=50):
        sent = 0
        with self.store.db() as db:
            rows = db.execute('SELECT id,chat_id,text,attempts FROM telegram_outbox WHERE sent IS NULL AND attempts<5 '
                              'ORDER BY created LIMIT ?', (limit,)).fetchall()
        for row in rows:
            try:
                self.call(token, 'sendMessage', dict(chat_id=row['chat_id'], text=row['text'], disable_web_page_preview='true'))
                with self.store.db() as db:db.execute('UPDATE telegram_outbox SET sent=? WHERE id=?', (time.time(), row['id']))
                sent += 1
            except TelegramError as exc:
                with self.store.db() as db:
                    if exc.status == 403:  # The user blocked the bot or deleted the chat: stop messaging them.
                        db.execute('DELETE FROM telegram_links WHERE chat_id=?', (row['chat_id'],))
                        db.execute('UPDATE telegram_outbox SET attempts=5 WHERE chat_id=? AND sent IS NULL', (row['chat_id'],))
                    elif exc.status == 429:
                        time.sleep(min(30, exc.retry_after or 5))
                        break
                    else:
                        db.execute('UPDATE telegram_outbox SET attempts=attempts+1 WHERE id=?', (row['id'],))
                if exc.status is None:break  # Telegram unreachable: try again next round.
            time.sleep(0.05)
        with self.store.db() as db:
            db.execute('DELETE FROM telegram_outbox WHERE (sent IS NOT NULL AND sent<?) OR (attempts>=5 AND created<?)',
                       (time.time() - 7 * 86400, time.time() - 7 * 86400))
            db.execute('DELETE FROM telegram_signal_sent WHERE sent<?', (time.time() - 30 * 86400,))
            db.execute('DELETE FROM telegram_link_codes WHERE expires<?', (time.time(),))
        return sent


class Worker:
    def __init__(self, store, feed_reader, site='', call=None, poll_seconds=10):
        self.telegram = Telegram(store, call)
        self.store, self.feed_reader, self.site, self.call, self.poll = store, feed_reader, site, self.telegram.call, poll_seconds

    def _gate(self, name, value=None):
        with self.store.db() as db:
            if value is None:
                row = db.execute('SELECT next_at FROM service_gate WHERE name=?', (name,)).fetchone()
                return row['next_at'] if row else None
            db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',
                       (name, value))

    def once(self):
        self._gate('telegram:heartbeat', time.time())
        token = self.telegram.token()
        if not token:return False
        offset = self._gate('telegram:offset')
        updates = self.call(token, 'getUpdates', dict(offset=int(offset or 0), timeout=self.poll,
                                                      allowed_updates='["message"]'), timeout=self.poll + 10)
        for update in updates:
            self.telegram.handle(update, self.site)
            self._gate('telegram:offset', update['update_id'] + 1)
        feed = self.feed_reader()
        if feed.get('status') == 'ready':self.telegram.queue_signals(feed.get('signals', []))
        self.telegram.send_outbox(token)
        self._gate('telegram:ok', time.time())
        return True


def main():
    from pathlib import Path
    from portal_database import configured_target
    from portal_store import PortalStore
    from signal_feed import read_feed
    key = Path(os.environ['PORTAL_KEY_FILE']).read_bytes().strip()
    store = PortalStore(configured_target(), key)
    feed = os.getenv('PORTAL_SIGNAL_FEED_DB', '')
    worker = Worker(store, lambda: read_feed(feed), os.getenv('PORTAL_ORIGIN', ''))
    stop = threading.Event()
    for sig in (signals_module.SIGTERM, signals_module.SIGINT):signals_module.signal(sig, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                if not worker.once():stop.wait(15)
            except TelegramError:
                print('Telegram could not be reached; retrying.', flush=True);stop.wait(15)
            except Exception:
                print('Telegram worker could not reach the database; retrying.', flush=True);stop.wait(5)
    finally:store.close()


if __name__ == '__main__':main()
