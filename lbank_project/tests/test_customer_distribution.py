import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
import zipfile

import httpx
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

import customer_manager as M
import customer_entrypoint as E
import license_access as L
import c3_sleeve as C
import pa_sleeve as P
from dashboard_server import create_app
from test_system import system, cfg, setup_position


@pytest.fixture
def issuer(tmp_path):
    private=tmp_path/'issuer.private.pem';public=tmp_path/'issuer.public.pem'
    M.keygen(private,public)
    return private,public


@pytest.fixture
def customer(tmp_path,issuer):
    private,public=issuer
    return M.create(tmp_path/'customers','alice',private,public,8101,1000.)


def use_license(monkeypatch,customer,identity='alice'):
    monkeypatch.setenv('BOT_LICENSE_REQUIRED','1')
    monkeypatch.setenv('BOT_LICENSE_FILE',str(customer/'license/license.json'))
    monkeypatch.setenv('BOT_LICENSE_PUBLIC_KEY_FILE',str(customer/'license/license_public.pem'))
    monkeypatch.setenv('BOT_CUSTOMER_ID',identity)


def test_customer_bootstrap_isolated_and_export_allowlist(tmp_path,issuer,customer):
    private,public=issuer
    bob=M.create(tmp_path/'customers','bob',private,public,8102,2000.)
    assert (customer/'secrets/dashboard_pin').read_text()!=(bob/'secrets/dashboard_pin').read_text()
    assert len((customer/'secrets/dashboard_pin').read_text().strip())==32
    assert json.loads((customer/'runtime/config.json').read_text())['bot_control']['auto_trade_enabled'] is False
    assert json.loads((bob/'runtime/pa_config.json').read_text())['paper_capital']==2000.
    (customer/'app/accidental-secret.txt').write_text('must not ship')
    archive=M.export(tmp_path/'customers','alice',tmp_path/'release.zip')
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist())
        assert 'secrets/dashboard_pin' in names and 'license/license_public.pem' in names
        assert not any('private' in n or n.endswith('.db') or n.endswith('accidental-secret.txt') for n in names)
        assert z.testzip() is None
    with pytest.raises(FileExistsError):M.export(tmp_path/'customers','alice',archive)


@pytest.mark.parametrize('identity',['../bob','ALICE','a/b','a','alice;echo','alice\n'])
def test_reject_unsafe_customer_id(tmp_path,issuer,identity):
    with pytest.raises(ValueError):M.create(tmp_path/'customers',identity,*issuer,8101,1000.)


def test_existing_customer_and_port_cannot_be_reused(tmp_path,issuer,customer):
    root=tmp_path/'customers';before=(customer/'runtime/config.json').read_bytes()
    with pytest.raises(ValueError):M.create(root,'alice',*issuer,8102,2000.)
    with pytest.raises(ValueError):M.create(root,'bob',*issuer,8101,2000.)
    assert (customer/'runtime/config.json').read_bytes()==before


def test_license_signature_customer_expiry_and_missing_files(monkeypatch,customer):
    use_license(monkeypatch,customer)
    original=(customer/'license/license.json').read_text();envelope=json.loads(original)
    start=L.timestamp(envelope['payload']['not_before']);end=L.timestamp(envelope['payload']['expires_at'])
    assert L.status(start)['state']=='active'
    assert L.status(start-1)['state']=='not_yet_valid'
    assert L.status(end)['state']=='expired' and not L.entries_allowed(end)
    monkeypatch.setenv('BOT_CUSTOMER_ID','bob');assert L.status(start)['state']=='invalid'
    monkeypatch.setenv('BOT_CUSTOMER_ID','alice')
    envelope['payload']['expires_at']='2099-01-01T00:00:00+00:00'
    (customer/'license/license.json').write_text(json.dumps(envelope))
    assert not L.entries_allowed(start)
    (customer/'license/license.json').unlink();assert not L.entries_allowed(start)


def test_renew_keeps_positions_config_and_secret(tmp_path,issuer,customer,monkeypatch):
    files=['runtime/config.json','secrets/dashboard_pin','customer.json']
    before={n:(customer/n).read_bytes() for n in files}
    (customer/'runtime/c3_sleeve.db').write_bytes(b'position-placeholder')
    old=json.loads((customer/'license/license.json').read_text())['payload']['license_id']
    M.renew(tmp_path/'customers','alice',issuer[0],90,'professional')
    assert all((customer/n).read_bytes()==b for n,b in before.items())
    assert (customer/'runtime/c3_sleeve.db').read_bytes()==b'position-placeholder'
    assert json.loads((customer/'license/license.json').read_text())['payload']['license_id']!=old
    use_license(monkeypatch,customer);assert L.status()['plan']=='professional'
    with pytest.raises(ValueError):M.export(tmp_path/'customers','alice',tmp_path/'bad.zip')


