"""Serve the actual Next.js export with hash-based CSP, without unsafe-inline/eval."""
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from functools import lru_cache
from pathlib import Path


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.inside = 'src' not in dict(attrs)
            self.parts = []

    def handle_data(self, data):
        if self.inside:self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.inside:
            self.scripts.append(''.join(self.parts))
            self.inside = False


@lru_cache(maxsize=4)
def _read_index(path, modified, size):
    html = Path(path).read_text(encoding='utf-8')
    parser = InlineScripts();parser.feed(html)
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
                     for script in parser.scripts})
    return html, ' '.join(hashes)


def frontend_index(directory, filename="index.html"):
    path = Path(directory) / filename
    stat = path.stat()
    return _read_index(str(path), stat.st_mtime_ns, stat.st_size)


# Search engines index only the public pages. Their canonical links and JSON-LD need the site's real origin, which
# the static export does not know at build time, so they are added here when a page is served.
PUBLIC_PAGES = {'/': 'index.html', '/register/': 'register.html', '/blog/': 'blog.html'}
BLOG_PATH = re.compile(r'/blog/([a-z0-9]+(?:-[a-z0-9]+)*)/')
SITE_NAME = 'Avina'
SITE_SUMMARY = 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.'


@lru_cache(maxsize=4)
def _blog_index(path, modified, size):
    posts = json.loads(Path(path).read_text(encoding='utf-8'))
    return {post['slug']: json.dumps(post, ensure_ascii=False, sort_keys=True) for post in posts}


def blog_posts(directory):
    """slug -> post summary JSON, from blog-index.json written by the Next.js build (empty if there is no build)."""
    path = Path(directory) / 'blog-index.json'
    try:stat = path.stat()
    except OSError:return {}
    return _blog_index(str(path), stat.st_mtime_ns, stat.st_size)


def public_file(directory, path):
    """(canonical path, exported file) for a public page URL with or without its trailing slash; None otherwise."""
    key = path if path.endswith('/') else path + '/'
    if key in PUBLIC_PAGES:return key, PUBLIC_PAGES[key]
    match = BLOG_PATH.fullmatch(key)
    if match and match[1] in blog_posts(directory):return key, f'blog/{match[1]}.html'
    return None


def _ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'


def seo_head(origin, canonical, post=None):
    """Canonical, social image and JSON-LD for a public page (JSON-LD is data, so the CSP needs no hash for it)."""
    url = origin + canonical
    image = origin + '/portal-assets/og-image.png'
    tags = [f'<link rel="canonical" href="{html.escape(url)}"/>',
            f'<meta property="og:url" content="{html.escape(url)}"/>',
            f'<meta property="og:image" content="{html.escape(image)}"/>',
            '<meta property="og:image:width" content="1200"/>', '<meta property="og:image:height" content="630"/>',
            f'<meta name="twitter:image" content="{html.escape(image)}"/>',
            f'<link rel="alternate" type="application/rss+xml" title="بلاگ آوینا" href="{html.escape(origin)}/blog/rss.xml"/>']
    organization = {'@type': 'Organization', '@id': origin + '/#org', 'name': SITE_NAME,
                    'alternateName': ['آوینا', 'AVINA by ARTAX'], 'url': origin + '/', 'logo': origin + '/portal-assets/icon-512.png',
                    'parentOrganization': {'@type': 'Organization', 'name': 'ARTAX'}}
    if canonical == '/':
        site = {'@type': 'WebSite', '@id': origin + '/#site', 'url': origin + '/', 'name': SITE_NAME,
                'alternateName': 'آوینا', 'inLanguage': 'fa', 'description': SITE_SUMMARY, 'publisher': {'@id': origin + '/#org'}}
        app = {'@type': 'SoftwareApplication', 'name': SITE_NAME, 'alternateName': 'آوینا', 'url': origin + '/',
               'applicationCategory': 'FinanceApplication', 'operatingSystem': 'Web', 'inLanguage': 'fa',
               'description': SITE_SUMMARY, 'image': image, 'publisher': {'@id': origin + '/#org'}}
        tags.append(_ld({'@context': 'https://schema.org', '@graph': [organization, site, app]}))
    elif post:
        article = {'@type': 'BlogPosting', 'headline': post['title'], 'description': post['description'],
                   'datePublished': post['date'], 'dateModified': post['updated'], 'inLanguage': 'fa',
                   'keywords': '، '.join(post.get('keywords', [])), 'url': url, 'mainEntityOfPage': url, 'image': image,
                   'author': {'@id': origin + '/#org'}, 'publisher': {'@id': origin + '/#org'}}
        crumbs = {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'آوینا', 'item': origin + '/'},
            {'@type': 'ListItem', 'position': 2, 'name': 'بلاگ', 'item': origin + '/blog/'},
            {'@type': 'ListItem', 'position': 3, 'name': post['title'], 'item': url}]}
        tags.append(_ld({'@context': 'https://schema.org', '@graph': [organization, article, crumbs]}))
    return ''.join(tags)


@lru_cache(maxsize=32)
def _public_page(origin, canonical, path, modified, size, post):
    page = _read_index(path, modified, size)[0]
    head = seo_head(origin, canonical, json.loads(post) if post else None)
    return page.replace('</head>', head + '</head>', 1)


def public_page(directory, path, origin):
    """The exported public page for a URL path with its SEO head tags; LookupError if no such page, OSError if unbuilt."""
    found = public_file(directory, path)
    if not found:raise LookupError(path)
    canonical, filename = found
    file = Path(directory) / filename
    stat = file.stat()
    post = blog_posts(directory).get(canonical.split('/')[2]) if canonical.startswith('/blog/') and canonical != '/blog/' else None
    return _public_page(origin, canonical, str(file), stat.st_mtime_ns, stat.st_size, post)


def robots_txt(origin):
    return f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /admin\n\nSitemap: {origin}/sitemap.xml\n'


def _day(path):
    try:return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).date().isoformat()
    except OSError:return None


def sitemap_xml(origin, directory):
    rows = []
    for path, filename in PUBLIC_PAGES.items():
        day = _day(Path(directory) / filename)
        if day:rows.append(f'<url><loc>{html.escape(origin + path)}</loc><lastmod>{day}</lastmod></url>')
    for slug, post in blog_posts(directory).items():
        rows.append(f'<url><loc>{html.escape(origin)}/blog/{slug}/</loc><lastmod>{json.loads(post)["updated"]}</lastmod></url>')
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(rows) + '</urlset>'


def rss_xml(origin, directory):
    """RSS 2.0 feed of the blog, newest first, for feed readers and aggregators."""
    posts = sorted((json.loads(post) for post in blog_posts(directory).values()), key=lambda p: (p['date'], p['slug']), reverse=True)
    items = []
    for post in posts[:30]:
        link = html.escape(f'{origin}/blog/{post["slug"]}/')
        day = datetime.strptime(post['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc).strftime('%a, %d %b %Y 00:00:00 +0000')
        items.append(f'<item><title>{html.escape(post["title"])}</title><link>{link}</link><guid>{link}</guid>'
                     f'<pubDate>{day}</pubDate><description>{html.escape(post["description"])}</description></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>بلاگ آوینا</title>'
            f'<link>{html.escape(origin)}/blog/</link><description>{html.escape(SITE_SUMMARY)}</description><language>fa</language>'
            + ''.join(items) + '</channel></rss>')
