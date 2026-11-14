"""Blog articles in Persian and English: stored in the portal database, written in the admin panel, rendered here as
plain HTML pages. Persian lives under /blog/ and English under /en/blog/; articles with the same address in both
languages are linked to each other with hreflang.

Bodies use a small Markdown subset (the same one as frontend/lib/markdown.ts, which the admin preview uses). Every
piece of text is HTML-escaped and links are limited to site paths, anchors and https, so an article cannot inject
markup or scripts. Pages are rendered on the server so search engines see the full article without running scripts.
"""
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import secrets
import time
import uuid

from portal_audit import record, require_admin

SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
SAFE_HREF = re.compile(r'^(/(?!/)\S*|#\S+|https://\S+)$')
# Images: ![alt](/blog-media/<id>.webp "optional caption"). Only images uploaded to this site are allowed.
IMAGE_SRC = re.compile(r'^/blog-media/([a-f0-9]{16,32})\.webp$')
IMAGE = r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)'
IMAGE_LINE = re.compile('^' + IMAGE + '$')
INLINE = re.compile(IMAGE + r'|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)')
LIMITS = dict(slug=80, title=120, description=300, keywords=300, body=60000)
SEED_DIRECTORY = Path(__file__).with_name('frontend') / 'content' / 'blog'
SITE_SUMMARY = {'fa': 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.',
                'en': 'Avina, a smart crypto and futures trading bot from the ARTAX family.'}
LANGS = ('fa', 'en')
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
PERSIAN_MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')


class BlogConflict(Exception):
    """The article changed since the editor loaded it, or its address is taken."""


# ---- Markdown subset -------------------------------------------------------------------------------------------

def image_html(alt, src, title, sizes, inline=False):
    """An uploaded image with its stored size (no layout shift) and lazy loading; anything else stays as text."""
    match = IMAGE_SRC.match(src or '')
    if not match or match[1] not in sizes:return html.escape(alt or '')
    width, height = sizes[match[1]]
    css = ' class="blog-inline-image"' if inline else ''
    tag = (f'<img{css} src="{html.escape(src)}" alt="{html.escape(alt or "")}" width="{width}" height="{height}" '
           'loading="lazy" decoding="async"/>')
    if inline:return tag
    caption = f'<figcaption>{html.escape(title)}</figcaption>' if title else ''
    return f'<figure class="blog-figure">{tag}{caption}</figure>'


def inline_html(source, sizes=None):
    out = []
    last = 0
    for match in INLINE.finditer(source):
        out.append(html.escape(source[last:match.start()]))
        if match[2] is not None:
            out.append(image_html(match[1], match[2], match[3], sizes or {}, inline=True))
        elif match[4] is not None:
            out.append('<strong>' + html.escape(match[4]) + '</strong>')
        elif SAFE_HREF.match(match[6]):
            external = ' rel="noopener" target="_blank"' if match[6].startswith('https://') else ''
            out.append(f'<a href="{html.escape(match[6])}"{external}>{html.escape(match[5])}</a>')
        else:
            out.append(html.escape(match[5]))
        last = match.end()
    out.append(html.escape(source[last:]))
    return ''.join(out)


def slugify(text):
    text = re.sub(r'[^\w\s-]', '', text.strip().lower())
    text = re.sub(r'[\s‌_]+', '-', text)
    return re.sub(r'-+', '-', text).strip('-') or 'section'


def blocks(source):
    """Parse the Markdown subset into ('h2'|'h3', text, id), ('p'|'quote', text), ('ul'|'ol', [items]) and
    ('figure', alt, src, caption) for an image on a line of its own."""
    out, paragraph, listing, ids = [], [], None, {}

    def flush():
        nonlocal paragraph, listing
        if paragraph:
            text = ' '.join(paragraph)
            out.append(('quote', text[2:]) if text.startswith('> ') else ('p', text))
            paragraph = []
        if listing:
            out.append(listing)
            listing = None

    for raw in source.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        heading = re.match(r'^(##|###) (.+)$', line)
        item = re.match(r'^(?:(-)|\d+\.) (.+)$', line)
        figure = IMAGE_LINE.match(line)
        if not line:
            flush()
        elif figure:
            flush()
            out.append(('figure', figure[1], figure[2], figure[3] or ''))
        elif heading:
            flush()
            base = slugify(heading[2])
            seen = ids.get(base, 0)
            ids[base] = seen + 1
            out.append(('h2' if heading[1] == '##' else 'h3', heading[2], f'{base}-{seen + 1}' if seen else base))
        elif item:
            kind = 'ul' if item[1] else 'ol'
            if paragraph or (listing and listing[0] != kind):
                flush()
            listing = listing or (kind, [])
            listing[1].append(item[2])
        else:
            if listing:
                flush()
            paragraph.append(line)
    flush()
    return out


