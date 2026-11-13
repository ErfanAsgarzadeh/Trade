"""Real browser theme lifecycle, pre-hydration bootstrap and WCAG contrast."""
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


def test_appearance_lifecycle_contrast_and_prepaint(tmp_path):
    pw=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    if not executable:pytest.skip('Chromium unavailable')
    store=PortalStore(tmp_path/'appearance.db',Fernet.generate_key())
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(create_app(store,origin=origin,secure=False),log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox'])
            context=browser.new_context(color_scheme='light',reduced_motion='reduce')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and ('Hydration' in m.text or 'Content Security Policy' in m.text) else None)
            page.goto(origin);switch=page.get_by_label('انتخاب ظاهر')
            assert page.locator('html').get_attribute('data-theme')=='dark'
            switch.select_option('light');page.wait_for_function("()=>document.documentElement.dataset.theme==='light'")
            page.reload();pw.expect(switch).to_have_value('light')
            cold=context.new_page();cold.route('**/_next/**/*.js',lambda route:route.abort())
            cold.goto(origin,wait_until='domcontentloaded')
            assert cold.locator('html').get_attribute('data-theme')=='light';cold.close()
            other=context.new_page();other.goto(origin)
            switch.select_option('dark');other.wait_for_function("()=>document.documentElement.dataset.theme==='dark'")
            switch.select_option('system');page.wait_for_function("()=>document.documentElement.dataset.theme==='light'")
            page.emulate_media(color_scheme='dark');page.wait_for_function("()=>document.documentElement.dataset.theme==='dark'")
            for theme in ('dark','light'):
                switch.select_option(theme)
                for width in (320,390,768,1440):
                    page.set_viewport_size({'width':width,'height':950})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                pairs=page.evaluate('''()=>{
                  const style=getComputedStyle(document.documentElement),ctx=document.createElement('canvas').getContext('2d');
                  const rgb=n=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=style.getPropertyValue('--'+n);ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].slice(0,3)};
                  const lum=n=>rgb(n).map(v=>v/255).reduce((s,v,i)=>s+[.2126,.7152,.0722][i]*(v<=.04045?v/12.92:((v+.055)/1.055)**2.4),0);
                  const ratio=(a,b)=>{let x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
                  const results=[];
                  for(const f of ['text-primary','text-secondary','primary','ai-accent','premium-text','profit-text','loss'])
                    for(const b of ['background','surface','surface-elevated'])results.push([f,b,ratio(f,b),4.5]);
                  for(const [f,b] of [['warning','warning-background'],['success','success-background'],['error','error-background'],['primary-foreground','primary']])results.push([f,b,ratio(f,b),4.5]);
                  results.push(['input-border','input',ratio('input-border','input'),3]);return results;
                }''')
                assert all(r[2]>=r[3] for r in pairs),[r for r in pairs if r[2]<r[3]]
                assert page.locator('#equity-stroke stop').last.evaluate("e=>getComputedStyle(e).stopColor") in ('rgb(201, 178, 255)','rgb(90, 58, 168)')
                switch.focus();assert switch.evaluate("e=>getComputedStyle(e).outlineStyle")!='none'
                screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path)))
                screenshots.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(screenshots/f'home-{theme}-desktop.png'))
                page.set_viewport_size({'width':390,'height':950})
                page.screenshot(path=str(screenshots/f'home-{theme}-mobile.png'))
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();store.close()


def test_standalone_terminal_and_real_chart_redraw(tmp_path):
    pw=pytest.importorskip('playwright.sync_api')
    executable=os.getenv('PORTAL_TEST_CHROMIUM') or shutil.which('chromium')
    chart_js=os.getenv('PORTAL_TEST_CHART_JS')
    if not executable or not chart_js:pytest.skip('Set PORTAL_TEST_CHART_JS to the existing Chart.js 4.4.1 UMD for an offline browser test')
    import json
    from dashboard_server import HTML
    snapshot=json.loads((Path(__file__).resolve().parents[1]/'frontend/public/backtest/five-year-summary.json').read_text())
    with pw.sync_playwright() as p:
        browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox'])
        context=browser.new_context(reduced_motion='reduce',viewport={'width':1440,'height':1000})
        page=context.new_page();errors=[];requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(request):
            url=request.request.url
            if 'chart.umd.min.js' in url:request.fulfill(body=Path(chart_js).read_bytes(),content_type='text/javascript')
            elif url=='http://terminal.test/':request.fulfill(body=HTML,content_type='text/html')
            else:requests.append(url);request.abort()
        page.route('**/*',route);page.goto('http://terminal.test/')
        page.evaluate('''snapshot=>{
          const p={seed:snapshot.initial,all:{},drawdown_now:0,drawdown_max:0,
            snapshots:snapshot.daily.map(([day,equity])=>({t:Date.parse(day)/1000,equity})),
            realized_curve:[],daily:{},bots:{},monthly:{},recent:[]};
          renderPerf(p);
        }''',snapshot)
        before=page.evaluate("Chart.getChart(document.getElementById('eq_chart')).data.datasets[0].data")
        for theme in ('dark','light'):
            page.locator('#terminal-appearance').select_option(theme)
            colors=page.evaluate("['eq_chart','dd_chart'].map(id=>Chart.getChart(document.getElementById(id)).data.datasets[0].borderColor)")
            assert [x.lower() for x in colors]==(['#c9b2ff','#ff7d9c'] if theme=='dark' else ['#5a3aa8','#b4234f'])
            assert page.evaluate("Chart.getChart(document.getElementById('eq_chart')).data.datasets[0].data")==before
            for tab in ('overview','positions','performance','settings'):
                page.locator('[data-tab="'+tab+'"]').click()
                for width in (320,768,1440):
                    page.set_viewport_size({'width':width,'height':1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(theme,tab,width,page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.className,e.id,e.getBoundingClientRect().width]).slice(0,20)"))
            screenshots=Path(os.getenv('PORTAL_SCREENSHOTS',str(tmp_path)))
            screenshots.mkdir(parents=True,exist_ok=True)
            page.locator('[data-tab="overview"]').click();page.screenshot(path=str(screenshots/f'terminal-{theme}.png'),full_page=True)
        assert not errors,errors
        assert not any('/api/' in url for url in requests),requests
        browser.close()
