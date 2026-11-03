"""No-network tests for a single manual real-account TP/SL update."""
import json
from pathlib import Path

import pytest

from exchanges import ExchangeError, TheTrueTrade
import ttt_one_time_tpsl as tpsl


def row(**changes):
    base = {
        "id": "p-private-opaque-123", "symbol": "BTCUSDT",
        "side": "SHORT", "status": "OPENED", "isActive": True,
        "entryPrice": "77855.399999999999999834",
        "size": "0.004835844590211942",
        "leverage": 150, "markPrice": "77949.4",
        "liquidationPrice": "78298.068284508520923672",
        "unrealizedPnL": "0.088012371541857343",
    }
    base.update(changes)
    return base


def exchange_with_mock(positions=None, response=None, patch_error=None):
    ex = TheTrueTrade("fake-key", "fake-secret", base=tpsl.BASE_URL)
    calls = []
    positions = positions if positions is not None else [row()]

    def fake_request(method, path, query=None, body=None, **kwargs):
        calls.append((method, path, query, body))
        if method == "GET" and path == "/futures/positions":
            return {"items": positions, "meta": {"total": len(positions)}}
        if method == "PATCH" and "/tpsl" in path:
            if patch_error:
                raise patch_error
            return response
        raise AssertionError("unexpected network operation")

    ex.request = fake_request
    return ex, calls


def test_preview_never_patches_or_creates_journal(tmp_path):
    ex, calls = exchange_with_mock()
    target = tmp_path / "journal.json"
    result = tpsl.run(ex, mode="off", intent_path=target)
    assert result["conclusion"] == "PREVIEW_ONLY"
    assert result["patch_sent"] is False
    assert result["stop_loss_verified"] is False
    assert result["take_profit"] == "76276"
    assert result["stop_loss"] == "78167"
    assert float(result["mark_to_stop_pct"]) > 0
    assert float(result["reported_minus_price_only_estimate"]) > 0.5
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert not target.exists()


def test_apply_sends_exactly_one_documented_patch_and_journals(tmp_path):
    ex, calls = exchange_with_mock(response={"positionId": "opaque"})
    target = tmp_path / "journal.json"
    result = tpsl.run(ex, apply=True, mode="off", intent_path=target)
    assert result["conclusion"] == "ACKNOWLEDGED_NOT_VERIFIED"
    assert result["stop_loss_verified"] is False
    assert result["patch_sent"] is True
    assert [c[0] for c in calls] == ["GET", "GET", "PATCH"]
    assert calls[-1][1] == "/futures/positions/p-private-opaque-123/tpsl"
    assert calls[-1][3] == {
        "takeProfit": "76276",
        "takeProfitOrderType": "TAKE_PROFIT_MARKET",
        "takeProfitStrategy": "MARK_PRICE",
        "stopLoss": "78167",
        "stopLossOrderType": "STOP_MARKET",
        "stopLossStrategy": "MARK_PRICE",
    }
    assert json.loads(target.read_text())["state"] == "ACKNOWLEDGED_NOT_VERIFIED"
    assert "p-private-opaque-123" not in target.read_text()
    assert "opaque" not in json.dumps(result)
    with pytest.raises(ExchangeError, match="Previous TP/SL intent"):
        tpsl.run(ex, apply=True, mode="off", intent_path=target)
    assert [c[0] for c in calls].count("PATCH") == 1


def test_timeout_is_uncertain_and_is_never_retried(tmp_path):
    ex, calls = exchange_with_mock(patch_error=TimeoutError())
    target = tmp_path / "journal.json"
    with pytest.raises(ExchangeError, match="outcome uncertain"):
        tpsl.run(ex, apply=True, mode="off", intent_path=target)
    assert [c[0] for c in calls] == ["GET", "GET", "PATCH"]
    assert json.loads(target.read_text())["state"] == "PENDING_OUTCOME"
    with pytest.raises(ExchangeError, match="Previous TP/SL intent"):
        tpsl.run(ex, apply=True, mode="off", intent_path=target)
    assert [c[0] for c in calls].count("PATCH") == 1


@pytest.mark.parametrize("changed", [
    {"symbol": "ETHUSDT"},
    {"side": "LONG"},
    {"status": "CLOSED"},
    {"isActive": False},
    {"entryPrice": "77854"},
    {"entryPrice": "77900"},
    {"size": "0.0001"},
    {"leverage": 5},
    {"markPrice": "78167.1"},
    {"markPrice": "76275"},
    {"liquidationPrice": "78000"},
    {"id": "../private/order"},
])
def test_mismatched_or_unsafe_position_never_patch(tmp_path, changed):
    ex, calls = exchange_with_mock([row(**changed)])
    with pytest.raises(ExchangeError):
        tpsl.run(ex, apply=True, mode="off", intent_path=tmp_path / "journal.json")
    assert [c[0] for c in calls] == ["GET"]
    assert not (tmp_path / "journal.json").exists()


def test_multiple_positions_fail_closed(tmp_path):
    ex, calls = exchange_with_mock([row(), row(id="another")])
    with pytest.raises(ExchangeError, match="exactly one"):
        tpsl.run(ex, apply=True, mode="off", intent_path=tmp_path / "journal.json")
    assert len(calls) == 1


def test_live_mode_blocks_before_any_call(tmp_path):
    ex, calls = exchange_with_mock()
    with pytest.raises(ExchangeError, match="OFF"):
        tpsl.run(ex, apply=True, mode="live", intent_path=tmp_path / "journal.json")
    assert not calls


def test_bad_base_url_blocks_before_any_call(tmp_path):
    ex, calls = exchange_with_mock()
    ex.base = "https://untrusted.example"
    with pytest.raises(ExchangeError, match="official"):
        tpsl.run(ex, apply=True, mode="off", intent_path=tmp_path / "journal.json")
    assert not calls


def test_guard_restored_after_validation_failure(tmp_path):
    ex, calls = exchange_with_mock([row(markPrice="78900")])
    original = ex.request
    with pytest.raises(ExchangeError):
        tpsl.run(ex, apply=True, mode="off", intent_path=tmp_path / "journal.json")
    assert ex.request is original
