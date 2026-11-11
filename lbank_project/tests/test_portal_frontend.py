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
