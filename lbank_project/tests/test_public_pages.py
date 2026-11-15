"""Properties every public page must have, checked by iterating over the page list."""
import re
import pytest
from fastapi.testclient import TestClient
import portal_frontend
from portal_server import create_app

ORIGIN = 'http://127.0.0.1:8080'
PAGES = {}


def all_paths():
    return [*portal_frontend.PUBLIC_PAGES, *getattr(portal_frontend, 'SERVER_PAGES', ())]


@pytest.fixture(scope='module')
def client():
    import os
    previous = os.environ.get('PORTAL_RATE_LIMIT_PER_MINUTE')
    os.environ['PORTAL_RATE_LIMIT_PER_MINUTE'] = '100000'
    try:
        with TestClient(create_app(store=object(), origin=ORIGIN, secure=False), base_url=ORIGIN) as c:
            yield c
    finally:
        if previous is None:os.environ.pop('PORTAL_RATE_LIMIT_PER_MINUTE', None)
        else:os.environ['PORTAL_RATE_LIMIT_PER_MINUTE'] = previous


@pytest.mark.parametrize('path', all_paths())
def test_every_public_page_has_the_required_head_and_one_h1(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    page = r.text
    assert len(re.findall(r'<h1[\s>]', page)) == 1, path
    title = re.search(r'<title[^>]*>(.*?)</title>', page, re.S).group(1)
    assert 10 < len(title) <= 70, title
    description = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
    assert 40 < len(description) <= 160, description
    assert f'<link rel="canonical" href="{ORIGIN}{path}"' in page
    for code in ('fa', 'en', 'x-default'):
        assert f'hreflang="{code}"' in page
    assert 'property="og:title"' in page and 'og:image' in page
    assert f'<loc>{ORIGIN}{path}</loc>' in client.get('/sitemap.xml').text
    assert 'lang="en" dir="ltr"' in page if path.startswith('/en') else 'lang="fa" dir="rtl"' in page
    assert 'unsafe-inline' not in r.headers['content-security-policy']
    if 'register' not in path:assert '/forward-test/' in page  # header/footer link (the sign-up form is the portal shell)


@pytest.mark.parametrize('path', all_paths())
def test_titles_and_descriptions_are_unique(client, path):
    pages = PAGES.setdefault('all', {p: client.get(p).text for p in all_paths()})
    title = re.search(r'<title[^>]*>(.*?)</title>', pages[path], re.S).group(1)
    description = re.search(r'<meta name="description" content="([^"]*)"', pages[path]).group(1)
    for other, text in pages.items():
        if other != path:
            assert title != re.search(r'<title[^>]*>(.*?)</title>', text, re.S).group(1)
            assert description != re.search(r'<meta name="description" content="([^"]*)"', text).group(1)


@pytest.mark.parametrize('path', [p for p in all_paths() if p != '/'])
def test_address_without_trailing_slash_redirects_permanently_keeping_the_query(client, path):
    r = client.get(path.rstrip('/') + '?ref=abc', follow_redirects=False)
    assert r.status_code == 308 and r.headers['location'] == path + '?ref=abc'
    assert client.get(path.rstrip('/'), follow_redirects=False).headers['location'] == path


def test_private_pages_and_blog_redirect_to_the_slash_form(client):
    for path in ('/dashboard', '/admin', '/en/dashboard', '/en/admin', '/blog', '/en/blog', '/blog/some-post', '/en/blog/some-post'):
        r = client.get(path + '?x=1', follow_redirects=False)
        assert r.status_code == 308 and r.headers['location'] == path + '/?x=1', path


def test_html_pages_have_a_strong_etag_and_revalidate_with_304(client):
    first = client.get('/en/forward-test/')
    etag = first.headers['etag']
    assert etag.startswith('"') and not etag.startswith('W/')
    again = client.get('/en/forward-test/', headers={'If-None-Match': etag})
    assert again.status_code == 304 and again.content == b'' and 'content-security-policy' in again.headers
    assert again.headers['cache-control'] == 'no-cache'
    assert client.get('/forward-test/').headers['etag'] != etag  # per page and language
    assert client.get('/en/forward-test/', headers={'If-None-Match': '"other"'}).status_code == 200


def test_sitemap_has_hreflang_alternates_and_stable_dates(client):
    xml = client.get('/sitemap.xml').text
    assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in xml
    assert 'hreflang="x-default" href="http://127.0.0.1:8080/forward-test/"' in xml
    assert 'hreflang="en" href="http://127.0.0.1:8080/en/forward-test/"' in xml
    assert '<lastmod>' + portal_frontend.CONTENT_UPDATED['/register/'] + '</lastmod>' in xml
