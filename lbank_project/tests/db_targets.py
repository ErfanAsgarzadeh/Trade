"""Run a test module on SQLite and, when a disposable PostgreSQL URL is configured, on PostgreSQL."""
import os

from cryptography.fernet import Fernet
import pytest

from portal_store import PortalStore

TARGETS = ['sqlite', 'postgres']


def fresh_store(target, tmp_path):
    if target == 'postgres':
        url = os.getenv('PORTAL_TEST_DATABASE_URL')
        if not url:pytest.skip('Disposable PostgreSQL test URL not configured')
        if os.getenv('PORTAL_TEST_ALLOW_RESET') != '1':pytest.fail('Set PORTAL_TEST_ALLOW_RESET=1 ONLY for a disposable test database')
        store = PortalStore(url, Fernet.generate_key())
        with store.db() as db:
            tables = [r['tablename'] for r in db.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='schema_migrations'").fetchall()]
            db.execute('TRUNCATE ' + ','.join(tables) + ' RESTART IDENTITY CASCADE')
        return store
    return PortalStore(tmp_path / 'portal.db', Fernet.generate_key())
