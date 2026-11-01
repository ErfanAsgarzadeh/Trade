"""Safety, completeness and privacy tests for futures TP/SL readback."""
import json

import pytest
from exchanges import ExchangeError, TheTrueTrade
import ttt_protection_readback as p


def target(**kw):
    record = {
        "id": "private-btc-id", "symbol": "BTCUSDT", "side": "SHORT",
        "isActive": True, "status": "OPENED",
        "entryPrice": "77855.4", "markPrice": "77949.4", "size": "0.00483584459",
        "stopLoss": "78167.000", "takeProfit": "76276",
        "slOrderId": "private-stop-order-1", "tpOrderId": "private-take-order-2",
        "stopLossOrderType": "STOP_MARKET",
        "takeProfitOrderType": "TAKE_PROFIT_MARKET",
        "stopLossStrategy": "MARK_PRICE",
        "takeProfitStrategy": "MARK_PRICE",
    }
    record.update(kw)
    return record


def make_exchange(history=None, before=None, after=None):
    ex = TheTrueTrade("fake", "fake", base=p.BASE_URL)
    calls = []
    before = [target()] if before is None else before
    after = before if after is None else after
    history = ([target(), {
        "id": "private-closed-1", "status": "CLOSED",
        "closingReason": "LIQUIDATED", "realizedPnL": "-1.2",
        "openFees": "0.1", "closeFees": "0.12",
    }] if history is None else history)

    def mock(method, path, query=None, body=None, auth=True):
        calls.append((method, path, query, body, auth))
        assert method == "GET" and path == "/futures/positions" and body is None
        if query == {"active": "true"}:
            n = sum(1 for c in calls if c[2] == {"active": "true"})
            rows = before if n == 1 else after
            return {"items": rows, "meta": {"total": len(rows)}}
        if query == {"page": 1}:
            return {"items": history, "meta": {"total": len(history)}}
        raise AssertionError("Unexpected request")

    ex.request = mock
    return ex, calls


def test_matching_tpsl_config_and_order_ids_still_never_unlock_live():
    ex, calls = make_exchange()
    result = p.run(ex, "off")
    assert [c[0] for c in calls] == ["GET", "GET", "GET"]
    assert result["configuration_readback_matches_requested"] is True
    assert result["tp_sl_order_references_both_present"] is True
    assert result["protective_fields"]["stop_loss"]["matches_requested_price"] is True
    assert result["protective_fields"]["take_profit"]["matches_requested_price"] is True
    assert result["closed_positions"]["closing_reason_categories"] == {"LIQUIDATION": 1}
    assert result["closed_positions"]["closed_realized_pnl_sum_if_complete"] == "-1.2"
    assert result["conclusion"] == "CONFIG_MATCHED_NOT_EXECUTION_VERIFIED"
    assert result["exchange_stop_execution_verified"] is False
    assert result["live_trading_authorized"] is False
    text = json.dumps(result)
    assert "private-btc-id" not in text
    assert "private-stop-order-1" not in text
    assert "private-closed-1" not in text


def test_missing_stop_order_id_is_not_proof_of_active_order():
    ex, _ = make_exchange(history=[target(slOrderId=None)])
    result = p.run(ex, "off")
    assert result["configuration_readback_matches_requested"] is True
    assert not result["tp_sl_order_references_both_present"]
    assert result["exchange_stop_execution_verified"] is False


@pytest.mark.parametrize("updates", [
    {"stopLoss": None},
    {"stopLoss": "78168"},
    {"takeProfit": "76276.01"},
    {"stopLossOrderType": "STOP_LIMIT"},
    {"takeProfitStrategy": "LATEST_PRICE"},
    {"status": "CLOSED"},
    {"side": "LONG"},
    {"isActive": False},
])
def test_wrong_price_strategy_type_or_state_never_matches(updates):
    ex, _ = make_exchange(history=[target(**updates)])
    out = p.run(ex, "off")
    assert out["configuration_readback_matches_requested"] is False
    assert out["live_trading_authorized"] is False


def test_target_not_in_first_page_stays_unverified():
    ex, _ = make_exchange(history=[{"id": "private-other", "status": "CLOSED"}])
    out = p.run(ex, "off")
    assert not out["current_position_found_in_history"]
    assert out["conclusion"] == "UNVERIFIED"


def test_target_closed_during_readback_is_unverified():
    ex, _ = make_exchange(after=[])
    out = p.run(ex, "off")
    assert not out["same_position_still_open_after_readback"]
    assert not out["configuration_readback_matches_requested"]


def test_history_duplicate_target_fails_closed():
    ex, _ = make_exchange(history=[target(), target()])
    with pytest.raises(ExchangeError, match="Duplicate"):
        p.run(ex, "off")


def test_live_mode_no_network():
    ex, calls = make_exchange()
    with pytest.raises(ExchangeError, match="OFF"):
        p.run(ex, "live")
    assert not calls


def test_bad_base_no_network():
    ex, calls = make_exchange()
    ex.base = "https://untrusted.test"
    with pytest.raises(ExchangeError, match="Non-official"):
        p.run(ex, "off")
    assert not calls


def test_history_more_pages_detected_and_untrusted_reason_redacted():
    r, more = p.page_rows({"items": [{"id": "private-1"}],
                           "meta": {"total": 5, "hasNext": True}})
    assert more is True and len(r) == 1
    summary = p.history_closure_summary([{
        "id": "private-id",
        "status": "CLOSED",
        "closingReason": "custom-secret",
        "realizedPnL": "-10",
        "openFees": "1",
        "closeFees": "2",
    }])
    assert summary["closing_reason_categories"] == {"OTHER_OR_UNKNOWN": 1}
    assert "custom-secret" not in json.dumps(summary)


def test_unsupported_history_schema_rejected():
    with pytest.raises(ExchangeError):
        p.page_rows({"summary": {}})
    with pytest.raises(ExchangeError):
        p.page_rows({"items": [{"id": 1}], "meta": {"total": 0}})
