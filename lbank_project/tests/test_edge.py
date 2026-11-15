"""Unknown pages, error logging, per-IP page limits, the blog cache and the referral lookup limit."""
import hashlib
import base64
import logging
import re

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_blog
import portal_server
from portal_blog import BlogStore
from portal_edge import TTLCache, TokenBuckets
from portal_server import create_app
from portal_store import PortalStore
from totp_helpers import enable_totp, extra

ORIGIN = 'https://avina.example';PASSWORD = 'disposable-test-password'


@pytest.fixture
def store(tmp_path):
    store = PortalStore(tmp_path / 'portal.db', Fernet.generate_key())
    store.create_user('manager', PASSWORD, 'm@example.com');store.set_admin('manager');enable_totp(store, 'manager')
    yield store
    store.close()


def client_for(store, **kw):
    return TestClient(create_app(store, origin=ORIGIN, secure=True, **kw), base_url=ORIGIN, raise_server_exceptions=False)


def script_hashes(html):
    return {"'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
            for s in re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)}


def test_unknown_pages_get_the_site_404_in_the_right_language_and_api_stays_json(store):
    with client_for(store) as client:
        page = client.get('/foo')
        assert page.status_code == 404 and 'text/html' in page.headers['content-type'] and '<html lang="fa" dir="rtl"' in page.text
        # The CSP carries the hashes of the 404 page's own bootstrap scripts, so the page works under the policy.
        csp = page.headers['content-security-policy']
        assert script_hashes(page.text) and all(h in csp for h in script_hashes(page.text))
        assert page.headers['cache-control'] == 'no-store' and page.headers['x-robots-tag'] == 'noindex, nofollow'
        english = client.get('/en/foo')
        assert english.status_code == 404 and '<html lang="en" dir="ltr"' in english.text
        assert client.get('/en/deep/er/path.php').status_code == 404
        api = client.get('/api/foo')
        assert api.status_code == 404 and api.json() == {'detail': 'Not Found'}
        for prefix in ('/_next/nothing.js', '/portal-assets/nothing.png', '/backtest/nothing.csv', '/blog-media/nothing'):
            response = client.get(prefix)
            assert response.status_code == 404 and 'text/html' not in response.headers['content-type'], prefix
        assert client.get('/blog/missing-post/').status_code == 404
        assert '<html lang="en"' in client.get('/en/blog/missing-post/').text
        assert client.get('/healthz').status_code == 200 and client.get('/').status_code == 200


def test_unhandled_errors_log_one_line_without_user_text_and_return_a_request_id(store, caplog):
    app = create_app(store, origin=ORIGIN, secure=True)

    @app.get('/api/boom/{name}')
    def boom(name: str):
        raise ValueError('secret-password-hunter2 ' + name)
    client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger='portal.errors'):
        response = client.get('/api/boom/line%0Aforged-entry?token=abc', headers={'Cookie': 'trade_session=hunter3', 'Authorization': 'Bearer hunter4'})
    assert response.status_code == 500
    body = response.json()
    assert body['detail'] == 'Internal error' and re.fullmatch(r'[0-9a-f]{8}', body['request_id'])
    assert response.headers['x-content-type-options'] == 'nosniff' and 'hunter' not in response.text
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and '\n' not in lines[0]
    assert body['request_id'] in lines[0] and 'method=GET' in lines[0] and 'type=ValueError' in lines[0] and 'test_edge.py' in lines[0]
    for forbidden in ('hunter', 'secret-password', 'token=abc', 'Bearer'):
        assert forbidden not in lines[0] and forbidden not in caplog.text


def test_token_bucket_limits_per_client_refills_and_stays_bounded():
    now = [0.0]
    buckets = TokenBuckets(per_minute=120, max_clients=3, clock=lambda: now[0])
    assert all(buckets.take('1.1.1.1') == 0 for _ in range(120))
    assert buckets.take('1.1.1.1') == 1 and buckets.take('2.2.2.2') == 0   # Another client is unaffected.
    now[0] += 30                                                           # 30 s refills 60 tokens at 2/s.
    assert sum(buckets.take('1.1.1.1') == 0 for _ in range(100)) == 60
    for index in range(10):buckets.take('10.0.0.%d' % index)
    assert len(buckets.buckets) == 3 and '1.1.1.1' not in buckets.buckets  # The oldest clients were dropped.