def image_ids(source):
    """Ids of the uploaded images an article refers to, in order of appearance."""
    return list(dict.fromkeys(re.findall(r'/blog-media/([a-f0-9]{16,32})\.webp', source or '')))


def render_body(source, sizes=None):
    """sizes maps image id to (width, height); images missing from it render as their alt text."""
    sizes = sizes or {}
    parts = []
    for block in blocks(source):
        kind = block[0]
        if kind in ('h2', 'h3'):
            parts.append(f'<{kind} id="{html.escape(block[2])}">{html.escape(block[1])}</{kind}>')
        elif kind == 'figure':
            parts.append(image_html(block[1], block[2], block[3], sizes))
        elif kind == 'quote':
            parts.append(f'<blockquote><p>{inline_html(block[1], sizes)}</p></blockquote>')
        elif kind in ('ul', 'ol'):
            parts.append(f'<{kind}>' + ''.join(f'<li>{inline_html(item, sizes)}</li>' for item in block[1]) + f'</{kind}>')
        else:
            parts.append(f'<p>{inline_html(block[1], sizes)}</p>')
    return ''.join(parts)


# ---- Images ----------------------------------------------------------------------------------------------------

MAX_UPLOAD = 10 * 1024 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000


def process_image(raw):
    """Re-encode an upload as WebP: at most 1600 px a side, upright, with no EXIF or GPS metadata. ValueError otherwise."""
    import io
    import warnings
    from PIL import Image, ImageOps
    if not raw or len(raw) > MAX_UPLOAD:raise ValueError('Image too large')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP', 'GIF'):raise ValueError('Unsupported image type')
                if source.width * source.height > MAX_PIXELS:raise ValueError('Image has too many pixels')
                image = ImageOps.exif_transpose(source)
                alpha = image.mode in ('RGBA', 'LA', 'PA') or (image.mode == 'P' and 'transparency' in image.info)
                image = image.convert('RGBA' if alpha else 'RGB')
                image.thumbnail((MAX_SIDE, MAX_SIDE))
                out = io.BytesIO()
                image.save(out, 'WEBP', quality=82, method=4)
    except ValueError:
        raise
    except Exception as exc:  # Pillow raises many types for corrupt or hostile files.
        raise ValueError('Not a readable image') from exc
    return out.getvalue(), image.width, image.height


def reading_minutes(body):
    return max(1, round(len(body.split()) / 200))


def _div(a, b):return int(a / b)  # truncating division, as in the reference jalaali-js algorithm


def _mod(a, b):return a - _div(a, b) * b


JALAALI_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


def _jal_cal(jy):
    gy, leap_j, jp, jump = jy + 621, -14, JALAALI_BREAKS[0], 0
    for jm in JALAALI_BREAKS[1:]:
        jump = jm - jp
        if jy < jm:break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    return (4 if leap == -1 else leap), gy, march


def _g2d(gy, gm, gd):
    d = (_div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408)
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def to_jalaali(gy, gm, gd):
    """Gregorian to Solar Hijri (jalaali-js algorithm)."""
    jdn = _g2d(gy, gm, gd)
    jy = gy - 621
    leap, _, march = _jal_cal(jy)
    k = jdn - _g2d(gy, 3, march)
    if k >= 0:
        if k <= 185:return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def persian_date(day):
    """Gregorian YYYY-MM-DD as a Solar Hijri date, e.g. ۲۲ آبان ۱۴۰۵."""
    year, month, dom = to_jalaali(*(int(part) for part in day.split('-')))
    return f'{dom} {PERSIAN_MONTHS[month - 1]} {year}'.translate(FA_DIGITS)


# ---- Storage ---------------------------------------------------------------------------------------------------

def _clean(fields):
    """Validated article fields; ValueError names the first problem."""
    value = {key: str(fields.get(key) or '').strip() for key in ('slug', 'title', 'description', 'body', 'status', 'published_on')}
    value['lang'] = str(fields.get('lang') or 'fa')
    keywords = fields.get('keywords') or []
    if isinstance(keywords, str):keywords = re.split(r'[,،]', keywords)
    keywords = [word.strip() for word in keywords if str(word).strip()]
    for key, limit in LIMITS.items():
        size = len(', '.join(keywords)) if key == 'keywords' else len(value[key])
        if size > limit:raise ValueError(f'{key} is too long')
    if value['lang'] not in LANGS:raise ValueError('lang must be fa or en')
    if not SLUG.match(value['slug']):raise ValueError('slug must be lowercase latin words and dashes')
    if not value['title'] or not value['description'] or not value['body']:raise ValueError('title, description and body are required')
    if value['status'] not in ('draft', 'published'):raise ValueError('status must be draft or published')
    if value['published_on'] and not DAY.match(value['published_on']):raise ValueError('published_on must be YYYY-MM-DD')
    value['keywords'] = keywords
    return value


