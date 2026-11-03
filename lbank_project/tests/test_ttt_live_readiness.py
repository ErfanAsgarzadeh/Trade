"""Network-free safety tests for TheTrueTrade live-readiness report."""
import json

from exchanges import ExchangeError, TheTrueTrade
import ttt_live_readiness as readiness


def build_exchange(minimums=True, active=None):
    ex = TheTrueTrade("dummy-key", "dummy-secret", base=readiness.OFFICIAL_BASE)
    calls = []
    if active is None:
        active = []
    markets = []
    for symbol in readiness.REQUIRED_SYMBOLS:
        m = {
            "symbol": symbol, "stepSize": "0.001",
            "tickSize": "0.01", "maxLeverage": 50,
        }
        if minimums:
            m.update(minOrderSize="0.01", minOrderValue="15")
        markets.append(m)

    def mock(method, path, query=None, body=None, auth=True):
        calls.append((method, path, query, body, auth))
        if path == "/futures/markets":
            return {"items": markets}
        if path == "/futures/positions":
            return {"items": active, "meta": {"total": len(active)}}
        if path == "/futures/assets":
            return {"summary": {"totalAssets": "1000", "availableBalance": "1000"}}
        raise AssertionError("unapproved route")

    ex.request = mock
    return ex, calls


def test_all_market_limits_missing_fails_closed_without_changing_account():
    ex, calls = build_exchange(minimums=False)
    prior = ex.request
    report = readiness.run(ex, {"mode": "off", "exchange": "thetruetrade"}, "READABLE")
    assert report["conclusion"] == "NOT_READY"
    assert report["exchange_active_position_records"] == 0
    assert report["exchange_equity_usdt"] == 1000
    assert report["configured_max_positions"] == 40
    assert report["markets"]["BTCUSDT"]["quantity_step"] == 0.001
    assert report["markets"]["BTCUSDT"]["minimum_order_value"] is None
    assert not report["markets"]["BTCUSDT"]["constraints_known"]
    assert "EXCHANGE_ORDER_MINIMUMS_UNVERIFIED" in report["blockers"]
    assert "NEW_ENTRY_STOP_READBACK_NOT_IMPLEMENTED" in report["blockers"]
    assert "RISK_BASED_POSITION_SIZING_NOT_IMPLEMENTED" in report["blockers"]
    assert report["risk_settings_are_enforced_by_current_mirror"] is False
    assert report["live_trading_authorized"] is False
    assert all(x[0] == "GET" and x[3] is None for x in calls)
    assert ex.request is prior


def test_even_with_minima_and_risk_fields_no_live_authorization():
    ex, calls = build_exchange()
    cfg = dict(mode="off", exchange="thetruetrade", leverage=5,
        adopt_existing=False, **{k: 1 for k in readiness.RISK_POLICY_KEYS})
    report = readiness.run(ex, cfg, "READABLE")
    assert "EXCHANGE_ORDER_MINIMUMS_UNVERIFIED" not in report["blockers"]
    assert "LIVE_RISK_POLICY_FIELDS_NOT_CONFIGURED" not in report["blockers"]
    assert report["risk_settings_are_enforced_by_current_mirror"] is False
    assert not report["live_trading_authorized"]
    assert report["conclusion"] == "NOT_READY"
    assert all(v["constraints_known"] for v in report["markets"].values())


def test_live_mode_blocked_before_any_network():
    ex, calls = build_exchange()
    report = readiness.run(ex, {"mode": "live"}, "READABLE")
    assert report["blockers"] == ["LIVE_MIRROR_MUST_BE_OFF_FOR_AUDIT"]
    assert report["conclusion"] == "NOT_READY"
    assert calls == []


def test_missing_local_config_blocks_without_api(monkeypatch, tmp_path):
    ex, calls = build_exchange()
    cfg, status = readiness.load_local_config(tmp_path / "missing.json")
    report = readiness.run(ex, cfg, status)
    assert "LOCAL_LIVE_CONFIG_NOT_VALIDATED" in report["blockers"]
    assert calls == []


def test_corrupt_config_is_not_silently_accepted(tmp_path):
    path = tmp_path / "live_config.json"
    path.write_text("{not-json")
    cfg, status = readiness.load_local_config(path)
    assert status == "INVALID"
    assert cfg["mode"] == "off"


def test_non_official_base_fails_before_request():
    ex, calls = build_exchange()
    ex.base = "https://other.invalid"
    report = readiness.run(ex, {"mode": "off"}, "READABLE")
    assert "NON_OFFICIAL_API_BASE" in report["blockers"]
    assert not calls


def test_existing_active_position_requires_independent_review_and_ids_not_exposed():
    ex, calls = build_exchange(active=[{
        "id": "confidential-position-id",
        "symbol": "BTCUSDT", "side": "LONG", "status": "OPENED",
        "size": "0.001", "entryPrice": "100000",
    }])
    report = readiness.run(ex, {"mode": "off"}, "READABLE")
    assert "EXISTING_REAL_POSITIONS_NEED_INDEPENDENT_REVIEW" in report["blockers"]
    assert report["exchange_active_position_records"] == 1
    assert "confidential-position-id" not in json.dumps(report)
    assert not report["live_trading_authorized"]


def test_guard_blocks_any_mutating_request_and_restores_original():
    ex, calls = build_exchange()
    prior = ex.request
    def attempt_write():
        ex.request("PATCH", "/futures/positions/secret/tpsl", body={"stopLoss": "1"})
    ex.markets = attempt_write
    try:
        readiness.run(ex, {"mode": "off"}, "READABLE")
    except ExchangeError as error:
        assert "forbids" in str(error)
    else:
        raise AssertionError("write guard did not fire")
    assert ex.request is prior
    assert calls == []


def test_market_summary_never_uses_step_as_minimum():
    m = {"BTCUSDT": {
        "step": 0.000001, "min_qty": None, "min_notional": None,
        "max_leverage": 150,
    }}
    result = readiness.market_summary(m, ("BTCUSDT",))
    assert result["BTCUSDT"]["quantity_step"] == 0.000001
    assert result["BTCUSDT"]["minimum_order_size"] is None
    assert result["BTCUSDT"]["minimum_order_value"] is None
    assert not result["BTCUSDT"]["constraints_known"]
