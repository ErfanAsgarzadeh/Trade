"""The forward-test page renders its chart and the paper-trading label in both languages, without CSP violations."""
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
from test_forward import build_runtime, midnight


@pytest.mark.parametrize('lang,path,label,heading', [('fa', '/forward-test/', 'Paper Trading', 'فوروارد تست زنده آوینا'),
                                                     ('en', '/en/forward-test/', 'Paper trading', 'Avina live forward test')])
@pytest.mark.parametrize('appearance', ['dark', 'light'])
def test_forward_page_and_landing_teaser_render(tmp_path, monkeypatch, lang, path, label, heading, appearance):
    module = pytest.importorskip('playwright.sync_api')
    executable = os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium unavailable')
    monkeypatch.setenv('PORTAL_FORWARD_TEST_DIR', str(build_runtime(tmp_path / 'rt', midnight())))
    store = PortalStore(tmp_path / 'f.db', Fernet.generate_key())
    listener = socket.socket();listener.bind(('127.0.0.1', 0));listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(create_app(store, origin=origin, secure=False), log_level='error', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True);thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:time.sleep(.02)
        with module.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='fa-IR' if lang == 'fa' else 'en-US')
            context.add_init_script("localStorage.setItem('trade.appearance', '" + appearance + "')")
            page = context.new_page();errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.goto(origin + path);page.wait_for_selector('svg.forward-chart-svg, .forward-chart svg')
            assert page.locator('h1').count() == 1 and heading in page.locator('h1').inner_text()
            assert label in page.locator('.forward-paper').inner_text()
            assert page.locator('.forward-badge').count() == 1
            assert page.locator('.forward-chart svg title').count() == 1
            assert page.locator('.forward-chart path.fc-line').get_attribute('d').count('L') == 19
            assert page.locator('.forward-bot').count() == 3 and page.locator('.forward-tile').count() == 8
            page.locator('.forward-table-toggle summary').click()
            assert page.locator('.forward-table-toggle tbody tr').count() == 20
            for width in (1280, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), width
            page.goto(origin + ('/en/' if lang == 'en' else '/'));page.wait_for_selector('.forward-spark svg')
            assert page.locator('#forward-test .forward-tile').count() == 4
            page.locator('#forward-test a[href$="/forward-test/"]').click()
            page.wait_for_selector('.forward-chart svg')
            assert not [e for e in errors if 'Content Security Policy' in e or 'Hydration' in e or 'pageerror' in e], errors
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True;thread.join(timeout=10);listener.close();store.close()


def test_forward_page_shows_collecting_state_without_data(tmp_path, monkeypatch):
    module = pytest.importorskip('playwright.sync_api')
    executable = os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium unavailable')
    monkeypatch.setenv('PORTAL_FORWARD_TEST_DIR', str(tmp_path / 'none'))
    store = PortalStore(tmp_path / 'f.db', Fernet.generate_key())
    listener = socket.socket();listener.bind(('127.0.0.1', 0));listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(create_app(store, origin=origin, secure=False), log_level='error', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True);thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:time.sleep(.02)
        with module.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page();page.goto(origin + '/en/forward-test/')
            page.wait_for_selector('.forward-collecting h2')
            page.wait_for_function("()=>document.querySelector('.forward-collecting').innerText.includes('7 full days')")
            assert page.locator('.forward-chart').count() == 0 and page.locator('.forward-paper').count() == 1
            browser.close()
    finally:
        server.should_exit = True;thread.join(timeout=10);listener.close();store.close()
