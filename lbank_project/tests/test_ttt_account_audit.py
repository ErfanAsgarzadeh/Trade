"""Schema-safe, read-only TheTrueTrade account audit tests."""
import json

import pytest

from exchanges import ExchangeError, TheTrueTrade
import ttt_account_audit as audit


def exchange():
    ex = TheTrueTrade("fake", "fake", base="https://apiv2.thetruetrade.io")
    calls = []
    def mock_request(method, path, query=None, **kwargs):
        calls.append((method, path, query, kwargs))
        if path == "/futures/positions" and query == {"active": "true"}:
            return {"items": [{
                "id": "confidential-position-id", "symbol": "BTCUSDT", "side": "SHORT",
                "status": "OPENED", "size": "0.004835844590211942",
                "entryPrice": "77855.4", "markPrice": "77949.4",
                "unrealizedPnL": "0.088012371541857343", "isActive": True,
            }], "meta": {"total": 1}}
        if path == "/futures/positions" and query == {"page": 1}:
            return {"items": [{
                "id": "confidential-position-id", "status": "OPENED", "symbol": "BTCUSDT"},
                {"id": "another-private-id", "status": "CLOSED", "symbol": "ETHUSDT"},
            ], "meta": {"total": 4, "hasNextPage": True}}
        if path == "/futures/trades":
            return {"items": [{
                "id": "private-trade-id", "positionId": "another-private-id",
                "realizedPnl": "-1.25", "symbol": "ETHUSDT",
            }], "meta": {"total": 1}}
        if path == "/futures/assets/pnl":
            return {"items": [{"id": "private-pnl-id", "profit": "-4.0"}],
                    "meta": {"total": 1}}
        if path == "/futures/assets":
            return {"summary": {"totalAssets": "2.394853634655784",
                                "availableBalance": "0.003180862484327237"}}
        raise AssertionError("unexpected request")
    ex.request = mock_request
    return ex, calls


def test_read_only_audit_redacts_ids_and_preserves_partial_history():
    ex, calls = exchange()
    result = audit.run(ex, "off")
    assert result["current_open_position_records"] == 1
    assert result["position_history"]["status_counts"] == {"OPENED": 1, "CLOSED": 1}
    assert result["position_history"]["snapshot"]["more_pages_indicated"] is True
    assert result["position_history"]["snapshot"]["complete_history_proven"] is False
    assert result["position_history"]["history_position_ids_not_in_current_active_snapshot"] == 1
    assert result["trade_history"]["records_on_page"] == 1
    assert result["futures_equity_usdt"] == pytest.approx(2.39485)
    assert result["available_margin_usdt"] == pytest.approx(0.00318086)
    assert result["btc_short_price_pnl_diagnostic"][0]["formula_verified_against_exchange_contract_specs"] is False
    assert len(calls) == 6
    assert all(m == "GET" and kw == {} for m, _, _, kw in calls)
    assert not result["stop_loss_verified_by_api"]
    assert not result["live_trading_authorized"]
    data = json.dumps(result)
    for secret in ("confidential-position-id", "another-private-id",
                   "private-trade-id", "private-pnl-id"):
        assert secret not in data


def test_guard_blocks_patch_and_restores_method():
    ex, calls = exchange()
    old = ex.request
    # The audit own wrapper strictly permits documented GET routes.
    assert audit.run(ex, "off")["read_only"] is True
    assert ex.request is old
    assert all(x[0] == "GET" for x in calls)


def test_off_mode_required_without_network_requests():
    ex, calls = exchange()
    with pytest.raises(ExchangeError, match="OFF"):
        audit.run(ex, "live")
    assert not calls


def test_only_official_base_allowed():
    ex, calls = exchange()
    ex.base = "https://example.com"
    with pytest.raises(ExchangeError, match="Non-official"):
        audit.run(ex, "off")
    assert not calls


def test_history_schema_recognizes_unfamiliar_shapes_without_leaking_values():
    value = {"secrets": "api-key-not-for-output",
             "summary": {"some": "private"},
             "meta": {"total": 100}}
    result = audit.collection_snapshot(value)
    assert result["schema"] == "no_recognized_collection"
    assert "api-key-not-for-output" not in json.dumps(result)
    assert result["complete_history_proven"] is False


def test_history_bad_records_fail_closed():
    with pytest.raises(ExchangeError):
        audit.collection_snapshot({"items": ["bad"]})


def test_unknown_status_values_are_redacted():
    data = {"items": [{"id": "private1", "status": "user-secret-token"}]}
    result = audit.summarize_positions_history(data, [])
    assert result["status_counts"] == {"OTHER_OR_UNKNOWN": 1}
    assert "user-secret-token" not in json.dumps(result)


def test_missing_pnl_fields_are_diagnostic_not_proof():
    result = audit.pnl_price_check([{"symbol": "BTCUSDT", "side": "SHORT"}])
    assert result[0]["calculation"] == "UNAVAILABLE_INVALID_FIELDS"
