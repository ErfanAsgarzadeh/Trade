"""No-trade safety and privacy tests for TheTrueTrade stop readback discovery."""
import pytest

import exchanges as X
import ttt_stop_audit as audit


def test_discovery_never_claims_a_confirmed_stop():
    rows = [
        {"id": "sensitive-id", "userId": "secret-123", "symbol": "BTCUSDT",
         "status": "OPENED", "size": "0.01", "entryPrice": "80000",
         "stopLoss": "79000", "nested": {"stopLossPrice": "79000"}},
        {"id": "secret-other", "userId": "private", "symbol": "ETHUSDT",
         "status": "OPENED", "size": "1", "entryPrice": "2000"},
    ]
    result = audit.audit_rows(rows)
    assert result["position_records_checked"] == 2
    assert result["possible_stop_related_field_names"] == ["nested.stopLossPrice", "stopLoss"]
    assert not result["stop_loss_verified"]
    assert not result["live_trading_authorized"]
    assert result["conclusion"] == "UNVERIFIED"
    text = __import__("json").dumps(result)
    assert "sensitive-id" not in text and "secret-123" not in text
    assert "79000" not in text


def test_absent_stop_fields_does_not_mean_no_protection():
    result = audit.audit_rows([{"id": 2, "symbol": "SOLUSDT", "status": "OPENED"}])
    assert result["possible_stop_related_field_names"] == []
    assert result["conclusion"] == "UNVERIFIED"


def test_read_only_audit_calls_only_known_get_endpoint(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    def fake_request(method, path, *args, **kwargs):
        calls.append((method, path))
        return {"items": [{"id": 1, "symbol": "BTCUSDT", "side": "LONG",
                           "status": "OPENED", "isActive": True,
                           "size": "0.01", "entryPrice": "80000"}],
                "meta": {"total": 1}}
    monkeypatch.setattr(ex, "request", fake_request)
    result = audit.audit_exchange(ex, "off")
    assert calls == [("GET", "/futures/positions")]
    assert result["position_records_checked"] == 1
    with pytest.raises(X.ExchangeError, match="forbids"):
        ex.request("POST", "/futures/positions", body={})
    with pytest.raises(X.ExchangeError, match="permits"):
        ex.request("GET", "/futures/assets")


def test_read_only_audit_wont_run_if_mirror_is_enabled(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    monkeypatch.setattr(ex, "request", lambda *a, **k: calls.append(a))
    for mode in ("dry", "live"):
        with pytest.raises(X.ExchangeError, match="mode=off"):
            audit.audit_exchange(ex, mode)
    assert calls == []


def test_read_only_audit_bad_position_response_fails_closed(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    monkeypatch.setattr(ex, "request", lambda *a, **k: {"summary": {}})
    with pytest.raises(X.ExchangeError, match="no position list"):
        audit.audit_exchange(ex, "off")


def test_audit_rows_rejects_malformed_snapshot():
    with pytest.raises(X.ExchangeError):
        audit.audit_rows([None])
