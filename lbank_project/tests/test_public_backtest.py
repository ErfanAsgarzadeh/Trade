"""Public marketing figures must reconcile to the bounded frozen research output."""
import csv
from datetime import date,timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from portal_server import create_app

FRONTEND=Path(__file__).parents[1]/'frontend'
PUBLIC=FRONTEND/'public/backtest'


def test_five_complete_years_and_advertised_metrics_reconcile():
    summary=json.loads((PUBLIC/'five-year-summary.json').read_text())
    rows=list(csv.DictReader((PUBLIC/'five-year-daily.csv').open()))
    assert summary['days']==len(rows)==1826
    assert [r['date'][:10] for r in rows]==[(date(2021,1,1)+timedelta(days=i)).isoformat() for i in range(1826)]
    assert rows[-1]['date'][:10]=='2025-12-31'
    assert float(rows[-1]['equity'])==summary['final']
    assert summary['initial']==10000
    assert summary['final']==pytest.approx(964451.7704777746)
    assert summary['max_minute_dd_pct']==-min(float(r['worst_minute_dd_pct']) for r in rows)
    assert summary['max_minute_dd_pct']==pytest.approx(30.69925699421282)
    assert summary['return_pct']==pytest.approx((summary['final']/summary['initial']-1)*100)
    assert summary['initial']*math.prod(1+r['return_pct']/100 for r in summary['monthly'])==pytest.approx(summary['final'])
    assert summary['initial']*math.prod(1+r['return_pct']/100 for r in summary['annual'])==pytest.approx(summary['final'])
    assert hashlib.sha256((PUBLIC/'five-year-daily.csv').read_bytes()).hexdigest()==summary['provenance']['public_csv_sha256']
    assert summary['execution']=='historical_simulation' and summary['assumptions']['f_enabled'] is False
    assert summary['assumptions']['withdrawals'] is False


def test_snapshot_generator_is_reproducible_and_rejects_unreviewed_data(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('public_backtest_builder',FRONTEND/'tools/build_public_backtest.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=tmp_path/'public/backtest';output.mkdir(parents=True)
    original=(PUBLIC/'five-year-summary.json').read_bytes();(output/'five-year-summary.json').write_bytes(original)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    module.build(PUBLIC/'five-year-daily.csv')
    assert (output/'five-year-summary.json').read_bytes()==original
    bad=tmp_path/'bad.csv';bad.write_text('date,equity,worst_minute_dd_pct\n2025-12-31,9999999,0\n')
    with pytest.raises(ValueError,match='Unreviewed'):module.build(bad)


def test_homepage_dashboard_and_public_evidence_are_distinct():
    origin='http://127.0.0.1:8080'
    with TestClient(create_app(store=object(),origin=origin,secure=False),base_url=origin) as client:
        homepage=client.get('/')
        assert homepage.status_code==200 and 'hero-title' in homepage.text
        assert 'backtest-motion' in homepage.text and 'login-form' not in homepage.text
        dashboard=client.get('/dashboard/')
        assert dashboard.status_code==200 and 'login-form' in dashboard.text
        assert "'sha256-" in dashboard.headers['content-security-policy']
        response=client.get('/backtest/five-year-summary.json')
        assert response.status_code==200 and response.json()['end']=='2025-12-31'
        assert client.get('/backtest/five-year-daily.csv').status_code==200
