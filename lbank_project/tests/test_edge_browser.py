"""Chromium checks for the sign-up referral lookup and the 404 page."""
import os
import shutil
import socket
import threading
import time

from cryptography.fernet import Fernet
import pytest
import uvicorn

from portal_server import create_app
from portal_store import PortalStore


def test_referral_code_is_looked_up_on_blur_or_from_the_link_not_on_every_keystroke(tmp_path):
    module = pytest.importorskip('playwright.sync_api')
    executable = os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium unavailable')
    store = PortalStore(tmp_path / 'edge.db', Fernet.generate_key())
    listener = socket.socket();listener.bind(('127.0.0.1', 0));listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(create_app(store, origin=origin, secure=False), log_level='error', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True);thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:time.sleep(.02)
        assert server.started
        with module.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width': 390, 'height': 844}, locale='fa-IR', reduced_motion='reduce')
            page = context.new_page();errors = [];lookups = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' and 'Content Security Policy' in msg.text else None)
            page.on('request', lambda r: lookups.append(r.url) if '/api/referral/' in r.url else None)
            page.goto(origin + '/register/');page.wait_for_selector('#register-form')
            field = page.locator('#referral-code-input')
            field.click();page.keyboard.type('ABCDEFGH', delay=60)
            page.wait_for_timeout(900)                                       # Well past the old 400 ms debounce.
            assert lookups == []
            page.locator('#email').click()                                   # Leaving the field looks the code up once.
            page.wait_for_function("()=>document.getElementById('referral-offer').textContent.includes('معتبر نیست')")
            assert len(lookups) == 1 and lookups[0].endswith('/api/referral/ABCDEFGH')
            field.click();field.press('End');field.type('Z');page.locator('#email').click()
            page.wait_for_function("()=>document.getElementById('referral-offer').textContent.includes('معتبر نیست')")
            assert len(lookups) == 2
            page.locator('#email').click();page.locator('#username').click()   # Blurring other fields does not repeat it.
            assert len(lookups) == 2
            lookups.clear()
            page.goto(origin + '/register/?ref=LINKCODE');page.wait_for_selector('#register-form')
            page.wait_for_function("()=>document.getElementById('referral-offer').textContent.includes('معتبر نیست')")
            assert len(lookups) == 1 and lookups[0].endswith('/api/referral/LINKCODE')
            assert not errors, errors
            # The site's own 404 page for unknown addresses, in both languages, under the page CSP.
            for path, lang in (('/no-such-page', 'fa'), ('/en/no-such-page', 'en')):
                response = page.goto(origin + path)
                assert response.status == 404 and page.evaluate('document.documentElement.lang') == lang
                assert page.locator('#not-found').is_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True;thread.join(timeout=10);listener.close();store.close()
