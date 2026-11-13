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


# Search engines index only the public pages; these head tags need the site's real origin, which the static export
# does not know at build time.
PUBLIC_PAGES = {'index.html': '/', 'register.html': '/register/'}
SITE_NAME = 'Avina'
SITE_SUMMARY = 'آوینا، ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز از خانوادهٔ ARTAX.'


def seo_head(origin, filename):
    """Canonical, social image and site-level JSON-LD for a public page (JSON-LD is data, so CSP needs no hash)."""
    url = origin + PUBLIC_PAGES[filename]
    image = origin + '/portal-assets/og-image.png'
    tags = [f'<link rel="canonical" href="{html.escape(url)}"/>',
            f'<meta property="og:url" content="{html.escape(url)}"/>',
            f'<meta property="og:image" content="{html.escape(image)}"/>',
            '<meta property="og:image:width" content="1200"/>', '<meta property="og:image:height" content="630"/>',
            f'<meta name="twitter:image" content="{html.escape(image)}"/>']
    if filename == 'index.html':
        brand = {'@type': 'Organization', '@id': origin + '/#org', 'name': SITE_NAME, 'alternateName': ['آوینا', 'AVINA by ARTAX'],
                 'url': origin + '/', 'logo': origin + '/portal-assets/icon-512.png',
                 'parentOrganization': {'@type': 'Organization', 'name': 'ARTAX'}}
        site = {'@type': 'WebSite', '@id': origin + '/#site', 'url': origin + '/', 'name': SITE_NAME,
                'alternateName': 'آوینا', 'inLanguage': 'fa', 'description': SITE_SUMMARY, 'publisher': {'@id': origin + '/#org'}}
        app = {'@type': 'SoftwareApplication', 'name': SITE_NAME, 'alternateName': 'آوینا', 'url': origin + '/',
               'applicationCategory': 'FinanceApplication', 'operatingSystem': 'Web', 'inLanguage': 'fa',
               'description': SITE_SUMMARY, 'image': image, 'publisher': {'@id': origin + '/#org'}}
        data = json.dumps({'@context': 'https://schema.org', '@graph': [brand, site, app]}, ensure_ascii=False)
        tags.append('<script type="application/ld+json">' + data.replace('<', '\\u003c') + '</script>')
    return ''.join(tags)


@lru_cache(maxsize=8)
def _public_page(origin, path, modified, size):
    page = _read_index(path, modified, size)[0]
    return page.replace('</head>', seo_head(origin, Path(path).name) + '</head>', 1)


def public_page(directory, filename, origin):
    """The exported page with its origin-dependent SEO head tags added."""
    path = Path(directory) / filename
    stat = path.stat()
    return _public_page(origin, str(path), stat.st_mtime_ns, stat.st_size)


def robots_txt(origin):
    return f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /admin\n\nSitemap: {origin}/sitemap.xml\n'


def sitemap_xml(origin, directory):
    rows = []
    for filename, path in PUBLIC_PAGES.items():
        try:day = datetime.fromtimestamp((Path(directory) / filename).stat().st_mtime, timezone.utc).date().isoformat()
        except OSError:continue
        rows.append(f'<url><loc>{html.escape(origin + path)}</loc><lastmod>{day}</lastmod></url>')
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(rows) + '</urlset>'