def _row(row, body=True):
    item = dict(row)
    item['keywords'] = json.loads(item['keywords'])
    item['minutes'] = reading_minutes(item['body'])
    item['updated_on'] = datetime.fromtimestamp(item['updated'], timezone.utc).date().isoformat()
    if not body:item.pop('body')
    return item


def _today():return datetime.now(timezone.utc).date().isoformat()


# Launch articles that described how the bots trade. Each pair is replaced once in the stored article, only where the
# original sentence is still unedited, so the trading method is not published.
CONTENT_FIXES = (
    ('fa', 'what-is-a-trading-bot',
     'آوینا ربات معامله‌گری است که سه استراتژی مختلف (شاهین برای شکست روند، موج‌سوار برای پولبک در روند و ققنوس برای الگوهای قیمتی) را روی یک حساب اجرا می‌کند.',
     'آوینا ربات معامله‌گری است که سه موتور معاملاتی مستقل را روی یک حساب اجرا می‌کند.'),
    ('fa', 'futures-stop-loss',
     '- **بر اساس اندیکاتور:** مثلاً آن‌سوی ابر ایچیموکو یا آن‌سوی میانگین متحرک.\n', ''),
)


class BlogStore:
    def __init__(self, store):self.store = store

    # Public reads: published articles only. A future publish date schedules the article for that UTC day.
    def published(self, lang='fa', limit=None):
        query = ("SELECT * FROM blog_posts WHERE lang=? AND status='published' AND published_on<=? "
                 "ORDER BY published_on DESC,created DESC,slug")
        args = (lang, _today()) + ((limit,) if limit else ())
        with self.store.db() as db:
            rows = db.execute(query + (' LIMIT ?' if limit else ''), args).fetchall()
        return [_row(r, body=False) for r in rows]

    def article(self, slug, lang='fa'):
        if lang not in LANGS or not SLUG.match(slug or '') or len(slug) > LIMITS['slug']:return None
        with self.store.db() as db:
            row = db.execute("SELECT * FROM blog_posts WHERE lang=? AND slug=? AND status='published' AND published_on<=?",
                             (lang, slug, _today())).fetchone()
        return _row(row) if row else None

    def translations(self, slug):
        """Languages in which this address is published, for hreflang links."""
        with self.store.db() as db:
            rows = db.execute("SELECT lang FROM blog_posts WHERE slug=? AND status='published' AND published_on<=?",
                              (slug, _today())).fetchall()
        return {row['lang'] for row in rows}

    # Admin.
    def all(self):
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM blog_posts ORDER BY updated DESC,slug').fetchall()
        return [_row(r, body=False) for r in rows]

    def get(self, post_id):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM blog_posts WHERE id=?', (post_id,)).fetchone()
        if not row:raise LookupError('Article not found')
        return _row(row)

    def save(self, actor, fields, post_id=None, expected_updated=None):
        value = _clean(fields)
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            require_admin(db, actor)
            now = max(time.time(), (db.execute('SELECT MAX(updated) AS m FROM blog_posts').fetchone()['m'] or 0) + 1e-6)
            clash = db.execute('SELECT id FROM blog_posts WHERE lang=? AND slug=?', (value['lang'], value['slug'])).fetchone()
            if clash and clash['id'] != post_id:raise BlogConflict('Another article already uses this address')
            published_on = value['published_on'] or None
            if value['status'] == 'published' and not published_on:
                published_on = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            data = (value['lang'], value['slug'], value['title'], value['description'],
                    json.dumps(value['keywords'], ensure_ascii=False), value['body'], value['status'], published_on, now)
            if post_id is None:
                post_id = str(uuid.uuid4())
                db.execute('INSERT INTO blog_posts(lang,slug,title,description,keywords,body,status,published_on,updated,id,created) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?,?)', data + (post_id, now))
                action = 'blog_created'
            else:
                current = db.execute('SELECT updated FROM blog_posts WHERE id=?', (post_id,)).fetchone()
                if not current:raise LookupError('Article not found')
                if expected_updated is None or abs(current['updated'] - expected_updated) > 1e-6:
                    raise BlogConflict('Article changed since it was opened; reload it')
                db.execute('UPDATE blog_posts SET lang=?,slug=?,title=?,description=?,keywords=?,body=?,status=?,published_on=?,'
                           'updated=? WHERE id=?', data + (post_id,))
                action = 'blog_updated'
            record(db, actor, action, post_id, dict(lang=value['lang'], slug=value['slug'], status=value['status']))
        return self.get(post_id)

    def delete(self, actor, post_id, expected_updated):
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            require_admin(db, actor)
            current = db.execute('SELECT lang,slug,updated FROM blog_posts WHERE id=?', (post_id,)).fetchone()
            if not current:raise LookupError('Article not found')
            if abs(current['updated'] - expected_updated) > 1e-6:raise BlogConflict('Article changed since it was opened; reload it')
            db.execute('DELETE FROM blog_posts WHERE id=?', (post_id,))
            record(db, actor, 'blog_deleted', post_id, dict(lang=current['lang'], slug=current['slug']))
        return dict(status='deleted')

    # Images.
    def add_image(self, actor, raw, name=''):
        data, width, height = process_image(raw)
        image_id = secrets.token_hex(12)
        name = re.sub(r'[^\w .-]', '', str(name or ''))[:120]
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            require_admin(db, actor)
            db.execute('INSERT INTO blog_images(id,name,width,height,size,data,created) VALUES(?,?,?,?,?,?,?)',
                       (image_id, name, width, height, len(data), data, time.time()))
            record(db, actor, 'blog_image_added', image_id, dict(name=name, width=width, height=height, size=len(data)))
        return dict(id=image_id, url=f'/blog-media/{image_id}.webp', name=name, width=width, height=height, size=len(data))

    def image(self, image_id):
        """Bytes of one image, or None."""
        if not re.fullmatch(r'[a-f0-9]{16,32}', image_id or ''):return None
        with self.store.db() as db:
            row = db.execute('SELECT data FROM blog_images WHERE id=?', (image_id,)).fetchone()
        return bytes(row['data']) if row else None

    def image_sizes(self, ids):
        ids = [i for i in ids if re.fullmatch(r'[a-f0-9]{16,32}', i)]
        if not ids:return {}
        with self.store.db() as db:
            rows = db.execute('SELECT id,width,height FROM blog_images WHERE id IN (' + ','.join('?' * len(ids)) + ')',
                              tuple(ids)).fetchall()
        return {row['id']: (row['width'], row['height']) for row in rows}

    def images(self):
        """All uploads, newest first, with the articles that use each one."""
        with self.store.db() as db:
            rows = db.execute('SELECT id,name,width,height,size,created FROM blog_images ORDER BY created DESC').fetchall()
            posts = db.execute('SELECT id,lang,slug,title,body FROM blog_posts').fetchall()
        used = {}
        for post in posts:
            for image_id in image_ids(post['body']):
                used.setdefault(image_id, []).append(dict(id=post['id'], lang=post['lang'], slug=post['slug'], title=post['title']))
        return [dict(row, url=f'/blog-media/{row["id"]}.webp', used_in=used.get(row['id'], [])) for row in rows]

    def delete_image(self, actor, image_id):
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            require_admin(db, actor)
            if not db.execute('SELECT 1 FROM blog_images WHERE id=?', (image_id,)).fetchone():raise LookupError('Image not found')
            for post in db.execute('SELECT body FROM blog_posts').fetchall():
                if image_id in image_ids(post['body']):raise BlogConflict('Image is used in an article')
            db.execute('DELETE FROM blog_images WHERE id=?', (image_id,))
            record(db, actor, 'blog_image_deleted', image_id)
        return dict(status='deleted')

    def seed(self, directory=SEED_DIRECTORY):
        """Import each language's launch articles once, so later admin edits and deletions are never overwritten."""
        count = 0
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            for lang, folder, flag in (('fa', Path(directory), 'blog:seeded'), ('en', Path(directory) / 'en', 'blog:seeded:en')):
                if db.execute('SELECT 1 FROM service_gate WHERE name=?', (flag,)).fetchone():continue
                for path in sorted(folder.glob('*.md')) if folder.is_dir() else []:
                    if path.name.startswith('_'):continue
                    meta, body = split_front_matter(path.read_text(encoding='utf-8'))
                    value = _clean(dict(meta, lang=lang, slug=path.stem, body=body, status='published', published_on=meta.get('date')))
                    if db.execute('SELECT 1 FROM blog_posts WHERE lang=? AND slug=?', (lang, value['slug'])).fetchone():continue
                    now = time.time()
                    db.execute('INSERT INTO blog_posts(id,lang,slug,title,description,keywords,body,status,published_on,created,updated) '
                               'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               (str(uuid.uuid4()), lang, value['slug'], value['title'], value['description'],
                                json.dumps(value['keywords'], ensure_ascii=False), value['body'], 'published',
                                value['published_on'], now, now))
                    count += 1
                db.execute('INSERT INTO service_gate(name,next_at) VALUES(?,?)', (flag, time.time()))
            if not db.execute("SELECT 1 FROM service_gate WHERE name='blog:fix:methods'").fetchone():
                for lang, slug, old, new in CONTENT_FIXES:
                    row = db.execute('SELECT id,body FROM blog_posts WHERE lang=? AND slug=?', (lang, slug)).fetchone()
                    if row and old in row['body']:
                        db.execute('UPDATE blog_posts SET body=? WHERE id=?', (row['body'].replace(old, new), row['id']))
                db.execute("INSERT INTO service_gate(name,next_at) VALUES('blog:fix:methods',?)", (time.time(),))
        return count


