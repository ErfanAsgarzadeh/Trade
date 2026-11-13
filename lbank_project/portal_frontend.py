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
# rendered by portal_blog.py.
PUBLIC_PAGES = {'/': 'index.html', '/register/': 'register.html'}
SITE_NAME = 'Avina'
SITE_SUMMARY = 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.'


def public_file(path):
    """(canonical path, exported file) for a public page URL with or without its trailing slash; None otherwise."""
    key = path if path.endswith('/') else path + '/'
    return (key, PUBLIC_PAGES[key]) if key in PUBLIC_PAGES else None


def _ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'


def seo_head(origin, canonical):
    """Canonical, social image and JSON-LD for a public page (JSON-LD is data, so the CSP needs no hash for it)."""
    url = origin + canonical
    image = origin + '/portal-assets/og-image.png'
    tags = [f'<link rel="canonical" href="{html.escape(url)}"/>',
            f'<meta property="og:url" content="{html.escape(url)}"/>',
            f'<meta property="og:image" content="{html.escape(image)}"/>',
            '<meta property="og:image:width" content="1200"/>', '<meta property="og:image:height" content="630"/>',
            f'<meta name="twitter:image" content="{html.escape(image)}"/>',
            f'<link rel="alternate" type="application/rss+xml" title="بلاگ آوینا" href="{html.escape(origin)}/blog/rss.xml"/>']
    if canonical == '/':
        organization = {'@type': 'Organization', '@id': origin + '/#org', 'name': SITE_NAME,
                        'alternateName': ['آوینا', 'AVINA by ARTAX'], 'url': origin + '/', 'logo': origin + '/portal-assets/icon-512.png',
                        'parentOrganization': {'@type': 'Organization', 'name': 'ARTAX'}}
        site = {'@type': 'WebSite', '@id': origin + '/#site', 'url': origin + '/', 'name': SITE_NAME,
                'alternateName': 'آوینا', 'inLanguage': 'fa', 'description': SITE_SUMMARY, 'publisher': {'@id': origin + '/#org'}}
        app = {'@type': 'SoftwareApplication', 'name': SITE_NAME, 'alternateName': 'آوینا', 'url': origin + '/',
               'applicationCategory': 'FinanceApplication', 'operatingSystem': 'Web', 'inLanguage': 'fa',
               'description': SITE_SUMMARY, 'image': image, 'publisher': {'@id': origin + '/#org'}}
        tags.append(_ld({'@context': 'https://schema.org', '@graph': [organization, site, app]}))
    return ''.join(tags)


@lru_cache(maxsize=8)
def _public_page(origin, canonical, path, modified, size):
    page = _read_index(path, modified, size)[0]
    return page.replace('</head>', seo_head(origin, canonical) + '</head>', 1)


def public_page(directory, path, origin):
    """The exported public page for a URL path with its SEO head tags; LookupError if no such page, OSError if unbuilt."""
    found = public_file(path)
    if not found:raise LookupError(path)
    canonical, filename = found
    file = Path(directory) / filename
    stat = file.stat()
    return _public_page(origin, canonical, str(file), stat.st_mtime_ns, stat.st_size)


def robots_txt(origin):
    return f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /admin\n\nSitemap: {origin}/sitemap.xml\n'


def sitemap_xml(origin, directory, posts=()):
    """Public pages plus published blog articles (dicts with slug and updated_on)."""
    rows = []
    for path, filename in PUBLIC_PAGES.items():
        try:day = datetime.fromtimestamp((Path(directory) / filename).stat().st_mtime, timezone.utc).date().isoformat()
        except OSError:continue
        rows.append(f'<url><loc>{html.escape(origin + path)}</loc><lastmod>{day}</lastmod></url>')
    if posts:
        newest = max(max(p['updated_on'], p['published_on']) for p in posts)
        rows.append(f'<url><loc>{html.escape(origin)}/blog/</loc><lastmod>{newest}</lastmod></url>')
    for post in posts:
        day = max(post['updated_on'], post['published_on'])
        rows.append(f'<url><loc>{html.escape(origin)}/blog/{html.escape(post["slug"])}/</loc><lastmod>{day}</lastmod></url>')
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(rows) + '</urlset>'
