import pytest

@pytest.fixture(autouse=True)
def isolated_c3_paths(tmp_path_factory,monkeypatch):
    """No test may touch the shipped c3_config.json or the real C3 database (the emergency stop writes C3 config)."""
    d=tmp_path_factory.mktemp('c3_isolated')
    monkeypatch.setenv('C3_CONFIG',str(d/'c3_config.json'));monkeypatch.setenv('C3_DB',str(d/'c3_sleeve.db'))