def split_front_matter(source):
    source = source.replace('\r\n', '\n')
    match = re.match(r'^---\n(.*?)\n---\n?', source, re.S)
    if not match:raise ValueError('Blog post is missing its front matter')
    meta = {}
    for line in match[1].split('\n'):
        pair = re.match(r'^([a-z_]+):\s*(.*)$', line.strip())
        if pair:meta[pair[1]] = re.sub(r'^"(.*)"$', r'\1', pair[2])
    return meta, source[match.end():]


# ---- Pages -----------------------------------------------------------------------------------------------------

def _e(value):return html.escape(str(value), quote=True)


def _ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'


def stylesheets(index_html):
    """The Next.js build's stylesheet links, so server-rendered pages share the site's exact look."""
    return re.findall(r'<link rel="stylesheet" href="(/_next/static/css/[A-Za-z0-9._-]+\.css)"', index_html)


def path(lang, value):
    """A site path in a language: Persian at the root, English under /en."""
    return '/en' + value if lang == 'en' else value


def blog_path(lang, slug=None):
    return path(lang, '/blog/' + (slug + '/' if slug else ''))


def date_label(day, lang):
    if lang == 'en':
        d = datetime.strptime(day, '%Y-%m-%d')
        return f'{d.strftime("%B")} {d.day}, {d.year}'
    return persian_date(day)


