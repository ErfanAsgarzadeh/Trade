import pytest

@pytest.fixture(autouse=True)
def isolated_c3_paths(tmp_path_factory,monkeypatch):
    """No test may touch the shipped c3_config.json or the real C3 database (the emergency stop writes C3 config)."""
    d=tmp_path_factory.mktemp('c3_isolated')
    monkeypatch.setenv('C3_CONFIG',str(d/'c3_config.json'));monkeypatch.setenv('C3_DB',str(d/'c3_sleeve.db'))
    monkeypatch.setenv('PA_CONFIG',str(d/'pa_config.json'));monkeypatch.setenv('PA_DB',str(d/'pa_sleeve.db'))


@pytest.fixture(autouse=True)
def no_exchange_readback_waits(monkeypatch):
    """Exchange readback retries wait a second in production; tests do not need to."""
    import exchanges
    monkeypatch.setattr(exchanges, 'pause', lambda seconds: None)
