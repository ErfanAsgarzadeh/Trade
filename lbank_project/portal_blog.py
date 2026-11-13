"""Blog articles: stored in the portal database, written in the admin panel, rendered here as plain HTML pages.

Bodies use a small Markdown subset (the same one as frontend/lib/markdown.ts, which the admin preview uses). Every
piece of text is HTML-escaped and links are limited to site paths, anchors and https, so an article cannot inject
markup or scripts. Pages are rendered on the server so search engines see the full article without running scripts.
"""
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import time
import uuid

from portal_audit import record, require_admin

SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
SAFE_HREF = re.compile(r'^(/(?!/)\S*|#\S+|https://\S+)$')
INLINE = re.compile(r'\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)')
LIMITS = dict(slug=80, title=120, description=300, keywords=300, body=60000)
SEED_DIRECTORY = Path(__file__).with_name('frontend') / 'content' / 'blog'
SITE_SUMMARY = 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.'
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
PERSIAN_MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')


class BlogConflict(Exception):
    """The article changed since the editor loaded it, or its address is taken."""


# ---- Markdown subset -------------------------------------------------------------------------------------------

def inline_html(source):
    out = []
    last = 0
    for match in INLINE.finditer(source):
        out.append(html.escape(source[last:match.start()]))
        if match[1] is not None:
            out.append('<strong>' + html.escape(match[1]) + '</strong>')
        elif SAFE_HREF.match(match[3]):
            external = ' rel="noopener" target="_blank"' if match[3].startswith('https://') else ''
            out.append(f'<a href="{html.escape(match[3])}"{external}>{html.escape(match[2])}</a>')
        else:
            out.append(html.escape(match[2]))
        last = match.end()
    out.append(html.escape(source[last:]))
    return ''.join(out)


def slugify(text):
    text = re.sub(r'[^\w\s-]', '', text.strip().lower())
    text = re.sub(r'[\s‌_]+', '-', text)
    return re.sub(r'-+', '-', text).strip('-') or 'section'


def blocks(source):
    """Parse the Markdown subset into ('h2'|'h3', text, id), ('p'|'quote', text) and ('ul'|'ol', [items])."""
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
        if not line:
            flush()
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


def render_body(source):
    parts = []
    for block in blocks(source):
        kind = block[0]
        if kind in ('h2', 'h3'):
            parts.append(f'<{kind} id="{html.escape(block[2])}">{html.escape(block[1])}</{kind}>')
        elif kind == 'quote':
            parts.append(f'<blockquote><p>{inline_html(block[1])}</p></blockquote>')
        elif kind in ('ul', 'ol'):
            parts.append(f'<{kind}>' + ''.join(f'<li>{inline_html(item)}</li>' for item in block[1]) + f'</{kind}>')
        else:
            parts.append(f'<p>{inline_html(block[1])}</p>')
    return ''.join(parts)


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
    keywords = fields.get('keywords') or []
    if isinstance(keywords, str):keywords = re.split(r'[,،]', keywords)
    keywords = [word.strip() for word in keywords if str(word).strip()]
    for key, limit in LIMITS.items():
        size = len(', '.join(keywords)) if key == 'keywords' else len(value[key])
        if size > limit:raise ValueError(f'{key} is too long')
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


