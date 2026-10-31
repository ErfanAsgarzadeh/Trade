import copy
import json
from pathlib import Path

import pytest

import lbank_official_candles as F
import lbank_bot as B
import c3_sleeve as C
import pa_sleeve as P

NOW = 125000 * F.H4 + 600
SYMBOL = 'BTC/USDT:USDT'


def payload(count=1000):
    boundary = NOW // F.H4 * F.H4
    raw = [dict(InstrumentID='BTCUSDT', ExchangeID='Exchange', PeriodID='4h',
                BeginTime=boundary - (count - i) * F.H4, OpenPrice='100',
                HighestPrice='102', LowestPrice='98', ClosePrice='101', Volume='12')
           for i in range(count)]
    return dict(success=True, status=0, dataWrapper=raw)


def test_explicit_closed_history_is_not_dropped_by_any_engine(tmp_path):
    rows = F.parse(payload(), SYMBOL, NOW)
    F.publish(tmp_path, SYMBOL, rows, NOW)
    batch = F.read_history(tmp_path, SYMBOL, '4h', 800, NOW)
    assert batch.closed_only and len(batch) == 799
    expected = (NOW // F.H4 - 1) * F.H4 * 1000
    root = Path(__file__).parents[1]
    cfg = B.validate_config(json.loads((root / 'config.json').read_text()))
    assert B.indicators(batch, cfg, '4h', NOW).iloc[-1].timestamp == expected
    assert C.features(batch, NOW, C.load(root / 'c3_config.json')).iloc[-1].timestamp == expected
    assert P.features(batch, NOW, P.load(root / 'pa_config.json')).iloc[-1].timestamp == expected
    # Unmarked legacy batches still drop the final forming row, as before.
    assert B.closed_rows(list(batch)) == batch[:-1]
    assert B.atr_regime_ratio(batch, cfg, '4h', NOW, 60) == pytest.approx(
        B.atr_regime_ratio(list(batch) + [[NOW // F.H4 * F.H4 * 1000, 100, 102, 98, 101, 12]],
                           cfg, '4h', NOW, 60))


def test_forming_exchange_candle_is_excluded_and_envelopes_supported():
    body = payload()
    forming = copy.deepcopy(body['dataWrapper'][-1])
    forming['BeginTime'] += F.H4
    body['dataWrapper'].append(forming)
    assert len(F.parse(body, SYMBOL, NOW)) == 1000
    lower = [{k[:1].lower() + k[1:]: v for k, v in r.items()} for r in body['dataWrapper']]
    assert F.parse(dict(code=200, data=lower), SYMBOL, NOW) == F.parse(body, SYMBOL, NOW)


@pytest.mark.parametrize('field,value', [
    ('InstrumentID', 'ETHUSDT'), ('ExchangeID', 'Other'), ('PeriodID', '1h'),
    ('OpenPrice', 'NaN'), ('OpenPrice', '103'), ('LowestPrice', '0'),
    ('Volume', '-1'), ('BeginTime', NOW + F.H4),
])
def test_wrong_source_and_invalid_candles_rejected(field, value):
    body = payload()
    body['dataWrapper'][500][field] = value
    with pytest.raises(ValueError):
        F.parse(body, SYMBOL, NOW)


def test_gap_duplicate_short_and_stale_history_rejected():
    body = payload()
    for index in (0, 500, -1):
        modified = copy.deepcopy(body)
        modified['dataWrapper'].pop(index)
        if index == 0:
            assert len(F.parse(modified, SYMBOL, NOW)) == 999
        else:
            with pytest.raises(ValueError):
                F.parse(modified, SYMBOL, NOW)
    duplicate = copy.deepcopy(body)
    duplicate['dataWrapper'][500] = duplicate['dataWrapper'][499]
    with pytest.raises(ValueError):
        F.parse(duplicate, SYMBOL, NOW)
    with pytest.raises(ValueError):
        F.parse(payload(998), SYMBOL, NOW)
    with pytest.raises(ValueError):
        F.parse(dict(success=False, status=0, dataWrapper=[]), SYMBOL, NOW)


def test_receipt_binding_freshness_and_no_legacy_fallback(tmp_path):
    rows = F.parse(payload(), SYMBOL, NOW)
    F.publish(tmp_path, SYMBOL, rows, NOW)
    path, receipt = F.paths(tmp_path, SYMBOL)
    for stamp in (NOW - 1, NOW + 601, NOW + F.H4):
        with pytest.raises(ValueError):
            F.read_history(tmp_path, SYMBOL, '4h', 800, stamp)
    with pytest.raises(ValueError):
        F.read_history(tmp_path, SYMBOL, '1h', 800, NOW)
    original = path.read_bytes()
    path.write_bytes(original.replace(b'101.0', b'100.0', 1))
    with pytest.raises(ValueError, match='checksum'):
        F.read_history(tmp_path, SYMBOL, '4h', 800, NOW)
    path.write_bytes(original)
    meta = json.loads(receipt.read_text());meta['source'] = 'spot'
    receipt.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='provenance'):
        F.read_history(tmp_path, SYMBOL, '4h', 800, NOW)


def test_failed_sync_preserves_previous_files(tmp_path, monkeypatch):
    F.publish(tmp_path, SYMBOL, F.parse(payload(), SYMBOL, NOW), NOW)
    path, receipt = F.paths(tmp_path, SYMBOL)
    previous = path.read_bytes(), receipt.read_bytes()
    monkeypatch.setattr(F, 'fetch', lambda *a: dict(success=False))
    assert F.sync([SYMBOL], tmp_path) is False
    assert (path.read_bytes(), receipt.read_bytes()) == previous


def test_marketdata_official_mode_and_collector_dispatch(tmp_path, monkeypatch):
    import lbank_candles as L
    monkeypatch.setenv('PAPER_DATA_MODE', 'csv-lbank')
    monkeypatch.setenv('LBANK_OFFICIAL_CANDLES', '1')
    monkeypatch.setenv('OHLCV_DIR', str(tmp_path))
    monkeypatch.setattr(B.time, 'time', lambda: NOW)
    F.publish(tmp_path, SYMBOL, F.parse(payload(), SYMBOL, NOW), NOW)
    data = B.MarketData()
    monkeypatch.setattr(data, 'market', lambda s: {})
    assert data.candles(SYMBOL, '4h', 800).closed_only
    monkeypatch.setattr(L, 'config_symbols', lambda: [SYMBOL])
    calls = []
    monkeypatch.setattr(F, 'run', lambda *a, **k: calls.append((a, k)) or 0)
    assert L.main(['--once']) == 0
    assert calls[0][1]['once'] is True
