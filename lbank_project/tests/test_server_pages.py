"""Server-rendered trust pages, product pages, methodology, contact details, offers and blog authorship."""
import json
import re

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_pages
from portal_pages_content import CONTENT
from portal_server import create_app
from portal_store import PortalStore
from pricing_helpers import enable_test_prices
from totp_helpers import enable_totp, extra

ORIGIN = 'https://avina.example'
PASSWORD = 'disposable-test-password'
FORBIDDEN = ('ichimoku', 'ایچیموکو', 'ema', 'rsi', 'macd', 'atr', 'اندیکاتور', 'indicator', 'timeframe', 'تایم‌فریم', 'breakout', 'pullback',
             'شکست روند', 'پولبک', 'moving average', 'میانگین متحرک')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('PORTAL_RATE_LIMIT_PER_MINUTE', '100000')
    store = PortalStore(tmp_path / 'p.db', Fernet.generate_key())
    store.create_user('manager', PASSWORD);store.set_admin('manager');enable_totp(store, 'manager');store.create_user('alice', PASSWORD)
    with TestClient(create_app(store, origin=ORIGIN), base_url=ORIGIN) as client:
        yield client, store
    store.close()


def login(client, name='manager'):
    r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': ORIGIN}, json=dict(username=name, password=PASSWORD, **extra(name)))
    assert r.status_code == 200, r.text
    return {'X-Portal-Request': '1', 'Origin': ORIGIN, 'X-CSRF-Token': r.json()['csrf']}


def text_of(page):
    body = re.search(r'<main.*?</main>', page, re.S).group(0)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body))


def test_product_pages_have_300_words_and_no_method_details():
    for slug in ('pricing', 'signals', 'auto-trading', 'exchanges'):
        for lang in ('fa', 'en'):
            exchanges = [dict(id='x', name='Binance', markets=['spot', 'futures'], pending_markets=[], required_fields={'spot': ['apiKey', 'secret']})] * 8
            page = portal_pages.build(slug, lang, ORIGIN, [], plans=None, exchanges=exchanges)
            assert len(text_of(page).split()) >= 300, (slug, lang, len(text_of(page).split()))
    for slug, langs in CONTENT.items():
        blob = json.dumps(langs, ensure_ascii=False).lower()
        for word in FORBIDDEN:
            assert not re.search(r'\b' + re.escape(word) + r'\b', blob) if word.isascii() else word not in blob, (slug, word)


def test_pages_render_without_javascript_with_breadcrumbs_and_internal_links(setup):
    client, _ = setup
    for path in portal_pages.SERVER_PAGES:
        page = client.get(path).text
        assert '<main' in page and page.count('<h1') == 1 and 'BreadcrumbList' in page
        assert re.search(r'<script(?![^>]*(ld\+json|src=))', page) is None  # no inline scripts of our own
        assert 'style=' not in page
        assert '/forward-test/' in page and ('/pricing/' in page or '/en/pricing/' in page)
    legal = client.get('/terms/').text + client.get('/en/privacy/').text + client.get('/risk/').text
    assert 'وکیل' not in legal and 'lawyer' not in legal.lower()  # the draft reminder lives only in the admin panel
    assert 'USDT' in client.get('/en/terms/').text and '30 days' in client.get('/en/privacy/').text