class BlogStore:
    def __init__(self, store):self.store = store

    # Public reads: published articles only.
    def published(self, limit=None):
        # A future publish date schedules the article: it appears on that UTC day.
        query = "SELECT * FROM blog_posts WHERE status='published' AND published_on<=? ORDER BY published_on DESC,created DESC,slug"
        with self.store.db() as db:
            rows = db.execute(query + (' LIMIT ?' if limit else ''), (_today(),) + ((limit,) if limit else ())).fetchall()
        return [_row(r, body=False) for r in rows]

    def article(self, slug):
        if not SLUG.match(slug or '') or len(slug) > LIMITS['slug']:return None
        with self.store.db() as db:
            row = db.execute("SELECT * FROM blog_posts WHERE slug=? AND status='published' AND published_on<=?",
                             (slug, _today())).fetchone()
        return _row(row) if row else None

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
            clash = db.execute('SELECT id FROM blog_posts WHERE slug=?', (value['slug'],)).fetchone()
            if clash and clash['id'] != post_id:raise BlogConflict('Another article already uses this address')
            published_on = value['published_on'] or None
            if value['status'] == 'published' and not published_on:
                published_on = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            data = (value['slug'], value['title'], value['description'], json.dumps(value['keywords'], ensure_ascii=False),
                    value['body'], value['status'], published_on, now)
            if post_id is None:
                post_id = str(uuid.uuid4())
                db.execute('INSERT INTO blog_posts(slug,title,description,keywords,body,status,published_on,updated,id,created) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?)', data + (post_id, now))
                action = 'blog_created'
            else:
                current = db.execute('SELECT updated FROM blog_posts WHERE id=?', (post_id,)).fetchone()
                if not current:raise LookupError('Article not found')
                if expected_updated is None or abs(current['updated'] - expected_updated) > 1e-6:
                    raise BlogConflict('Article changed since it was opened; reload it')
                db.execute('UPDATE blog_posts SET slug=?,title=?,description=?,keywords=?,body=?,status=?,published_on=?,updated=? '
                           'WHERE id=?', data + (post_id,))
                action = 'blog_updated'
            record(db, actor, action, post_id, dict(slug=value['slug'], status=value['status']))
        return self.get(post_id)

    def delete(self, actor, post_id, expected_updated):
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            require_admin(db, actor)
            current = db.execute('SELECT slug,updated FROM blog_posts WHERE id=?', (post_id,)).fetchone()
            if not current:raise LookupError('Article not found')
            if abs(current['updated'] - expected_updated) > 1e-6:raise BlogConflict('Article changed since it was opened; reload it')
            db.execute('DELETE FROM blog_posts WHERE id=?', (post_id,))
            record(db, actor, 'blog_deleted', post_id, dict(slug=current['slug']))
        return dict(status='deleted')

    def seed(self, directory=SEED_DIRECTORY):
        """Import the launch articles once, so later admin edits and deletions are never overwritten."""
        with self.store.db() as db:
            self.store.database.begin_write(db, 'blog')
            if db.execute("SELECT 1 FROM service_gate WHERE name='blog:seeded'").fetchone():return 0
            count = 0
            for path in sorted(Path(directory).glob('*.md')) if Path(directory).is_dir() else []:
                if path.name.startswith('_'):continue
                meta, body = split_front_matter(path.read_text(encoding='utf-8'))
                value = _clean(dict(meta, slug=path.stem, body=body, status='published', published_on=meta.get('date')))
                if db.execute('SELECT 1 FROM blog_posts WHERE slug=?', (value['slug'],)).fetchone():continue
                now = time.time()
                db.execute('INSERT INTO blog_posts(id,slug,title,description,keywords,body,status,published_on,created,updated) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?)', (str(uuid.uuid4()), value['slug'], value['title'], value['description'],
                                                          json.dumps(value['keywords'], ensure_ascii=False), value['body'],
                                                          'published', value['published_on'], now, now))
                count += 1
            db.execute("INSERT INTO service_gate(name,next_at) VALUES('blog:seeded',?)", (time.time(),))
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


HEADER = '''<header class="landing-header"><a class="logo" href="/" aria-label="Avina، صفحهٔ اصلی"><img class="logo-mark" src="/portal-assets/avina-mark.png" alt="" width="44" height="24"/><span class="brand-lockup"><span class="brand">AVINA</span><span class="brand-parent">by ARTAX</span></span></a><nav aria-label="ناوبری اصلی"><a href="/#why">چرا آوینا</a><a href="/#backtest">کارنامهٔ پنج‌ساله</a><a href="/#strategies">استراتژی‌ها</a><a href="/#products">پلن‌ها</a><a href="/blog/">بلاگ</a><a href="/#faq">پرسش‌ها</a></nav><div class="landing-header-actions"><div class="theme-switcher"><label for="blog-appearance">ظاهر</label><select id="blog-appearance" data-legacy-theme-switch aria-label="انتخاب ظاهر"><option value="dark">تیره</option><option value="light">روشن</option><option value="system">سیستم</option></select></div><a href="/dashboard/" class="landing-login">ورود به پنل</a><a href="/register/" class="landing-signup">ساخت حساب <span aria-hidden="true">←</span></a></div></header>'''
FOOTER = '''<footer class="landing-footer"><a class="logo" href="/" aria-label="Avina، صفحهٔ اصلی"><img class="logo-mark" src="/portal-assets/avina-mark.png" alt="" width="44" height="24"/><span class="brand-lockup"><span class="brand">AVINA</span><span class="brand-parent">by ARTAX</span></span></a><p>آوینا، ربات معامله‌گر هوشمند از خانوادهٔ ARTAX. معامله در بازارهای مالی ریسک از دست دادن سرمایه دارد و نتایج بک‌تست تضمین‌کنندهٔ بازده آینده نیستند.</p><nav aria-label="پیوندهای پایانی"><a href="/blog/">بلاگ</a><a href="/#faq">پرسش‌های پرتکرار</a><a href="/dashboard/">ورود</a><a href="/register/">ثبت‌نام</a><a href="/backtest/methodology-fa.md">روش بک‌تست</a></nav></footer>'''


