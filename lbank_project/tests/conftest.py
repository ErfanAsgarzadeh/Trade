import os

import pytest

# Production hashes with scrypt n=2**17 (~128 MB, ~0.3 s); the suite creates many users, so it asks for n=2**10.
os.environ.setdefault('PORTAL_SCRYPT_LOG_N', '10')

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


@pytest.fixture(autouse=True)
def movable_totp_clock(monkeypatch):
    """TOTP accepts a time step once. Tests that need several codes in a row move the authenticator clock forward 30 s per code."""
    import time
    import portal_totp
    from totp_helpers import AUTH, SKEW
    SKEW['seconds'] = 0
    AUTH.clear()
    monkeypatch.setattr(portal_totp, 'now', lambda: time.time() + SKEW['seconds'])
