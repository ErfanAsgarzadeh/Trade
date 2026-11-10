"""The hero must be actual data replay, pauseable, reduced-motion aware and responsive."""
import os
from pathlib import Path
import shutil
import socket
import threading
import time

from cryptography.fernet import Fernet
import pytest
import uvicorn
from portal_server import create_app
from portal_store import PortalStore


def test_public_hero_replay_and_navigation_on_mobile_and_desktop(tmp_path):
    module=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium unavailable')
    screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path/'screenshots')));screenshots.mkdir(parents=True,exist_ok=True)
    store=PortalStore(tmp_path/'landing.db',Fernet.generate_key())
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(create_app(store,origin=origin,secure=False),log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        with module.sync_playwright() as p:
            browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=browser.new_context(viewport={'width':1440,'height':1000},locale='fa-IR',reduced_motion='reduce')
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and ('Content Security Policy' in msg.text or 'Hydration' in msg.text) else None)
            page.goto(origin);page.wait_for_selector('#hero-title')
            page.wait_for_function("()=>document.getElementById('backtest-motion').dataset.reducedMotion==='true'")
            assert page.locator('#backtest-motion').get_attribute('data-motion')=='paused'
            assert '۹۶۴٬۴۵۱' in page.locator('#replay-equity').inner_text()
            assert page.locator('.actual-equity-line').get_attribute('d').count('L')==1826
            for width in (1440,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),str(width)
                rect=page.locator('.landing-signup').bounding_box()
                assert rect['x']>=0 and rect['x']+rect['width']<=width
                page.screenshot(path=str(screenshots/f'landing-{width}.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#toggle-backtest-motion').click()
            page.wait_for_function("()=>document.getElementById('backtest-motion').dataset.motion==='playing'")
            page.wait_for_function("()=>document.getElementById('replay-equity').textContent!=='۱۰٬۰۰۰ دلار'")
            page.locator('#toggle-backtest-motion').click()
            assert page.locator('#backtest-motion').get_attribute('data-motion')=='paused'
            paused=page.locator('#replay-equity').inner_text();page.wait_for_timeout(150)
            assert page.locator('#replay-equity').inner_text()==paused
            page.screenshot(path=str(screenshots/'hero-motion-paused.png'))
            page.emulate_media(reduced_motion='reduce');page.wait_for_function("()=>document.getElementById('backtest-motion').dataset.reducedMotion==='true'")
            page.locator('a[href="#backtest"]').first.click()
            assert page.locator('.annual-result-table tbody tr').count()==5
            page.locator('.methodology-details summary').click()
            assert 'فاندینگ' in page.locator('.methodology-grid').inner_text()
            assert page.request.get(origin+'/backtest/five-year-summary.json').json()['max_minute_dd_pct']>30
            page.locator('.landing-login').click();page.wait_for_selector('#login-form')
            assert page.url.rstrip('/').endswith('/dashboard')
            page.goto(origin);page.locator('.landing-signup').click();page.wait_for_selector('#register-form')
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();store.close()