def _page(origin, css, canonical, title, description, og_type, extra_head, body):
    url = origin + canonical
    image = origin + '/portal-assets/og-image.png'
    links = ''.join(f'<link rel="stylesheet" href="{_e(href)}"/>' for href in css)
    return ('<!DOCTYPE html><html lang="fa" dir="rtl" data-theme="dark"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>'
            '<meta name="theme-color" content="#100424"/>'
            '<link rel="preload" href="/portal-assets/arabic.woff" as="font" type="font/woff" crossorigin="anonymous"/>'
            f'{links}<script src="/portal-assets/appearance.js"></script>'
            f'<title>{_e(title)}</title><meta name="description" content="{_e(description)}"/>'
            f'<link rel="canonical" href="{_e(url)}"/>'
            '<link rel="icon" href="/portal-assets/favicon.png"/><link rel="apple-touch-icon" href="/portal-assets/apple-touch-icon.png"/>'
            '<link rel="manifest" href="/manifest.webmanifest"/>'
            f'<link rel="alternate" type="application/rss+xml" title="بلاگ آوینا" href="{_e(origin)}/blog/rss.xml"/>'
            f'<meta property="og:type" content="{og_type}"/><meta property="og:site_name" content="Avina"/>'
            f'<meta property="og:locale" content="fa_IR"/><meta property="og:title" content="{_e(title)}"/>'
            f'<meta property="og:description" content="{_e(description)}"/><meta property="og:url" content="{_e(url)}"/>'
            f'<meta property="og:image" content="{_e(image)}"/><meta property="og:image:width" content="1200"/>'
            '<meta property="og:image:height" content="630"/><meta name="twitter:card" content="summary_large_image"/>'
            f'<meta name="twitter:title" content="{_e(title)}"/><meta name="twitter:description" content="{_e(description)}"/>'
            f'<meta name="twitter:image" content="{_e(image)}"/>{extra_head}</head><body>'
            f'<div class="landing blog-page"><a class="skip-link" href="#blog-main">رفتن به محتوا</a>{HEADER}'
            f'<main id="blog-main">{body}</main>{FOOTER}</div></body></html>')


def card(post):
    return (f'<article class="blog-card"><small><time datetime="{_e(post["published_on"])}">{persian_date(post["published_on"])}</time>'
            f'<span aria-hidden="true">·</span><span>{str(post["minutes"]).translate(FA_DIGITS)} دقیقه مطالعه</span></small>'
            f'<h3><a href="/blog/{_e(post["slug"])}/">{_e(post["title"])}</a></h3><p>{_e(post["description"])}</p></article>')


def index_page(origin, css, posts):
    title = 'بلاگ آوینا | آموزش ربات ترید، حد ضرر و مدیریت ریسک'
    description = ('مقاله‌های آموزشی آوینا دربارهٔ ربات معامله‌گر ارز دیجیتال، معاملات فیوچرز، حد ضرر، مدیریت ریسک '
                   'و خواندن نتایج بک‌تست.')
    cards = ''.join(card(post) for post in posts) or '<p>هنوز مقاله‌ای منتشر نشده است.</p>'
    body = ('<section class="blog-hero" aria-labelledby="blog-title"><span class="eyebrow">AVINA JOURNAL</span>'
            '<h1 id="blog-title">بلاگ آوینا</h1><p>راهنماهای کوتاه و بی‌تعارف دربارهٔ ربات ترید، معاملات فیوچرز، حد ضرر و '
            'مدیریت ریسک؛ برای اینکه پیش از سپردن معامله به هر ربات، بدانید چه چیزی را باید بسنجید.</p></section>'
            f'<div class="blog-cards blog-list">{cards}</div>')
    return _page(origin, css, '/blog/', title, description, 'website', '', body)


