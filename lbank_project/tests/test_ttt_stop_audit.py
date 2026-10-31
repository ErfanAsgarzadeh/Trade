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


def test_documented_orders_audit_uses_only_get_and_redacts_secrets(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    response = {
        "items": [
            {"id": "secret-order-1", "userId": "private-user", "symbol": "BTCUSDT",
             "orderType": "STOP_MARKET", "status": "OPEN", "stopPrice": "79123.45",
             "positionId": "private-position-id"},
            {"id": "secret-order-2", "type": "MARKET", "status": "FILLED",
             "apiKey": "private-key"},
        ],
        "meta": {"total": 2},
    }
    def fake_request(method, path, *args, **kwargs):
        calls.append((method, path, args, kwargs))
        return response
    monkeypatch.setattr(ex, "request", fake_request)
    result = audit.audit_orders(ex, "off")
    assert calls == [("GET", "/futures/orders", ({"active": "true", "page": 1},), {})]
    assert result["order_records_checked"] == 2
    assert result["order_type_counts"] == {"STOP_MARKET": 1, "MARKET": 1}
    assert result["order_status_counts"] == {"OPEN": 1, "FILLED": 1}
    assert result["possible_stop_related_field_names"] == ["stopPrice"]
    assert result["stop_loss_verified"] is False
    assert result["live_trading_authorized"] is False
    data = __import__("json").dumps(result)
    for secret in ("secret-order-1", "private-user", "79123.45", "private-position-id", "private-key"):
        assert secret not in data
    with pytest.raises(X.ExchangeError, match="forbids"):
        ex.request("PATCH", "/futures/positions/1/tpsl")
    with pytest.raises(X.ExchangeError, match="permits"):
        ex.request("GET", "/futures/assets")


def test_orders_audit_refuses_non_off_mode_without_requests(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    monkeypatch.setattr(ex, "request", lambda *a, **kw: calls.append(a))
    for mode in ("dry", "live"):
        with pytest.raises(X.ExchangeError, match="mode=off"):
            audit.audit_orders(ex, mode)
    assert calls == []


@pytest.mark.parametrize("payload", [None, {}, {"items": {}}, {"items": [None]}])
def test_orders_audit_rejects_missing_or_invalid_rows(payload):
    with pytest.raises(X.ExchangeError):
        audit.audit_order_rows(payload)


def test_orders_audit_reports_pagination_and_unknown_types_without_values():
    response = {
        "items": [{"id": "sensitive-order-id", "orderType": "account-secret-goes-here",
                   "status": "custom-private-value"}],
        "meta": {"total": 3, "hasNextPage": True},
    }
    result = audit.audit_order_rows(response)
    assert result["possibly_incomplete_page"] is True
    assert result["order_type_counts"] == {"OTHER_OR_UNKNOWN": 1}
    assert result["order_status_counts"] == {"OTHER_OR_UNKNOWN": 1}
    assert "sensitive-order-id" not in str(result)
    assert "account-secret-goes-here" not in str(result)
