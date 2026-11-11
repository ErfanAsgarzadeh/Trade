#!/usr/bin/env python3
"""Non-activating server preflight. Stdlib only; never reads .env or account keys.

Run from a checkout: python3 lbank_project/tools/server_preflight.py --repo .
Reports contain only allowlisted metadata. Child test output is summarized,
never echoed. No installs, build, service start, order, or config writes occur.
Test processes may write only their usual disposable fixtures/cache in /tmp.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

TESTS = (
    'test_capital_licensing.py', 'test_signup_products.py', 'test_customer_distribution.py',
    'test_portal.py', 'test_admin_workbench.py', 'test_portal_queue.py',
    'test_momentum.py', 'test_shared_paper_account.py',
    'test_portfolio_runtime.py', 'test_live_mirror.py', 'test_multi_exchange.py',
    'test_ttt_live_readiness.py', 'test_ttt_stop_audit.py', 'test_ttt_account_audit.py',
    'test_ttt_protection_readback.py', 'test_ttt_one_time_tpsl.py',
    'test_paper_forward_audit.py', 'test_portal_frontend.py', 'test_public_backtest.py',
    'test_portal_thetruetrade.py',
)
PACKAGES = ('ccxt','pandas','numpy','fastapi','uvicorn','pydantic','cryptography',
            'pytest','httpx','yaml')
DISTRIBUTIONS = {name: ('PyYAML' if name == 'yaml' else name) for name in PACKAGES}
BLOCKERS = [
    'CUSTOMER_PORTAL_LIVE_EXECUTION_IS_DISABLED',
    'LIVE_CUSTOMER_PROVISIONING_AND_LICENSE_TO_EXECUTOR_END_TO_END_NOT_VERIFIED',
    'AUTHENTICATED_EXCHANGE_PERMISSIONS_BALANCE_AND_POSITION_READBACK_NOT_TESTED',
    'REAL_ORDER_STOP_UPDATE_PARTIAL_FILL_RECONNECT_AND_EMERGENCY_CLOSE_NOT_TESTED',
    'DOMAIN_TLS_BACKUPS_AND_MONITORING_NOT_VERIFIED',
]


def command(args, cwd=None, timeout=15, env=None):
    try:
        p=subprocess.run(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
        return p.returncode,p.stdout
    except (OSError, subprocess.SubprocessError):
        return -1,''


def package_probe(executable):
    source = ('import importlib.util,importlib.metadata,json; '
              'names='+repr(DISTRIBUTIONS)+'; '
              'result={};\n'
              'for module,dist in names.items():\n'
              ' try: result[module]=importlib.metadata.version(dist) if importlib.util.find_spec(module) else None\n'
              ' except Exception: result[module]=None\n'
              'print(json.dumps(result))')
    code,out=command([str(executable),'-c',source])
    try:return json.loads(out) if code==0 else {}
    except ValueError:return {}


def choose_python(root):
    candidates=[Path(sys.executable),root/'.venv/bin/python',root/'venv/bin/python',
                root/'lbank_project/.venv/bin/python',Path('/workspace/backtest-venv/bin/python')]
    best,packages=Path(sys.executable),{}
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file():
            found=package_probe(candidate)
            if sum(v is not None for v in found.values())>sum(v is not None for v in packages.values()):
                best,packages=candidate,found
            if found and all(found.values()):break
    return best,packages


def safe_config(path):
    if not path.is_file():return {'status':'NOT_FOUND'}
    try:
        data=json.loads(path.read_text())
        if not isinstance(data,dict):return {'status':'INVALID'}
        mode=data.get('mode')
        return {'status':'READABLE','mode':mode if mode in ('off','dry','live') else 'UNKNOWN',
                'adopt_existing':data.get('adopt_existing') if isinstance(data.get('adopt_existing'),bool) else None}
    except (OSError,ValueError,UnicodeError):return {'status':'INVALID'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def public_get(url):
    try:
        opener=urllib.request.build_opener(NoRedirect())
        with opener.open(urllib.request.Request(url,method='GET',headers={'User-Agent':'Trade-preflight/1'}),timeout=8) as response:
            return {'http_status':response.status,'tls_verified':True,'authenticated':False}
    except urllib.error.HTTPError as exc:
        return {'http_status':exc.code,'tls_verified':True,'authenticated':False}
    except Exception as exc:
        return {'status':'UNREACHABLE','error_type':type(exc.reason).__name__ if isinstance(exc,urllib.error.URLError) else type(exc).__name__,'authenticated':False}


def test_summary(output,code):
    # Never return raw tracebacks, paths, environment, stdout, or exception messages.
    counts={}
    for label in ('passed','failed','skipped','errors','error','deselected'):
        matches=re.findall(r'\b(\d+) '+label+r'\b',output)
        if matches:counts[label]=int(matches[-1])
    return {'status':'PASS' if code==0 and counts.get('passed',0)>0 else 'FAIL_OR_UNAVAILABLE',
            'exit_code':code,'counts':counts,'failed_tests':sorted({module+'::'+name for module,name in re.findall(r'FAILED [^\n]*?/?(test_\w+\.py)::(test_\w+)',output) if module in TESTS})[:20],'raw_output_included':False,
            'scope':'isolated tests and mocked exchange adapters; not real-order certification'}


def run_tests(python,project,packages):
    files=[project/'tests'/name for name in TESTS]
    if not all(path.is_file() for path in files):return {'status':'BLOCKED_TEST_FILES_MISSING'}
    if not packages or not all(packages.get(name) for name in PACKAGES):
        return {'status':'BLOCKED_TEST_DEPENDENCIES_MISSING'}
    with tempfile.TemporaryDirectory(prefix='trade-preflight-') as temporary:
        # Do not pass trading credentials or production paths into regression tests.
        env={key:os.environ[key] for key in ('PATH','HOME','LANG','LC_ALL','LD_LIBRARY_PATH','SSL_CERT_FILE') if key in os.environ}
        sandbox=Path(temporary)
        shutil.copyfile(project/'tests/baseline_config.json',sandbox/'config.json')
        guard=sandbox/'trade_preflight_guard.py'
        guard.write_text("""import socket, ipaddress

