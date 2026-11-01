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


def test_diagnose_history_links_and_tpsl_flags_without_sensitive_values(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    original = []
    private_id = "sensitive-position-id"
    responses = {
        ("GET", "/futures/positions", (("active", "true"),)): {
            "items": [{"id": private_id, "symbol": "BTCUSDT", "side": "SHORT",
                       "status": "OPENED", "isActive": True, "size": "0.01",
                       "entryPrice": "80000"}], "meta": {"total": 1}},
        ("GET", "/futures/orders", (("page", 1),)): {
            "items": [
                {"id": "private-order-1", "positionId": private_id,
                 "type": "MARKET", "status": "FILLED", "hasTPSL": True,
                 "strategy": "LATEST_PRICE", "triggerPrice": None},
                {"id": "private-order-2", "positionId": private_id,
                 "type": "STOP_LOSS_MARKET", "status": "CANCELED",
                 "hasTPSL": False, "strategy": "MARK_PRICE",
                 "triggerPrice": "79000"},
                {"id": "private-order-3", "positionId": "another-private-id",
                 "type": "LIMIT", "status": "FILLED"},
            ],
            "meta": {"total": 3}},
        ("GET", "/futures/orders", (("active", "true"), ("page", 1))): {
            "items": [], "meta": {"total": 0}},
    }

    def fake(method, path, query=None, **kwargs):
        calls.append((method, path, query))
        assert not kwargs
        return responses[(method, path, tuple(sorted((query or {}).items())))]

    monkeypatch.setattr(ex, "request", fake)
    report = audit.diagnose_order_links(ex, "off")
    assert len(calls) == 3 and all(method == "GET" for method, _, _ in calls)
    assert report["current_position_count"] == 1
    assert report["current_position_ids_with_historical_orders"] == 1
    assert report["historical_order_records_linked_to_current_positions"] == 2
    assert report["current_position_ids_with_working_orders"] == 0
    assert report["historical_orders"] == 3 and report["working_orders"] == 0
    assert report["unknown_type_groups"] == {
        "stop_like": 1, "take_profit_like": 0, "other": 0}
    assert report["hasTPSL_flag_counts"] == {
        "true": 1, "false": 1, "missing": 1, "invalid": 0}
    assert report["orders_with_trigger_price_field_populated"] == 1
    assert not report["stop_loss_verified"] and not report["live_trading_authorized"]
    text = __import__("json").dumps(report)
    for secret in (private_id, "private-order-1", "private-order-2",
                   "another-private-id", "79000"):
        assert secret not in text
    assert ex.request is fake  # Guard does not linger past diagnostic.


def test_diagnose_refuses_when_not_off_and_does_not_call_api(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    calls = []
    monkeypatch.setattr(ex, "request", lambda *args, **kwargs: calls.append(args))
    for mode in ("dry", "live"):
        with pytest.raises(X.ExchangeError, match="mode=off"):
            audit.diagnose_order_links(ex, mode)
    assert not calls


def test_diagnose_fails_closed_if_orders_snapshot_malformed(monkeypatch):
    ex = X.TheTrueTrade("fake", "fake")
    def fake(method, path, query=None):
        if path == "/futures/positions":
            return {"items": [], "meta": {"total": 0}}
        return {"items": ["invalid"], "meta": {"total": 1}}
    monkeypatch.setattr(ex, "request", fake)
    with pytest.raises(X.ExchangeError, match="expected order list"):
        audit.diagnose_order_links(ex, "off")
    assert ex.request is fake