def test_page_requests_are_limited_per_ip_but_static_files_health_and_signed_in_polling_are_not(store, monkeypatch):
    monkeypatch.setenv('PORTAL_RATE_LIMIT_PER_MINUTE', '5')
    with client_for(store) as client:
        statuses = [client.get('/blog/').status_code for _ in range(5)]
        assert statuses == [200] * 5
        limited = client.get('/blog/')
        assert limited.status_code == 429 and int(limited.headers['retry-after']) >= 1 and limited.headers['cache-control'] == 'no-store'
        assert client.get('/en/').status_code == 429 and client.get('/api/plans').status_code == 429
        for _ in range(20):
            assert client.get('/healthz').status_code == 200
            assert client.get('/portal-assets/avina-mark.png').status_code == 200
            assert client.get('/api/me').status_code == 401        # Signed-in API polling is not counted, only authenticated.
            assert client.get('/blog-media/ffffffffffffffffffffffff.webp').status_code == 404


def test_rate_limit_keys_on_the_client_address_the_proxy_layer_reports(store, monkeypatch):
    monkeypatch.setenv('PORTAL_RATE_LIMIT_PER_MINUTE', '2')
    with client_for(store) as client:
        assert [client.get('/blog/').status_code for _ in range(3)] == [200, 200, 429]
    seen = []
    real = portal_server.TokenBuckets.take
    monkeypatch.setattr(portal_server.TokenBuckets, 'take', lambda self, client: (seen.append(client), real(self, client))[1])
    with client_for(store) as client:
        client.get('/blog/')
    assert seen == ['testclient']   # request.client.host: uvicorn replaces it with the real address behind trusted proxies.


def test_blog_pages_are_cached_briefly_and_refreshed_after_any_save_or_delete(store, monkeypatch):
    with store.db() as db:manager = db.execute("SELECT id FROM users WHERE username='manager'").fetchone()['id']
    blog = BlogStore(store)
    fields = dict(lang='fa', slug='first-guide', title='راهنمای اول ربات', description='توضیح مقاله', keywords=[], body='## بخش\nمتن', status='published')
    post = blog.save(manager, fields)
    reads = []
    real = BlogStore.published
    monkeypatch.setattr(BlogStore, 'published', lambda self, lang='fa', limit=None: (reads.append(lang), real(self, lang, limit))[1])
    with client_for(store) as client:
        first = client.get('/blog/')
        assert first.status_code == 200 and 'راهنمای اول ربات' in first.text
        count = len(reads)
        for path in ('/blog/', '/blog/rss.xml', '/sitemap.xml'):client.get(path);client.get(path)
        after_two = len(reads)
        for path in ('/blog/', '/blog/rss.xml', '/sitemap.xml'):client.get(path)
        assert len(reads) == after_two and after_two > count   # Cached: no new database reads.
        article = client.get('/blog/first-guide/')
        assert article.status_code == 200
        articles_read = len(reads)
        client.get('/blog/first-guide/');assert len(reads) == articles_read
        # Saving changes the pages at once; so does deleting.
        blog.save(manager, dict(fields, title='عنوان تازه'), post['id'], post['updated'])
        assert 'عنوان تازه' in client.get('/blog/').text and 'عنوان تازه' in client.get('/blog/first-guide/').text
        current = blog.get(post['id'])
        blog.delete(manager, post['id'], current['updated'])
        assert 'عنوان تازه' not in client.get('/blog/').text and client.get('/blog/first-guide/').status_code == 404
        assert 'first-guide' not in client.get('/sitemap.xml').text


def test_ttl_cache_expires_and_is_bounded():
    now = [0.0]
    cache = TTLCache(30, limit=2, clock=lambda: now[0])
    cache.put('a', 1);cache.put('b', 2);cache.put('c', 3)
    assert cache.get('a') is None and cache.get('c') == 3
    now[0] = 31
    assert cache.get('c') is None
    cache.put('d', 4, generation=1)
    assert cache.get('d', 2) is None


def test_referral_lookup_allows_thirty_per_minute_per_ip(store):
    with client_for(store) as client:
        codes = [client.get('/api/referral/ABCD1234').status_code for _ in range(30)]
        assert codes == [200] * 30
        assert client.get('/api/referral/ABCD1234').status_code == 429
        assert client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN},
                           json=dict(username='nobody', password='x' * 12)).status_code == 401   # Other counters are separate.
