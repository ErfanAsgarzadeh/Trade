"""Real Chromium smoke test against an isolated portal; no exchange/payment calls.

Optional: pip install playwright, then install Chromium or set
PORTAL_TEST_CHROMIUM. Screenshots go to PORTAL_SCREENSHOTS (a temporary directory
by default); account information is entirely disposable test data.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import threading
import time

from cryptography.fernet import Fernet
import pytest
import uvicorn

from portal_store import PortalStore
from portal_server import create_app
from portal_billing import Billing
import customer_manager
from pricing_helpers import enable_test_prices


@pytest.mark.parametrize("appearance", ["dark", "light"])
def test_portal_desktop_mobile_and_subscription_journey(tmp_path, appearance):
    browser_module=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):
        pytest.skip('Install Chromium or set PORTAL_TEST_PLAYWRIGHT_BROWSER=1')
    screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path/'screenshots')));screenshots=screenshots/appearance;screenshots.mkdir(parents=True,exist_ok=True)
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    enable_test_prices(store)
    user=store.create_user('demo-trader','disposable-browser-password')
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem'
    customer_manager.keygen(private,public)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(create_app(store,origin=origin,secure=False),log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        with browser_module.sync_playwright() as p:
            browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=browser.new_context(viewport={'width':1440,'height':1050},locale='fa-IR',reduced_motion='reduce')
            context.add_init_script("localStorage.setItem('trade.appearance', '"+appearance+"')")
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('dialog',lambda dialog:dialog.accept())
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and ('Content Security Policy' in msg.text or 'Hydration' in msg.text) else None)
            page.goto(origin+'/dashboard/');page.wait_for_selector('#login-panel:not([hidden])')
            page.screenshot(path=str(screenshots/'login-desktop.png'),full_page=True)
            page.locator('#username').fill('demo-trader');page.locator('#password').fill('disposable-browser-password')
            page.locator('#login-form button').click()
            page.wait_for_selector('#account-panel:not([hidden])');page.wait_for_function("()=>document.getElementById('plan-price').textContent==='۴۹'")
            page.locator('input[name="term"][value="3"]').check()
            page.wait_for_function("()=>document.getElementById('plan-price').textContent==='۱۲۹'",timeout=5000)
            page.locator('.pricing-details').evaluate('(el)=>el.open=true')
            page.screenshot(path=str(screenshots/'dashboard-desktop.png'),full_page=True)
            assert page.locator('#pricing-rows tr').count()==7
            assert page.locator('#robots article').count()==3
            for width in (390,360,320):
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),str(width)
                page.screenshot(path=str(screenshots/f'dashboard-mobile-{width}.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#request-license').click()
            page.wait_for_selector('#checkout-dialog[open]')
            assert page.locator('#confirm-order').is_disabled()
            page.locator('#checkout-consent').check();page.screenshot(path=str(screenshots/'checkout-mobile.png'))
            page.locator('#confirm-order').click();page.wait_for_selector('#checkout-dialog:not([open])',state='attached')
            page.wait_for_selector('#order-rows .pending');assert page.locator('#request-license').is_disabled()
            page.reload();page.wait_for_selector('#order-rows .pending')
            page.locator('#order-rows button').click();page.wait_for_selector('#order-rows .cancelled')
            page.wait_for_function("()=>!document.getElementById('request-license').disabled")
            page.locator('#request-license').click();page.locator('#checkout-consent').check();page.locator('#confirm-order').click()
            page.wait_for_selector('#order-rows .pending')
            billing=Billing(store);oid=next(o['id'] for o in billing.snapshot(user)['orders'] if o['status']=='pending')
            billing.approve(oid,private,'binance:demo123','10000','payment:browser')
            page.locator('#refresh-license').click();page.wait_for_function("()=>document.getElementById('license-state').textContent==='فعال'")
            assert page.locator('#download-license').is_visible()
            download=page.request.get(origin+'/api/me/license/download')
            assert download.ok and download.json()['payload']['account_id']=='binance:demo123'
            page.locator('#capital-tier').select_option('25000')
            page.wait_for_function("()=>!document.getElementById('request-license').disabled")
            assert 'مابه‌التفاوت' in page.locator('#monthly-equivalent').inner_text()
            billing.cashflow('demo-trader',private,'deposit:browser','500')
            page.locator('#refresh-license').click();page.wait_for_function("()=>document.getElementById('license-state').textContent==='مهلت ارتقای سرمایه'")
            assert page.locator('#license-alert').is_visible()
            page.screenshot(path=str(screenshots/'grace-mobile.png'),full_page=True)
            page.evaluate('navigator.serviceWorker.ready');page.reload();page.wait_for_selector('#account-panel:not([hidden])')
            context.set_offline(True);page.goto(origin+'/dashboard/')
            assert 'به اینترنت وصل شوید' in page.locator('h1').inner_text()
            context.set_offline(False);page.goto(origin+'/dashboard/');page.wait_for_selector('#account-panel:not([hidden])')
            cached=page.evaluate("caches.keys().then(async keys=>Promise.all(keys.map(async key=>(await caches.open(key)).keys().then(reqs=>reqs.map(r=>new URL(r.url).pathname)))))")
            assert all(path in ('/portal-assets/offline.html','/portal-assets/titanium.css','/portal-assets/appearance.js') for paths in cached for path in paths)
            page.locator('#exchange-id').select_option('okx')
            page.locator('#credential-api_key').fill('old-test-key')
            page.locator('#api-secret').fill('old-test-secret')
            page.locator('#credential-passphrase').fill('old-test-passphrase')
            page.locator('#exchange-id').select_option('lbank')
            assert page.locator('#credential-api_key').input_value()==''
            assert page.locator('#api-secret').input_value()==''
            assert page.locator('#credential-passphrase').count()==0
            page.locator('#credential-api_key').fill('browser-test-key')
            page.locator('#api-secret').fill('browser-test-secret')
            page.locator('#connection-form button').click()
            page.wait_for_function("()=>document.getElementById('connection-status').textContent.includes('ثبت شدند')")
            assert page.locator('#credential-api_key').input_value()==''
            assert page.locator('#api-secret').input_value()==''
            page.locator('#disconnect').click()
            page.wait_for_function("()=>document.getElementById('connection-status').textContent==='حسابی ثبت نشده'")
            page.locator('#logout').click();page.wait_for_selector('#login-panel:not([hidden])')
            assert page.locator('#order-rows tr').count()==0
            assert page.locator('#license-account').count()==0
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();store.close()


@pytest.mark.parametrize("appearance", ["dark", "light"])
def test_signup_and_closed_product_sales_on_mobile(tmp_path, appearance):
    browser_module=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium not installed')
    import product_pricing
    import signal_feed
    screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path/'screenshots')));screenshots=screenshots/appearance;screenshots.mkdir(parents=True,exist_ok=True)
    store=PortalStore(tmp_path/'registration.db',Fernet.generate_key())
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem';customer_manager.keygen(private,public)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(create_app(store,origin=origin,secure=False),log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        with browser_module.sync_playwright() as p:
            browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=browser.new_context(viewport={'width':390,'height':844},locale='fa-IR',reduced_motion='reduce')
            context.add_init_script("localStorage.setItem('trade.appearance', '"+appearance+"')")
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and ('Content Security Policy' in msg.text or 'Hydration' in msg.text) else None)
            page.goto(origin+'/register/');page.wait_for_selector('#register-form')
            page.screenshot(path=str(screenshots/'register-mobile.png'),full_page=True)
            page.locator('#username').fill('fresh-user');page.locator('#password').fill('disposable-signup-password')
            page.locator('#password-confirmation').fill('different-password')
            page.locator('#register-form button').click()
            page.wait_for_function("()=>document.getElementById('message').textContent.includes('یکسان نیستند')")
            page.locator('#password-confirmation').fill('disposable-signup-password')
            page.locator('#register-form button').click();page.wait_for_selector('#account-panel')
            page.wait_for_selector('#sales-closed');assert page.locator('#request-license').is_disabled()
            assert page.locator('#plan-price').inner_text()=='تعیین نشده'
            page.locator('input[name="product"][value="signals"]').check()
            assert page.locator('#request-license').is_disabled()
            assert 'تعیین نشده' in page.locator('#plan-price').inner_text()
            for width in (320,390,1440):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),str(width)
                page.screenshot(path=str(screenshots/f'products-closed-{width}.png'),full_page=True)
            me=page.request.get(origin+'/api/me').json()
            user=store.session(page.context.cookies()[0]['value'])['id']
            # All prices below are disposable test tariffs, not configured production prices.
            enable_test_prices(store)
            page.locator('#refresh-license').click();page.wait_for_function("()=>!document.getElementById('request-license').disabled")
            page.locator('input[name="product"][value="signals"]').check()
            page.locator('#request-license').click();page.locator('#checkout-consent').check();page.locator('#confirm-order').click()
            page.wait_for_selector('#order-rows .pending')
            billing=Billing(store);order=billing.snapshot(user)['orders'][0]
            assert order['product']=='signals'
            billing.approve(order['id'],private,payment_ref='payment:signal-browser')
            page.locator('#refresh-license').click();page.wait_for_function("()=>document.getElementById('license-state').textContent==='فعال'")
            assert page.locator('#connection-section').count()==0
            page.wait_for_function("()=>document.getElementById('signals-empty').textContent.includes('منبع سیگنال')")
            assert not page.request.get(origin+'/api/me/license').json()['license']['entries_allowed']
            page.locator('#logout').click();page.wait_for_selector('#login-form')
            assert page.locator('#signals-section').count()==0
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();store.close()