def test_runtime_cannot_be_attached_to_other_customer(customer,monkeypatch):
    # prepare intentionally fixes process environment; restore every changed key after this test.
    for key in ('BOT_LICENSE_REQUIRED','BOT_CONFIG','BOT_DB','C3_CONFIG','C3_DB',
                'PA_CONFIG','PA_DB','OHLCV_DIR','FUNDING_DIR'):
        monkeypatch.setenv(key,os.environ.get(key,''))
    monkeypatch.setenv('BOT_CUSTOMER_ID','alice');monkeypatch.setenv('BOT_RUNTIME_DIR',str(customer/'runtime'))
    monkeypatch.setenv('BOT_DB','/wrong/customer.db');E.prepare()
    assert Path(os.environ['BOT_DB']).parent==customer/'runtime'
    monkeypatch.setenv('BOT_CUSTOMER_ID','bob')
    with pytest.raises(ValueError,match='another customer'):E.prepare()


def test_expiry_blocks_all_entries_but_keeps_exits(system,customer,issuer,monkeypatch,tmp_path):
    p=setup_position(system,state='STATE_INITIAL')
    # The position existed before expiry; licensing must not interfere with its risk exit.
    expired=M.issue(issuer[0],'alice',1,'beta',datetime.now(timezone.utc)-timedelta(days=2))
    (customer/'license/license.json').write_bytes(expired);use_license(monkeypatch,customer)
    now=time.time();assert not L.entries_allowed(now)
    assert system._activate(p,100.,now) is False
    assert system._pyramid_add(p,'long',pd.Series(),system.config.read(),now) is False
    with pytest.raises(PermissionError):system._insert({})
    c=C.load(Path(C.__file__).with_name('c3_config.json'))
    cs=C.Store(tmp_path/'c3.db');sl=C.Sleeve(c,cs,system.data)
    assert sl.open('AAVE/USDT:USDT','long',pd.Series(dict(atr=1.,close=100.,timestamp=0)),now) is None
    ps=P.Store(tmp_path/'pa.db');pa=P.Sleeve(P.load(Path(P.__file__).with_name('pa_config.json')),ps,system.data)
    pa.store.set_order('LINK/USDT:USDT',dict(side='long',level=100.,stop=95.,signal_ts=0,expires=(now+100)*1000))
    assert pa.open('LINK/USDT:USDT',{},now) is None
    pa.watchdog(now);assert not ps.orders()
    for store,symbol in [(cs,'AAVE/USDT:USDT'),(ps,'LINK/USDT:USDT')]:
        with store.db() as db:
            db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,'long',100.,2.,95.,100.,1.,0,0,10.))
    system.data.prices[p['symbol']]=80.
    system.data.prices['AAVE/USDT:USDT']=90.;system.data.prices['LINK/USDT:USDT']=90.
    system.watchdog(now);sl.watchdog(now);pa.watchdog(now)
    assert system.db.positions()==[] and cs.positions()==[] and ps.positions()==[]


def test_no_default_pin_file_precedence_throttle_and_license_api(system,customer,monkeypatch):
    monkeypatch.delenv('BOT_PIN',raising=False);monkeypatch.delenv('BOT_PIN_FILE',raising=False)
    with TestClient(create_app(system)) as client:
        assert client.get('/api/status',headers={'X-Bot-Pin':'1234'}).status_code==401
        assert client.get('/healthz').json()=={'status':'ok'}
    monkeypatch.setenv('BOT_PIN','wrong-env-secret')
    monkeypatch.setenv('BOT_PIN_FILE',str(customer/'secrets/dashboard_pin'));use_license(monkeypatch,customer)
    pin=(customer/'secrets/dashboard_pin').read_text().strip()
    with TestClient(create_app(system)) as client:
        assert client.get('/api/license',headers={'X-Bot-Pin':pin}).json()['state']=='active'
        assert client.get('/api/license',headers={'X-Bot-Pin':'wrong-env-secret'}).status_code==401
        body=client.get('/api/status',headers={'X-Bot-Pin':pin}).text
        assert pin not in body and 'signature' not in body
        for _ in range(10):assert client.get('/api/status',headers={'X-Bot-Pin':'bad'}).status_code==401
        assert client.get('/api/status',headers={'X-Bot-Pin':pin}).status_code==429


