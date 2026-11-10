"""Admin workbench in Chromium against the actual FastAPI and temporary database."""
import os
from pathlib import Path
import shutil
import socket
import threading
import time
import uuid

from cryptography.fernet import Fernet
import pytest
import uvicorn

from portal_server import create_app
from portal_store import PortalStore
from portal_billing import Billing
from portal_issuer import Issuer
from capital_plans import PRICES,TERMS
import customer_manager


def test_admin_workbench_journey_and_mobile_layout(tmp_path):
    module=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable and not os.getenv('PORTAL_TEST_PLAYWRIGHT_BROWSER'):pytest.skip('Chromium unavailable')
    screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path/'screenshots')));screenshots.mkdir(parents=True,exist_ok=True)
    store=PortalStore(tmp_path/'admin.db',Fernet.generate_key())
    store.create_user('manager','disposable-manager-password');store.set_admin('manager')
    alice=store.create_user('alice','disposable-customer-password');bob=store.create_user('bob','disposable-customer-password')
    private,public=tmp_path/'issuer.private.pem',tmp_path/'issuer.public.pem';customer_manager.keygen(private,public)
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
            context=browser.new_context(viewport={'width':1440,'height':1050},locale='fa-IR',reduced_motion='reduce')
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and ('Content Security Policy' in msg.text or 'Hydration' in msg.text) else None)
            page.on('dialog',lambda d:d.accept())
            page.goto(origin+'/admin/');page.locator('#username').fill('manager');page.locator('#password').fill('disposable-manager-password');page.locator('#login-form button').click()
            page.wait_for_selector('#admin-workbench');page.wait_for_function("()=>document.getElementById('admin-count-users').textContent==='۳'")
            page.screenshot(path=str(screenshots/'admin-overview-desktop.png'),full_page=True)
            page.locator('#admin-tab-pricing').click();page.wait_for_selector('#admin-pricing-signals')
            assert page.locator('#admin-pricing-signals .admin-open-sales').is_disabled()
            for width in (320,390,1440):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),str(width)
                page.screenshot(path=str(screenshots/f'admin-pricing-{width}.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1050})
            section=page.locator('#admin-pricing-signals')
            for cap,prices in PRICES.items():
                for index,months in enumerate(TERMS):section.locator(f'input[data-cap="{cap}"][data-months="{months}"]').fill(str(prices[index]/2))
            with page.expect_response('**/api/admin/pricing/signals') as saved:section.locator('form button').click()
            assert saved.value.status==200
            page.wait_for_function("async()=>!(await(await fetch('/api/plans')).json()).products.find(p=>p.product==='signals').sales_enabled")
            section.locator('input[type="checkbox"]').check();section.locator('.admin-open-sales').click()
            section.locator('.admin-close-sales').wait_for();section.locator('.admin-close-sales').click()
            section.locator('.admin-open-sales').wait_for()
            assert not page.request.get(origin+'/api/plans').json()['products'][0]['sales_enabled']
            section.locator('input[type="checkbox"]').check();section.locator('.admin-open-sales').click();section.locator('.admin-close-sales').wait_for()
            billing=Billing(store)
            def create_order(owner):
                quote=billing.quote(owner,10000,1,product='signals')
                return billing.order(owner,10000,1,'subscription',str(uuid.uuid4()),quote['price_cents'],product='signals')['id']
            oid=create_order(alice)
            page.locator('#admin-tab-orders').click();page.wait_for_selector('#admin-order-rows tr')
            page.locator('#admin-order-rows button').filter(has_text='بررسی').click()
            page.wait_for_selector('#admin-order-dialog[open]');assert page.locator('#admin-submit-review').is_disabled()
            page.locator('#admin-payment-ref').fill('receipt:browser-admin');page.locator('#admin-verified').check();page.locator('#admin-submit-review').click()
            page.wait_for_selector('#admin-order-dialog:not([open])',state='attached')
            page.wait_for_function("()=>document.getElementById('admin-order-rows').textContent.includes('در صف صدور')")
            assert billing.snapshot(alice)['license']['state']=='none'
            assert Issuer(store,private).once()
            page.locator('#admin-order-filter').select_option('approved')
            page.wait_for_function("()=>document.getElementById('admin-order-rows').textContent.includes('صادرشده')")
            assert billing.snapshot(alice)['license']['state']=='active'
            create_order(bob);page.locator('#admin-order-filter').select_option('pending');page.wait_for_selector('#admin-order-rows tr')
            page.locator('#admin-order-rows button').filter(has_text='رد درخواست').click();page.locator('#admin-reject-reason').fill('رسید ارائه‌شده تأیید نشد');page.locator('#admin-submit-review').click()
            page.wait_for_selector('#admin-order-dialog:not([open])',state='attached')
            page.locator('#admin-order-filter').select_option('rejected');page.wait_for_function("()=>document.getElementById('admin-order-rows').textContent.includes('ردشده')")
            page.locator('#admin-tab-users').click();page.locator('#admin-user-search').fill('alice');page.locator('.admin-search button').click()
            page.wait_for_function("()=>document.querySelectorAll('#admin-user-rows tr').length===1")
            page.locator('#admin-user-rows button').click();page.wait_for_function("()=>document.getElementById('admin-user-rows').textContent.includes('تعلیق‌شده')")
            assert store.login('alice','disposable-customer-password') is None
            page.locator('#admin-user-rows button').click();page.wait_for_function("()=>document.getElementById('admin-user-rows').textContent.includes('فعال‌سازی')===false")
            page.locator('#admin-tab-audit').click();page.wait_for_selector('.admin-content tbody tr')
            assert 'صدور لایسنس' in page.locator('.admin-content').inner_text()
            page.locator('#logout').click();page.wait_for_selector('#login-form')
            page.locator('#username').fill('alice');page.locator('#password').fill('disposable-customer-password');page.locator('#login-form button').click()
            page.wait_for_selector('#admin-forbidden');assert page.locator('#admin-workbench').count()==0
            assert page.request.get(origin+'/api/admin/users').status==403
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();store.close()