def test_contact_details_come_from_site_info_and_jsonld_only_when_set(setup):
    client, store = setup
    page = client.get('/en/contact/').text
    assert 'No public contact details' in page and 'contactPoint' not in page and 'mailto:' not in page
    assert client.put('/api/admin/site-info', json={}).status_code == 401
    alice = login(client, 'alice')
    assert client.put('/api/admin/site-info', headers=alice, json={'support_email': 'a@b.co'}).status_code == 403
    client.post('/api/logout', headers=alice)
    h = login(client)
    bad = {'telegram_link': 'https://evil.example/x'}
    assert client.put('/api/admin/site-info', headers=h, json=bad).status_code == 422
    assert client.put('/api/admin/site-info', headers=h, json={'support_email': 'not-an-email'}).status_code == 422
    assert client.put('/api/admin/site-info', headers=h, json={'support_email': 'x' * 200}).status_code == 422
    assert client.put('/api/admin/site-info', headers=h, json={'support_email': 'help@avina.example', 'telegram_id': '@avina_help',
                                                               'telegram_link': 'https://t.me/avina_help'}).status_code == 200
    assert client.get('/api/admin/site-info').json()['support_email'] == 'help@avina.example'
    page = client.get('/en/contact/').text
    assert 'mailto:help@avina.example' in page and 'https://t.me/avina_help' in page and '"contactPoint"' in page
    assert 'No public contact details' not in page
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM admin_events WHERE action='site_info.update'").fetchone()['n'] == 1
    assert 'help@avina.example' in client.get('/contact/').text


def test_pricing_offers_only_when_sales_are_open_and_priced(setup):
    client, store = setup
    page = client.get('/en/pricing/').text
    assert '"offers"' not in page and 'Sales are closed' in page and 'FAQPage' in page
    enable_test_prices(store)
    from portal_blog import GENERATION
    GENERATION[0] += 1
    page = client.get('/en/pricing/').text
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1))
    app = next(n for n in ld['@graph'] if n['@type'] == 'SoftwareApplication')
    assert app['offers'] and all(o['priceCurrency'] == 'USD' and o['availability'].endswith('InStock') and float(o['price']) > 0 for o in app['offers'])
    assert 'aggregateRating' not in page and 'review' not in page.lower().replace('reviewed', '')


def test_methodology_page_renders_markdown_and_raw_files_are_noindex(setup):
    client, _ = setup
    page = client.get('/en/methodology/').text
    assert '<h2' in page or '<p>' in page
    assert 'Full calendar period' in page and '1,826 days' in page
    raw = client.get('/backtest/methodology-en.md')
    assert raw.status_code == 200 and raw.headers['x-robots-tag'] == 'noindex'
    assert 'noindex' not in client.get('/backtest/five-year-summary.json').headers.get('x-robots-tag', '')
    assert '/methodology/' in client.get('/en/').text


def test_blog_author_related_three_and_footer_links(setup):
    client, store = setup
    h = login(client)
    for i in range(5):
        r = client.post('/api/admin/blog', headers=h, json=dict(slug=f'post-{i}', title=f'Post {i} title', description='Short description', body='## A\ntext',
                                                               status='published', lang='en',
                                                               **({'author_name': 'Sara K.', 'author_bio': 'Writes about risk.'} if i == 0 else {})))
        assert r.status_code in (200, 201), r.text
    page = client.get('/en/blog/post-0/').text
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1))
    post = next(n for n in ld['@graph'] if n['@type'] == 'BlogPosting')
    assert post['author'] == {'@type': 'Person', 'name': 'Sara K.', 'description': 'Writes about risk.'}
    assert 'Writes about risk.' in page and page.count('class="blog-card"') == 3
    for target in ('/en/pricing/', '/en/signals/', '/en/auto-trading/', '/en/exchanges/', '/en/about/', '/en/contact/', '/en/terms/', '/en/privacy/', '/en/risk/'):
        assert f'href="{target}"' in page, target
    other = client.get('/en/blog/post-1/').text
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', other).group(1))
    assert next(n for n in ld['@graph'] if n['@type'] == 'BlogPosting')['author'] == {'@id': ORIGIN + '/#org'}
    assert client.post('/api/admin/blog', headers=h, json=dict(slug='x1', title='t', description='d', body='b', status='draft', author_name='y' * 90)).status_code == 422


def test_blog_pages_get_etags_and_304(setup):
    client, _ = setup
    first = client.get('/en/blog/')
    assert first.headers['etag'] and client.get('/en/blog/', headers={'If-None-Match': first.headers['etag']}).status_code == 304
