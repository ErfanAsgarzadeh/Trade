"""The server diagnostic must not leak config values or inherit trading credentials."""
import json
from pathlib import Path
from tools import server_preflight as preflight


def test_config_only_reports_allowlisted_fields(tmp_path):
    config=tmp_path/'live_config.json'
    config.write_text(json.dumps({'mode':'SECRET_VALUE','api_key':'SECRET_VALUE','adopt_existing':False}))
    result=preflight.safe_config(config)
    assert result=={'status':'READABLE','mode':'UNKNOWN','adopt_existing':False}
    assert 'SECRET_VALUE' not in json.dumps(result)


def test_test_output_never_echoes_secrets_or_paths():
    result=preflight.test_summary('SECRET_VALUE\nFAILED tests/test_live_mirror.py::test_fake[SECRET_VALUE]\n1 failed, 4 passed',1)
    assert result['counts']=={'passed':4,'failed':1}
    assert result['failed_tests']==['test_live_mirror.py::test_fake']
    assert 'SECRET_VALUE' not in json.dumps(result)
    assert preflight.test_summary('all skipped',0)['status']!='PASS'


def test_regression_process_isolated_from_live_environment(tmp_path,monkeypatch):
    project=tmp_path/'project';tests=project/'tests';tests.mkdir(parents=True)
    (tests/'baseline_config.json').write_text('{}')
    for filename in preflight.TESTS:(tests/filename).touch()
    monkeypatch.setenv('TTT_API_KEY','SECRET_VALUE');monkeypatch.setenv('BINANCE_API_SECRET','SECRET_VALUE')
    monkeypatch.setenv('BOT_DB','/production/account.db')
    def run(args,cwd=None,timeout=None,env=None):
        assert 'SECRET_VALUE' not in json.dumps(env)
        assert 'TTT_API_KEY' not in env and 'BINANCE_API_SECRET' not in env
        assert env['BOT_DB']!='/production/account.db'
        assert Path(env['BOT_CONFIG']).read_text()=='{}'
        guard=Path(env['RISK_DIR'])/'trade_preflight_guard.py'
        assert guard.is_file() and 'Preflight regression blocks non-loopback network' in guard.read_text()
        assert 'trade_preflight_guard' in args
        return 0,'20 passed'
    monkeypatch.setattr(preflight,'command',run)
    assert preflight.run_tests(Path('/python'),project,{name:'1' for name in preflight.PACKAGES})['status']=='PASS'