def minutes_label(minutes, lang):
    return f'{minutes} min read' if lang == 'en' else f'{str(minutes).translate(FA_DIGITS)} دقیقه مطالعه'


TEXT = {
    'fa': dict(home='Avina، صفحهٔ اصلی', nav='ناوبری اصلی', why='چرا آوینا', record='کارنامهٔ پنج‌ساله', plans='پلن‌ها',
               blog='بلاگ', faq='پرسش‌ها', theme='ظاهر', choose_theme='انتخاب ظاهر', dark='تیره', light='روشن', system='سیستم',
               signin='ورود به پنل', signup='ساخت حساب', skip='رفتن به محتوا', other='English',
               footer='آوینا، ربات معامله‌گر هوشمند از خانوادهٔ ARTAX. معامله در بازارهای مالی ریسک از دست دادن سرمایه دارد و نتایج بک‌تست تضمین‌کنندهٔ بازده آینده نیستند.',
               footer_nav='پیوندهای پایانی', faq_long='پرسش‌های پرتکرار', login='ورود', register='ثبت‌نام', method='روش بک‌تست',
               index_title='بلاگ آوینا | آموزش ربات ترید، حد ضرر و مدیریت ریسک',
               index_description='مقاله‌های آموزشی آوینا دربارهٔ ربات معامله‌گر ارز دیجیتال، معاملات فیوچرز، حد ضرر، مدیریت ریسک و خواندن نتایج بک‌تست.',
               index_h1='بلاگ آوینا',
               index_lead='راهنماهای کوتاه و بی‌تعارف دربارهٔ ربات ترید، معاملات فیوچرز، حد ضرر و مدیریت ریسک؛ برای اینکه پیش از سپردن معامله به هر ربات، بدانید چه چیزی را باید بسنجید.',
               empty='هنوز مقاله‌ای منتشر نشده است.', suffix=' | بلاگ آوینا', crumbs='مسیر صفحه', brand='آوینا',
               contents='فهرست مطالب', in_article='در این مقاله', updated='به‌روزرسانی', cta_label='شروع با آوینا',
               cta_h2='کارنامهٔ آوینا را خودتان بسنجید.',
               cta_p='بک‌تست پنج‌ساله، دادهٔ روزانه و روش محاسبه را ببینید و اگر قانع شدید، حساب بسازید. سرمایه در حساب صرافی خودتان می‌ماند.',
               cta_record='دیدن کارنامه', cta_signup='ساخت حساب',
               disclaimer='این مقاله آموزشی است و توصیهٔ سرمایه‌گذاری نیست. معامله در بازار فیوچرز ریسک از دست دادن سرمایه دارد.',
               related='مقاله‌های دیگر', rss='بلاگ آوینا', locale='fa_IR'),
    'en': dict(home='Avina home', nav='Main navigation', why='Why Avina', record='Five-year record', plans='Plans',
               blog='Blog', faq='FAQ', theme='Theme', choose_theme='Choose theme', dark='Dark', light='Light', system='System',
               signin='Sign in', signup='Create account', skip='Skip to content', other='فارسی',
               footer='Avina, a smart trading bot from the ARTAX family. Trading financial markets carries the risk of losing capital, and backtest results do not guarantee future returns.',
               footer_nav='Footer links', faq_long='FAQ', login='Sign in', register='Sign up', method='Backtest method',
               index_title='Avina Blog | Trading Bots, Stop-Losses and Risk Management',
               index_description='Guides from Avina on crypto trading bots, futures trading, stop-losses, risk management and reading backtest results.',
               index_h1='The Avina blog',
               index_lead='Short, straight guides on trading bots, futures, stop-losses and risk management, so you know what to check before you hand your trading to any bot.',
               empty='No articles have been published yet.', suffix=' | Avina Blog', crumbs='Breadcrumb', brand='Avina',
               contents='Contents', in_article='In this article', updated='Updated', cta_label='Start with Avina',
               cta_h2='Judge the Avina record for yourself.',
               cta_p='See the five-year backtest, the daily data and the method, and create an account if you are convinced. Your funds stay in your own exchange account.',
               cta_record='See the record', cta_signup='Create account',
               disclaimer='This article is educational and not investment advice. Futures trading carries the risk of losing capital.',
               related='More articles', rss='Avina Blog', locale='en_US'),
}