def test_generated_compose_isolated_and_no_credentials(customer):
    compose=yaml.safe_load((customer/'compose.yml').read_text())
    assert 'CUSTOMER_ID' in compose['name']
    for service in compose['services'].values():
        assert service['read_only'] and service['cap_drop']==['ALL']
        assert './runtime:/app/runtime' in service['volumes']
        assert './license:/app/license:ro' in service['volumes']
        assert not any('API_KEY' in key or 'SECRET_KEY' in key for key in service['environment'])
    assert compose['services']['dashboard']['ports'][0].startswith('127.0.0.1:')
    assert compose['services']['candles']['profiles']==['market-data']


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def test_two_customer_processes_have_independent_accounts(tmp_path,issuer):
    """Real bot and HTTP processes for two customers, with different PINs and three DBs each."""
    root=tmp_path/'customers';ports=[free_port(),free_port()]
    while ports[1]==ports[0]:ports[1]=free_port()
    directories=[M.create(root,n,*issuer,port,capital) for n,port,capital in zip(('alice','bob'),ports,(1000.,2000.))]
    processes=[];logs=[]
    try:
        for directory,port in zip(directories,ports):
            name=directory.name
            env={**os.environ,'BOT_CUSTOMER_ID':name,'BOT_RUNTIME_DIR':str(directory/'runtime'),
                 'BOT_LICENSE_FILE':str(directory/'license/license.json'),
                 'BOT_LICENSE_PUBLIC_KEY_FILE':str(directory/'license/license_public.pem'),
                 'BOT_PIN_FILE':str(directory/'secrets/dashboard_pin'),
                 'PAPER_DATA_MODE':'demo','PAPER_EQUITY':str(1000 if name=='alice' else 2000)}
            # Entrypoint normally serves container port 8000. Here retain its setup while using unique host ports.
            code='import customer_entrypoint as e;e.prepare();import uvicorn;uvicorn.run("dashboard_server:app",host="127.0.0.1",port='+str(port)+',proxy_headers=False)'
            for command in ([sys.executable,'-u','customer_entrypoint.py','bot'],[sys.executable,'-c',code]):
                log=(tmp_path/(name+str(len(logs))+'.log')).open('w');logs.append(log)
                processes.append(subprocess.Popen(command,cwd=directory/'app',env=env,stdout=log,stderr=subprocess.STDOUT))
        pins=[(d/'secrets/dashboard_pin').read_text().strip() for d in directories]
        with httpx.Client(trust_env=False,timeout=2) as client:
            deadline=time.monotonic()+30;statuses={}
            while time.monotonic()<deadline:
                assert all(p.poll() is None for p in processes)
                for i,port in enumerate(ports):
                    try:
                        response=client.get(f'http://127.0.0.1:{port}/api/status',headers={'X-Bot-Pin':pins[i]})
                        if response.status_code==200 and response.json()['runtime'].get('watchdog_at'):statuses[i]=response.json()
                    except httpx.TransportError:pass
                if len(statuses)==2:break
                time.sleep(.1)
            assert len(statuses)==2
            assert statuses[0]['equity_usd']==1000 and statuses[1]['equity_usd']==2000
            for i,port in enumerate(ports):
                base=f'http://127.0.0.1:{port}'
                assert client.get(base+'/api/status',headers={'X-Bot-Pin':pins[1-i]}).status_code==401
                assert client.get(base+'/api/license',headers={'X-Bot-Pin':pins[i]}).json()['customer_id']==directories[i].name
            base=f'http://127.0.0.1:{ports[0]}'
            assert client.post(base+'/api/bots/toggle',headers={'X-Bot-Pin':pins[0]},json={'bot':'pa','enabled':True}).status_code==200
            assert json.loads((directories[0]/'runtime/pa_config.json').read_text())['enabled'] is True
            assert json.loads((directories[1]/'runtime/pa_config.json').read_text())['enabled'] is False
            assert all((d/'runtime'/n).exists() for d in directories for n in ('lbank_ichimoku_bot.db','c3_sleeve.db','pa_sleeve.db'))
    finally:
        for p in processes:p.terminate()
        for p in processes:
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()