def pytest_sessionstart(session):
    original=socket.socket.connect
    original_ex=socket.socket.connect_ex
    def allowed(sock,address):
        if sock.family==socket.AF_UNIX:return True
        try:return ipaddress.ip_address(address[0]).is_loopback
        except (ValueError,TypeError):return address[0]=='localhost'
    def connect(sock,address):
        if not allowed(sock,address):raise OSError('Preflight regression blocks non-loopback network')
        return original(sock,address)
    def connect_ex(sock,address):
        if not allowed(sock,address):raise OSError('Preflight regression blocks non-loopback network')
        return original_ex(sock,address)
    socket.socket.connect=connect
    socket.socket.connect_ex=connect_ex
""")
        env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=temporary,
                   PYTHONPATH=os.pathsep.join((temporary,str(project))),
                   PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTEST_ADDOPTS='',PYTEST_PLUGINS='',
                   BOT_CONFIG=str(sandbox/'config.json'),BOT_DB=str(sandbox/'bot.db'),
                   BOT_RUNTIME_DIR=temporary,RISK_DIR=temporary,
                   C3_CONFIG=str(sandbox/'c3.json'),C3_DB=str(sandbox/'c3.db'),
                   PA_CONFIG=str(sandbox/'pa.json'),PA_DB=str(sandbox/'pa.db'),
                   PORTAL_DB=str(sandbox/'portal.db'),PORTAL_KEY_FILE=str(sandbox/'portal.key'),
                   BOT_PIN='preflight-disposable-test-pin',BOT_LICENSE_REQUIRED='0',
                   PAPER_DATA_MODE='demo',PAPER_EQUITY='10000',BOT_SIGNAL_FEED_ENABLED='0')
        code,out=command([str(python),'-m','pytest','-q','-p','no:cacheprovider','-p','trade_preflight_guard',
                          '--basetemp',str(Path(temporary)/'pytest'),*[str(path) for path in files]],
                         cwd=project,timeout=300,env=env)
        return test_summary(out,code)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--skip-tests',action='store_true',help='Report tests as NOT_RUN')
    parser.add_argument('--skip-network',action='store_true',help='Skip public unauthenticated GET probes')
    args=parser.parse_args(argv)
    root=args.repo.resolve()
    if root.name=='lbank_project':root=root.parent
    project=root/'lbank_project'
    report={'schema':1,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
            'read_only_toward_trading':True,'environment_files_read':False,'credentials_used':False,'orders_sent':False,
            'services_started':False,'live_trading_authorized':False,'checks':{}}
    checks=report['checks']
    if not (project/'portal_server.py').is_file():
        report.update(conclusion='NOT_READY',blockers=['TRADE_CHECKOUT_NOT_FOUND'])
        print(json.dumps(report,indent=2));return 0
    code,head=command(['git','rev-parse','HEAD'],cwd=root)
    checks['source_commit']=head.strip() if code==0 and re.fullmatch('[a-f0-9]{40}\n?',head) else 'UNKNOWN'
    code,_=command(['git','merge-base','--is-ancestor','5d3a7ce', 'HEAD'],cwd=root)
    checks['titanium_release_present']=code==0
    disk=shutil.disk_usage(root)
    mem={}
    try:
        mem={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.split(':')[0] in ('MemTotal','MemAvailable')}
    except (OSError,ValueError):pass
    checks['resources']={'cpu_count':os.cpu_count(),'load_1_5_15':list(os.getloadavg()) if hasattr(os,'getloadavg') else None,
                         'disk_free_gib':round(disk.free/2**30,2),'ram_available_gib':round(mem['MemAvailable']/2**20,2) if 'MemAvailable' in mem else None,
                         'capacity_for_live_trading':'NOT_DETERMINED_BY_RESOURCE_SNAPSHOT'}
    code,out=command(['timedatectl','show','--property=NTPSynchronized','--value'])
    checks['ntp_synchronized']=out.strip()=='yes' if code==0 else 'UNKNOWN'
    code,out=command(['docker','version','--format','{{.Server.Version}}'])
    checks['docker_daemon']={'reachable':code==0,'version':out.strip() if re.fullmatch(r'[\d.\w+-]+\n?',out) else None}
    code,out=command(['docker','compose','version','--short'])
    checks['docker_compose']={'available':code==0,'version':out.strip() if re.fullmatch(r'v?[\d.\w+-]+\n?',out) else None}
    code,out=command(['node','--version'])
    checks['node_version']=out.strip() if code==0 and re.fullmatch(r'v\d+\.\d+\.\d+\n?',out) else None
    listeners=[]
    for filename in ('/proc/net/tcp','/proc/net/tcp6'):
        try:
            for line in Path(filename).read_text().splitlines()[1:]:
                fields=line.split()
                if fields[3]=='0A':listeners.append(int(fields[1].split(':')[-1],16))
        except (OSError,ValueError,IndexError):pass
    checks['local_listeners']={str(port):port in listeners for port in (80,443,8000,8080)}
    checks['live_configs']={label:safe_config(project/relative) for label,relative in
                           (('runtime','runtime/live_config.json'),('data','data/live_config.json'))}
    checks['runtime_config_scope']='default paths only; custom paths and customer containers are NOT inspected'
    checks['frontend_export']={name:(project/'frontend/out'/name).is_file() for name in ('index.html','dashboard.html','admin.html','register.html')}
    python,packages=choose_python(root)
    code,out=command([str(python),'-c','import platform; print(platform.python_version())'])
    checks['test_python_version']=out.strip() if code==0 and re.fullmatch(r'\d+\.\d+\.\d+\n?',out) else None
    checks['python_packages']=packages
    checks['offline_regression']= {'status':'NOT_RUN'} if args.skip_tests else run_tests(python,project,packages)
    if args.skip_network:checks['public_network']={'status':'NOT_RUN'}
    else:checks['public_network']={name:public_get(url) for name,url in (
        ('binance_futures','https://fapi.binance.com/fapi/v1/time'),
        ('lbank','https://api.lbkex.com/v2/timestamp.do'),
        ('thetruetrade','https://apiv2.thetruetrade.io/futures/markets'))}
    blockers=list(BLOCKERS)
    if not checks['titanium_release_present']:blockers.append('CHECKOUT_IS_OLDER_THAN_PORTAL_THEME_RELEASE')
    if not all(checks['frontend_export'].values()):blockers.append('FRONTEND_EXPORT_MISSING')
    if checks['offline_regression']['status']!='PASS':blockers.append('REGRESSION_TESTS_NOT_PASSED')
    if any(c.get('mode')=='live' for c in checks['live_configs'].values()):blockers.append('LIVE_MODE_ALREADY_CONFIGURED_NO_CHANGES_MADE')
    report.update(conclusion='NOT_READY_FOR_CUSTOMER_LIVE_TRADING',blockers=blockers,
                  note='Public network reachability and passing offline tests do not verify account permissions or live execution. No setting was enabled.')
    print(json.dumps(report,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
