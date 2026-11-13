import base64
import hashlib
import re
from pathlib import Path
from fastapi.testclient import TestClient
from portal_frontend import frontend_index
from portal_server import create_app


def test_missing_next_build_returns_clear_error_not_legacy_ui(tmp_path,monkeypatch):
    monkeypatch.setenv('PORTAL_FRONTEND_DIR',str(tmp_path/'missing'))
    # Supplied store avoids unrelated secrets/database provisioning in this static-route test.
    with TestClient(create_app(store=object(),origin='http://127.0.0.1:8080',secure=False),base_url='http://127.0.0.1:8080') as client:
        response=client.get('/')
        assert response.status_code==503 and 'npm run build' in response.text
        assert client.get('/portal.js').status_code==404


def test_next_bootstrap_hashes_are_exact_and_do_not_allow_arbitrary_inline_scripts(tmp_path):
    html='<html><script>self.__next_f.push([1,"<&hello>"])</script><script src="/_next/chunk.js"></script></html>'
    (tmp_path/'index.html').write_text(html)
    content,hashes=frontend_index(tmp_path)
    expected=base64.b64encode(hashlib.sha256(b'self.__next_f.push([1,"<&hello>"])').digest()).decode()
    assert content==html and hashes=="'sha256-"+expected+"'"
    assert 'unsafe-inline' not in hashes and 'unsafe-eval' not in hashes


def test_exported_next_chunks_are_served_with_their_html_csp():
    with TestClient(create_app(store=object(),origin='http://127.0.0.1:8080',secure=False),base_url='http://127.0.0.1:8080') as client:
        response=client.get('/')
        assert response.status_code==200 and '/_next/static/' in response.text
        assert "'sha256-" in response.headers['content-security-policy']
        assert 'unsafe-inline' not in response.headers['content-security-policy']
        chunk=re.search(r'src="(/_next/[^\"]+\.js)"',response.text).group(1)
        assert client.get(chunk).status_code==200
        assert client.get('/manifest.webmanifest').json()['display']=='standalone'


def test_public_pages_carry_search_metadata_for_the_configured_origin():
    origin='https://avina.example'
    with TestClient(create_app(store=object(),origin=origin,secure=True),base_url=origin) as client:
        home=client.get('/')
        assert home.text.count('<link rel="canonical" href="https://avina.example/"/>')==1
        assert '<meta property="og:image" content="https://avina.example/portal-assets/og-image.png"/>' in home.text
        assert home.text.count('<h1')==1 and 'FAQPage' in home.text and '"SoftwareApplication"' in home.text
        # Added JSON-LD is data: the CSP still lists only the executable inline scripts.
        assert home.headers['content-security-policy'].count("'sha256-")==frontend_index(Path(__file__).parents[1]/'frontend'/'out')[1].count("'sha256-")
        assert home.headers['cache-control']=='no-cache' and 'x-robots-tag' not in home.headers
        assert '<link rel="canonical" href="https://avina.example/register/"/>' in client.get('/register/').text
        assert client.get('/portal-assets/og-image.png').headers['cache-control']=='public, max-age=86400'
        chunk=re.search(r'src="(/_next/static/[^\"]+\.js)"',home.text).group(1)
        assert client.get(chunk).headers['cache-control']=='public, max-age=31536000, immutable'
        robots=client.get('/robots.txt')
        assert 'Disallow: /api/' in robots.text and 'Sitemap: https://avina.example/sitemap.xml' in robots.text
        sitemap=client.get('/sitemap.xml').text
        assert '<loc>https://avina.example/</loc>' in sitemap and '<loc>https://avina.example/register/</loc>' in sitemap
        assert 'dashboard' not in sitemap


def test_private_pages_and_errors_stay_out_of_search_and_caches():
    with TestClient(create_app(store=object(),origin='http://127.0.0.1:8080',secure=False),base_url='http://127.0.0.1:8080') as client:
        for path in ('/dashboard/','/admin/'):
            page=client.get(path)
            assert page.headers['cache-control']=='no-store' and page.headers['x-robots-tag']=='noindex, nofollow'
            assert 'rel="canonical"' not in page.text
        assert client.get('/portal-assets/missing.png').headers['cache-control']=='no-store'
