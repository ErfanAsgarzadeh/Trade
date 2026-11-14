"""Serve the actual Next.js export with hash-based CSP, without unsafe-inline/eval."""
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
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
# the static export does not know at build time, so they are added here when a page is served. Blog pages are
# rendered by portal_blog.py. Persian pages are at the root and English pages under /en/.
PUBLIC_PAGES = {'/': 'index.html', '/register/': 'register.html', '/en/': 'en.html', '/en/register/': 'en/register.html'}
SITE_NAME = 'Avina'
SITE_SUMMARY = {'fa': 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.',
                'en': 'Avina, a smart crypto and futures trading bot from the ARTAX family.'}


def page_lang(path):
    return 'en' if path == '/en' or path.startswith('/en/') else 'fa'


def counterpart(path):
    """The same page in the other language."""
    if page_lang(path) == 'en':return path[3:] or '/'
    return '/en' + path


def localize(page, lang):
    """English pages share the Persian root layout; set the document language and direction before it reaches a browser."""
    if lang != 'en':return page
    return page.replace('<html lang="fa" dir="rtl"', '<html lang="en" dir="ltr"', 1)


def public_file(path):
    """(canonical path, exported file) for a public page URL with or without its trailing slash; None otherwise."""
    key = path if path.endswith('/') else path + '/'
    return (key, PUBLIC_PAGES[key]) if key in PUBLIC_PAGES else None


def _ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'


def seo_head(origin, canonical):
    """Canonical, hreflang, social image and JSON-LD for a public page (JSON-LD is data, so the CSP needs no hash)."""
    lang = page_lang(canonical)
    url = origin + canonical
    image = origin + '/portal-assets/og-image.png'
    fa, en = (canonical, counterpart(canonical)) if lang == 'fa' else (counterpart(canonical), canonical)
    blog = origin + ('/en/blog/' if lang == 'en' else '/blog/')
    tags = [f'<link rel="canonical" href="{html.escape(url)}"/>',
            f'<link rel="alternate" hreflang="fa" href="{html.escape(origin + fa)}"/>',
            f'<link rel="alternate" hreflang="en" href="{html.escape(origin + en)}"/>',
            f'<link rel="alternate" hreflang="x-default" href="{html.escape(origin + fa)}"/>',
            f'<meta property="og:url" content="{html.escape(url)}"/>',
            f'<meta property="og:image" content="{html.escape(image)}"/>',
            '<meta property="og:image:width" content="1200"/>', '<meta property="og:image:height" content="630"/>',
            f'<meta name="twitter:image" content="{html.escape(image)}"/>',
            f'<link rel="alternate" type="application/rss+xml" title="{"Avina Blog" if lang == "en" else "بلاگ آوینا"}" '
            f'href="{html.escape(blog)}rss.xml"/>']
    if canonical in ('/', '/en/'):
        home = origin + canonical
        organization = {'@type': 'Organization', '@id': origin + '/#org', 'name': SITE_NAME,
                        'alternateName': ['آوینا', 'AVINA by ARTAX'], 'url': origin + '/', 'logo': origin + '/portal-assets/icon-512.png',
                        'parentOrganization': {'@type': 'Organization', 'name': 'ARTAX'}}
        site = {'@type': 'WebSite', '@id': home + '#site', 'url': home, 'name': SITE_NAME,
                'alternateName': 'آوینا', 'inLanguage': lang, 'description': SITE_SUMMARY[lang], 'publisher': {'@id': origin + '/#org'}}
        app = {'@type': 'SoftwareApplication', 'name': SITE_NAME, 'alternateName': 'آوینا', 'url': home,
               'applicationCategory': 'FinanceApplication', 'operatingSystem': 'Web', 'inLanguage': lang,
               'description': SITE_SUMMARY[lang], 'image': image, 'publisher': {'@id': origin + '/#org'}}
        tags.append(_ld({'@context': 'https://schema.org', '@graph': [organization, site, app]}))
    return ''.join(tags)


@lru_cache(maxsize=16)
def _public_page(origin, canonical, path, modified, size):
    page = localize(_read_index(path, modified, size)[0], page_lang(canonical))
    return page.replace('</head>', seo_head(origin, canonical) + '</head>', 1)


def public_page(directory, path, origin):
    """The exported public page for a URL path with its SEO head tags; LookupError if no such page, OSError if unbuilt."""
    found = public_file(path)
    if not found:raise LookupError(path)
    canonical, filename = found
    file = Path(directory) / filename
    stat = file.stat()
    return _public_page(origin, canonical, str(file), stat.st_mtime_ns, stat.st_size)


def private_page(directory, filename):
    """A signed-in page (panel, admin) in its language; never indexed, so no SEO tags."""
    return localize(frontend_index(directory, filename)[0], 'en' if filename.startswith('en/') else 'fa')


def robots_txt(origin):
    return (f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /admin\nDisallow: /en/dashboard\n'
            f'Disallow: /en/admin\n\nSitemap: {origin}/sitemap.xml\n')


def sitemap_xml(origin, directory, posts=None):
    """Public pages plus published blog articles; posts maps a language to its articles (dicts with slug and dates)."""
    posts = posts or {}
    rows = []
    for path, filename in PUBLIC_PAGES.items():
        try:day = datetime.fromtimestamp((Path(directory) / filename).stat().st_mtime, timezone.utc).date().isoformat()
        except OSError:continue
        rows.append(f'<url><loc>{html.escape(origin + path)}</loc><lastmod>{day}</lastmod></url>')
    for lang, items in posts.items():
        base = origin + ('/en/blog/' if lang == 'en' else '/blog/')
        if items:
            newest = max(max(p['updated_on'], p['published_on']) for p in items)
            rows.append(f'<url><loc>{html.escape(base)}</loc><lastmod>{newest}</lastmod></url>')
        for post in items:
            day = max(post['updated_on'], post['published_on'])
            rows.append(f'<url><loc>{html.escape(base + post["slug"])}/</loc><lastmod>{day}</lastmod></url>')
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(rows) + '</urlset>'