def _logo(lang):
    return (f'<a class="logo" href="{path(lang, "/")}" aria-label="{_e(TEXT[lang]["home"])}"><img class="logo-mark" '
            'src="/portal-assets/avina-mark.png" alt="" width="44" height="24"/><span class="brand-lockup"><span class="brand">AVINA'
            '</span><span class="brand-parent">by ARTAX</span></span></a>')


def _header(lang, other_href):
    t = TEXT[lang]
    home = path(lang, '/')
    other = 'en' if lang == 'fa' else 'fa'
    return (f'<header class="landing-header">{_logo(lang)}<nav aria-label="{t["nav"]}"><a href="{home}#why">{t["why"]}</a>'
            f'<a href="{home}#backtest">{t["record"]}</a><a href="{home}#products">{t["plans"]}</a>'
            f'<a href="{blog_path(lang)}">{t["blog"]}</a><a href="{home}#faq">{t["faq"]}</a></nav>'
            f'<div class="landing-header-actions"><a class="language-link" href="{_e(other_href)}" hreflang="{other}" lang="{other}">'
            f'{t["other"]}</a><div class="theme-switcher"><label for="blog-appearance">{t["theme"]}</label>'
            f'<select id="blog-appearance" data-legacy-theme-switch aria-label="{t["choose_theme"]}"><option value="dark">{t["dark"]}'
            f'</option><option value="light">{t["light"]}</option><option value="system">{t["system"]}</option></select></div>'
            f'<a href="{path(lang, "/dashboard/")}" class="landing-login">{t["signin"]}</a>'
            f'<a href="{path(lang, "/register/")}" class="landing-signup">{t["signup"]}</a></div></header>')


def _footer(lang):
    t = TEXT[lang]
    method = '/backtest/methodology-en.md' if lang == 'en' else '/backtest/methodology-fa.md'
    return (f'<footer class="landing-footer">{_logo(lang)}<p>{t["footer"]}</p><nav aria-label="{t["footer_nav"]}">'
            f'<a href="{blog_path(lang)}">{t["blog"]}</a><a href="{path(lang, "/")}#faq">{t["faq_long"]}</a>'
            f'<a href="{path(lang, "/dashboard/")}">{t["login"]}</a><a href="{path(lang, "/register/")}">{t["register"]}</a>'
            f'<a href="{method}">{t["method"]}</a></nav></footer>')


