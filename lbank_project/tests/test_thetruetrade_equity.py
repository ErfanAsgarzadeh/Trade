"""Regression tests for TheTrueTrade futures equity response shapes (no network)."""
import pytest

from exchanges import ExchangeError, TheTrueTrade


def adapter(monkeypatch, payload):
    exchange = TheTrueTrade("fake-key", "fake-secret", "https://example.invalid")
    def fake_request(method, path, **kwargs):
        assert (method, path) == ("GET", "/futures/assets")
        return payload
    monkeypatch.setattr(exchange, "request", fake_request)
    return exchange


def test_modern_futures_summary_equity_no_double_count_pnl(monkeypatch):
    payload = {
        "summary": {
            "totalAssets": "9.828017869708509526",
            "availableBalance": "1.645366040000000002",
            "positionMarginBalance": "8.182651829708509457",
            "totalUnrealizedPnl": "0.513053230987205807",
        },
        "assets": [{
            "symbol": "USDT",
            "totalAssets": "9.828017869708509526",
            "availableBalance": "1.645366040000000002",
        }],
    }
    exchange = adapter(monkeypatch, payload)
    monkeypatch.setattr(exchange, "_raw_positions",
                        lambda: pytest.fail("Modern equity must not fetch or double-count position PnL"))
    assert len(exchange._list(payload)) == 1
    assert exchange.equity() == pytest.approx(9.82801786970851)


def test_summary_is_preferred_over_assets_and_zero_is_valid(monkeypatch):
    exchange = adapter(monkeypatch, {
        "summary": {"totalAssets": "0.00"},
        "assets": [{"symbol": "USDT", "totalAssets": "20.00"}],
    })
    assert exchange.equity() == 0.0


def test_fallback_to_usdt_asset_when_summary_missing(monkeypatch):
    exchange = adapter(monkeypatch, {
        "summary": {},
        "assets": [
            {"symbol": "BTC", "totalAssets": "123.0"},
            {"symbol": "USDT", "totalAssets": "9.828017869708509526"},
        ],
    })
    assert exchange.equity() == pytest.approx(9.82801786970851)


@pytest.mark.parametrize("response", [
    None,
    {},
    {"summary": {}, "assets": []},
    {"assets": [{"symbol": "BTC", "totalAssets": "100"}]},
    {"assets": [{"symbol": "USDT", "totalAssets": None}]},
    {"summary": {"totalAssets": "NaN"}, "assets": [{"symbol": "USDT", "totalAssets": "9"}]},
    {"summary": {"totalAssets": "Infinity"}},
    {"summary": {"totalAssets": "-1"}},
    {"summary": {"totalAssets": False}},
    {"summary": {"totalAssets": "invalid"}},
])
def test_invalid_or_missing_equity_fails_closed(monkeypatch, response):
    with pytest.raises(ExchangeError):
        adapter(monkeypatch, response).equity()


def test_legacy_flat_assets_still_support_pnl(monkeypatch):
    exchange = adapter(monkeypatch, [{"asset": "USDT", "balance": "1000"}])
    monkeypatch.setattr(exchange, "_raw_positions", lambda: [{"unrealizedPnL": "5"}])
    assert exchange.equity() == 1005.0