def article_page(origin, css, post, related):
    url = f'{origin}/blog/{post["slug"]}/'
    title = f'{post["title"]} | بلاگ آوینا'
    parsed = blocks(post['body'])
    headings = [b for b in parsed if b[0] == 'h2']
    contents = ''
    if len(headings) > 2:
        contents = ('<nav class="blog-contents" aria-label="فهرست مطالب"><strong>در این مقاله</strong><ol>'
                    + ''.join(f'<li><a href="#{_e(h[2])}">{_e(h[1])}</a></li>' for h in headings) + '</ol></nav>')
    updated = ''
    if post['updated_on'] > post['published_on']:
        updated = f'<span>به‌روزرسانی <time datetime="{post["updated_on"]}">{persian_date(post["updated_on"])}</time></span>'
    more = ''
    if related:
        more = ('<section class="blog-related" aria-labelledby="related-title"><h2 id="related-title">مقاله‌های دیگر</h2>'
                '<div class="blog-cards">' + ''.join(card(item) for item in related) + '</div></section>')
    body = ('<article class="blog-article"><nav class="blog-breadcrumb" aria-label="مسیر صفحه"><a href="/">آوینا</a>'
            '<span aria-hidden="true">/</span><a href="/blog/">بلاگ</a></nav>'
            f'<header class="blog-article-head"><h1>{_e(post["title"])}</h1><p class="blog-lead">{_e(post["description"])}</p>'
            f'<small><time datetime="{_e(post["published_on"])}">{persian_date(post["published_on"])}</time>'
            f'<span aria-hidden="true">·</span><span>{str(post["minutes"]).translate(FA_DIGITS)} دقیقه مطالعه</span>{updated}</small></header>'
            f'{contents}<div class="blog-body">{render_body(post["body"])}</div>'
            '<aside class="blog-cta" aria-label="شروع با آوینا"><h2>کارنامهٔ آوینا را خودتان بسنجید.</h2>'
            '<p>بک‌تست پنج‌ساله، دادهٔ روزانه و روش محاسبه را ببینید و اگر قانع شدید، حساب بسازید. '
            'سرمایه در حساب صرافی خودتان می‌ماند.</p><div><a class="landing-primary" href="/#backtest">دیدن کارنامه ←</a>'
            '<a class="landing-secondary" href="/register/">ساخت حساب ←</a></div></aside>'
            '<p class="blog-disclaimer">این مقاله آموزشی است و توصیهٔ سرمایه‌گذاری نیست. معامله در بازار فیوچرز ریسک از دست دادن '
            f'سرمایه دارد.</p></article>{more}')
    organization = {'@type': 'Organization', '@id': origin + '/#org', 'name': 'Avina', 'url': origin + '/',
                    'logo': origin + '/portal-assets/icon-512.png'}
    article = {'@type': 'BlogPosting', 'headline': post['title'], 'description': post['description'],
               'datePublished': post['published_on'], 'dateModified': max(post['updated_on'], post['published_on']),
               'inLanguage': 'fa', 'keywords': '، '.join(post['keywords']), 'url': url, 'mainEntityOfPage': url,
               'image': origin + '/portal-assets/og-image.png', 'author': {'@id': origin + '/#org'},
               'publisher': {'@id': origin + '/#org'}}
    crumbs = {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'آوینا', 'item': origin + '/'},
        {'@type': 'ListItem', 'position': 2, 'name': 'بلاگ', 'item': origin + '/blog/'},
        {'@type': 'ListItem', 'position': 3, 'name': post['title'], 'item': url}]}
    head = (f'<meta property="article:published_time" content="{_e(post["published_on"])}"/>'
            + (f'<meta name="keywords" content="{_e(", ".join(post["keywords"]))}"/>' if post['keywords'] else '')
            + _ld({'@context': 'https://schema.org', '@graph': [organization, article, crumbs]}))
    return _page(origin, css, f'/blog/{post["slug"]}/', title, post['description'], 'article', head, body)


def rss_xml(origin, posts):
    items = []
    for post in posts[:30]:
        link = _e(f'{origin}/blog/{post["slug"]}/')
        day = datetime.strptime(post['published_on'], '%Y-%m-%d').strftime('%a, %d %b %Y 00:00:00 +0000')
        items.append(f'<item><title>{_e(post["title"])}</title><link>{link}</link><guid>{link}</guid>'
                     f'<pubDate>{day}</pubDate><description>{_e(post["description"])}</description></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>بلاگ آوینا</title>'
            f'<link>{_e(origin)}/blog/</link><description>{_e(SITE_SUMMARY)}</description><language>fa</language>'
            + ''.join(items) + '</channel></rss>')