def _page(origin, css, lang, canonical, title, description, og_type, extra_head, body, alternates, other_href, image=None):
    """alternates: {lang: path} of this page in each language, for hreflang. image: (path, width, height) to share."""
    url = origin + canonical
    image_path, image_width, image_height = image or ('/portal-assets/og-image.png', 1200, 630)
    image = origin + image_path
    links = ''.join(f'<link rel="stylesheet" href="{_e(href)}"/>' for href in css)
    hreflang = ''.join(f'<link rel="alternate" hreflang="{code}" href="{_e(origin + href)}"/>' for code, href in alternates.items())
    if 'fa' in alternates:hreflang += f'<link rel="alternate" hreflang="x-default" href="{_e(origin + alternates["fa"])}"/>'
    t = TEXT[lang]
    return (f'<!DOCTYPE html><html lang="{lang}" dir="{"ltr" if lang == "en" else "rtl"}" data-theme="dark"><head>'
            '<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>'
            '<meta name="theme-color" content="#100424"/>'
            '<link rel="preload" href="/portal-assets/arabic.woff" as="font" type="font/woff" crossorigin="anonymous"/>'
            f'{links}<script src="/portal-assets/appearance.js"></script>'
            f'<title>{_e(title)}</title><meta name="description" content="{_e(description)}"/>'
            f'<link rel="canonical" href="{_e(url)}"/>{hreflang}'
            '<link rel="icon" href="/portal-assets/favicon.png"/><link rel="apple-touch-icon" href="/portal-assets/apple-touch-icon.png"/>'
            '<link rel="manifest" href="/manifest.webmanifest"/>'
            f'<link rel="alternate" type="application/rss+xml" title="{_e(t["rss"])}" href="{_e(origin + blog_path(lang))}rss.xml"/>'
            f'<meta property="og:type" content="{og_type}"/><meta property="og:site_name" content="Avina"/>'
            f'<meta property="og:locale" content="{t["locale"]}"/><meta property="og:title" content="{_e(title)}"/>'
            f'<meta property="og:description" content="{_e(description)}"/><meta property="og:url" content="{_e(url)}"/>'
            f'<meta property="og:image" content="{_e(image)}"/><meta property="og:image:width" content="{image_width}"/>'
            f'<meta property="og:image:height" content="{image_height}"/><meta name="twitter:card" content="summary_large_image"/>'
            f'<meta name="twitter:title" content="{_e(title)}"/><meta name="twitter:description" content="{_e(description)}"/>'
            f'<meta name="twitter:image" content="{_e(image)}"/>{extra_head}</head><body>'
            f'<div class="landing blog-page"><a class="skip-link" href="#blog-main">{t["skip"]}</a>{_header(lang, other_href)}'
            f'<main id="blog-main">{body}</main>{_footer(lang)}</div></body></html>')


def card(post, lang):
    return (f'<article class="blog-card"><small><time datetime="{_e(post["published_on"])}">{date_label(post["published_on"], lang)}'
            f'</time><span aria-hidden="true">·</span><span>{minutes_label(post["minutes"], lang)}</span></small>'
            f'<h3><a href="{blog_path(lang, post["slug"])}">{_e(post["title"])}</a></h3><p>{_e(post["description"])}</p></article>')


def index_page(origin, css, posts, lang='fa'):
    t = TEXT[lang]
    cards = ''.join(card(post, lang) for post in posts) or f'<p>{t["empty"]}</p>'
    body = (f'<section class="blog-hero" aria-labelledby="blog-title"><span class="eyebrow">AVINA JOURNAL</span>'
            f'<h1 id="blog-title">{t["index_h1"]}</h1><p>{t["index_lead"]}</p></section>'
            f'<div class="blog-cards blog-list">{cards}</div>')
    alternates = {code: blog_path(code) for code in LANGS}
    return _page(origin, css, lang, blog_path(lang), t['index_title'], t['index_description'], 'website', '', body,
                 alternates, blog_path('en' if lang == 'fa' else 'fa'))


