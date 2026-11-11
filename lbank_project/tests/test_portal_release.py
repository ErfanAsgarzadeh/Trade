import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import yaml
import pytest
from tools import prepare_portal_release as release


def make_source(root):
    for name in release.MODULES:(root/name).write_text('# fixture\n')
    for page in ('index.html','dashboard.html','admin.html','register.html'):
        file=root/'frontend/out'/page;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('<html></html>')
    public=root/'frontend/public';public.mkdir(parents=True)
    (public/'manifest.webmanifest').write_text('{}')
    return root


def test_release_allowlist_hashes_no_runtime_and_no_node_build(tmp_path):
    source=tmp_path/'source';source.mkdir();make_source(source)
    (source/'.env').write_text('PRIVATE_SECRET')
    (source/'runtime').mkdir();(source/'runtime/account.db').write_text('PRIVATE_ACCOUNT')
    archive=tmp_path/'preview.tar.gz'
    result=release.build(archive,source)
    with tarfile.open(archive) as stream:
        contents={Path(member.name).relative_to('trade-portal-preview').as_posix():stream.extractfile(member).read() for member in stream.getmembers()}
    assert b'PRIVATE_SECRET' not in b''.join(contents.values()) and b'PRIVATE_ACCOUNT' not in b''.join(contents.values())
    manifest=json.loads(contents['release-manifest.json'])
    for name,digest in manifest['sha256'].items():assert hashlib.sha256(contents[name]).hexdigest()==digest
    assert result['release_tag']==manifest['release_tag'] and not manifest['live_execution_enabled']
    assert b'node:' not in contents['Dockerfile'] and b'npm' not in contents['Dockerfile']
    compose=yaml.safe_load(contents['compose.yml'])
    assert compose['name']=='trade-portal-preview'
    assert compose['services']['portal']['ports']==['127.0.0.1:18080:8080']
    assert compose['services']['portal']['mem_limit']=='256m'
    assert compose['services']['account-worker']['profiles']==['account-read']
    with pytest.raises(FileExistsError):release.build(archive,source)


def test_release_rejects_secret_or_symlink_in_public_assets(tmp_path):
    source=make_source(tmp_path)
    secret=source/'frontend/public/.env';secret.write_text('PRIVATE')
    with pytest.raises(ValueError):release.build(tmp_path/'preview.tar.gz',source)
    secret.unlink();(source/'frontend/public/unsafe.txt').symlink_to(source/'requirements.txt')
    with pytest.raises(ValueError):release.build(tmp_path/'preview.tar.gz',source)


def test_preview_initializer_preserves_key_and_does_not_start_services(tmp_path):
    script=tmp_path/'initialize_preview.py';script.write_text(release.INIT)
    first=subprocess.check_output([sys.executable,str(script)],text=True)
    key=tmp_path/'preview-secrets/portal.key';data=key.read_bytes()
    subprocess.check_call([sys.executable,str(script)])
    assert data==key.read_bytes() and len(data.strip())==44
    assert key.stat().st_mode & 0o777==0o600
    assert data.decode().strip() not in first


def test_packaged_portal_runs_without_importing_source_checkout(tmp_path):
    if not (release.ROOT/'frontend/out/index.html').is_file():pytest.skip('Build frontend first')
    archive=tmp_path/'preview.tar.gz';release.build(archive)
    with tarfile.open(archive) as stream:stream.extractall(tmp_path/'unpacked',filter='data')
    packaged=tmp_path/'unpacked/trade-portal-preview'
    code='''
import json
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from portal_server import create_app
from portal_store import PortalStore
store=PortalStore(Path('isolated-smoke.db'),Fernet.generate_key())
origin='http://127.0.0.1:18080'
with TestClient(create_app(store,origin=origin,secure=False),base_url=origin) as client:
    for path in ('/','/dashboard/','/register/','/admin/','/healthz'):
        assert client.get(path).status_code==200,path
    assert not any(p['sales_enabled'] for p in client.get('/api/plans').json()['products'])
    result=client.post('/api/register',headers={'X-Portal-Request':'1'},json={'username':'preview-user','password':'disposable-preview-password','password_confirmation':'disposable-preview-password'})
    assert result.status_code==201,result.status_code
    entries=client.get('/api/exchanges').json()['exchanges']
    assert next(e for e in entries if e['id']=='thetruetrade')['markets']==['futures']
    state=client.get('/api/me/execution-readiness').json()
    assert not state['trading_enabled'] and state['status']=='license_required'
store.close()
print('PACKAGED_PORTAL_OK')
'''
    import os
    env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    process=subprocess.run([sys.executable,'-c',code],cwd=packaged,env=env,capture_output=True,text=True,timeout=30)
    assert process.returncode==0,process.stderr
    assert process.stdout.strip()=='PACKAGED_PORTAL_OK'