def article_page(origin, css, post, related, translations=(), lang='fa', sizes=None):
    """sizes maps the article's image ids to (width, height); the first image becomes its sharing image."""
    sizes = sizes or {}
    first = next((i for i in image_ids(post['body']) if i in sizes), None)
    share = (f'/blog-media/{first}.webp', *sizes[first]) if first else None
    t = TEXT[lang]
    canonical = blog_path(lang, post['slug'])
    url = origin + canonical
    title = post['title'] + t['suffix']
    parsed = blocks(post['body'])
    headings = [b for b in parsed if b[0] == 'h2']
    contents = ''
    if len(headings) > 2:
        contents = (f'<nav class="blog-contents" aria-label="{t["contents"]}"><strong>{t["in_article"]}</strong><ol>'
                    + ''.join(f'<li><a href="#{_e(h[2])}">{_e(h[1])}</a></li>' for h in headings) + '</ol></nav>')
    updated = ''
    # Only a real edit after creation counts as an update (imported launch articles are created and stamped together).
    if post['updated_on'] > post['published_on'] and post['updated'] - post['created'] > 60:
        updated = f'<span>{t["updated"]} <time datetime="{post["updated_on"]}">{date_label(post["updated_on"], lang)}</time></span>'
    more = ''
    if related:
        more = (f'<section class="blog-related" aria-labelledby="related-title"><h2 id="related-title">{t["related"]}</h2>'
                '<div class="blog-cards">' + ''.join(card(item, lang) for item in related) + '</div></section>')
    body = (f'<article class="blog-article"><nav class="blog-breadcrumb" aria-label="{t["crumbs"]}"><a href="{path(lang, "/")}">'
            f'{t["brand"]}</a><span aria-hidden="true">/</span><a href="{blog_path(lang)}">{t["blog"]}</a></nav>'
            f'<header class="blog-article-head"><h1>{_e(post["title"])}</h1><p class="blog-lead">{_e(post["description"])}</p>'
            f'<small><time datetime="{_e(post["published_on"])}">{date_label(post["published_on"], lang)}</time>'
            f'<span aria-hidden="true">·</span><span>{minutes_label(post["minutes"], lang)}</span>{updated}</small></header>'
            f'{contents}<div class="blog-body">{render_body(post["body"], sizes)}</div>'
            f'<aside class="blog-cta" aria-label="{t["cta_label"]}"><h2>{t["cta_h2"]}</h2><p>{t["cta_p"]}</p><div>'
            f'<a class="landing-primary" href="{path(lang, "/")}#backtest">{t["cta_record"]}</a>'
            f'<a class="landing-secondary" href="{path(lang, "/register/")}">{t["cta_signup"]}</a></div></aside>'
            f'<p class="blog-disclaimer">{t["disclaimer"]}</p></article>{more}')
    organization = {'@type': 'Organization', '@id': origin + '/#org', 'name': 'Avina', 'url': origin + '/',
                    'logo': origin + '/portal-assets/icon-512.png'}
    article = {'@type': 'BlogPosting', 'headline': post['title'], 'description': post['description'],
               'datePublished': post['published_on'], 'dateModified': max(post['updated_on'], post['published_on']),
               'inLanguage': lang, 'keywords': ', '.join(post['keywords']), 'url': url, 'mainEntityOfPage': url,
               'image': origin + (share[0] if share else '/portal-assets/og-image.png'), 'author': {'@id': origin + '/#org'},
               'publisher': {'@id': origin + '/#org'}}
    crumbs = {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': t['brand'], 'item': origin + path(lang, '/')},
        {'@type': 'ListItem', 'position': 2, 'name': t['blog'], 'item': origin + blog_path(lang)},
        {'@type': 'ListItem', 'position': 3, 'name': post['title'], 'item': url}]}
    head = (f'<meta property="article:published_time" content="{_e(post["published_on"])}"/>'
            + (f'<meta name="keywords" content="{_e(", ".join(post["keywords"]))}"/>' if post['keywords'] else '')
            + _ld({'@context': 'https://schema.org', '@graph': [organization, article, crumbs]}))
    alternates = {code: blog_path(code, post['slug']) for code in LANGS if code in set(translations) | {lang}}
    other = 'en' if lang == 'fa' else 'fa'
    other_href = blog_path(other, post['slug']) if other in translations else blog_path(other)
    return _page(origin, css, lang, canonical, title, post['description'], 'article', head, body, alternates, other_href,
                 share)


def rss_xml(origin, posts, lang='fa'):
    items = []
    for post in posts[:30]:
        link = _e(origin + blog_path(lang, post['slug']))
        day = datetime.strptime(post['published_on'], '%Y-%m-%d').strftime('%a, %d %b %Y 00:00:00 +0000')
        items.append(f'<item><title>{_e(post["title"])}</title><link>{link}</link><guid>{link}</guid>'
                     f'<pubDate>{day}</pubDate><description>{_e(post["description"])}</description></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f'<title>{_e(TEXT[lang]["rss"])}</title><link>{_e(origin + blog_path(lang))}</link>'
            f'<description>{_e(SITE_SUMMARY[lang])}</description><language>{lang}</language>'
            + ''.join(items) + '</channel></rss>')
