"""Read-only preflight for TheTrueTrade Live Mirror.

This tool NEVER enables live trading and NEVER sends POST/PATCH/DELETE.
It reports whether current configuration and documented exchange market limits
are sufficient for a potential future paper-to-live pilot. It does not grant
permission to trade, nor prove exchange stop execution in extreme conditions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from exchanges import ExchangeError, TheTrueTrade
from live_mirror import folder

REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")
OFFICIAL_BASE = "https://apiv2.thetruetrade.io"
RISK_POLICY_KEYS = ("risk_per_trade_pct", "max_total_open_risk_pct",
                    "max_daily_loss_pct", "max_drawdown_pct", "max_margin_usage_pct")


def load_local_config(path: Path | None = None):
    """Never silently accept read_config() fallback as validated user settings."""
    path = folder() / "live_config.json" if path is None else path
    if not path.is_file():
        return {"mode": "off"}, "MISSING"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON dictionary")
        # read only recognized, nonsensitive fields. Never echo raw user config.
        return data, "READABLE"
    except (OSError, ValueError, UnicodeError, TypeError):
        return {"mode": "off"}, "INVALID"


def limited_positive(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def market_summary(markets, symbols=REQUIRED_SYMBOLS):
    """Use actual exchange-reported minimums; never equate steps with minimums."""
    result = {}
    for symbol in symbols:
        market = markets.get(symbol)
        if not isinstance(market, dict):
            result[symbol] = {
                "market_reported": False,
                "minimum_order_size_verified": False,
                "minimum_order_value_verified": False,
                "constraints_known": False,
            }
            continue
        mq = limited_positive(market.get("min_qty"))
        mn = limited_positive(market.get("min_notional"))
        step = limited_positive(market.get("step"))
        result[symbol] = {
            "market_reported": True,
            "quantity_step": step,
            "minimum_order_size": mq,
            "minimum_order_value": mn,
            "maximum_exchange_leverage": limited_positive(market.get("max_leverage")),
            "minimum_order_size_verified": mq is not None,
            "minimum_order_value_verified": mn is not None,
            "constraints_known": bool(mq is not None and mn is not None and step is not None),
        }
    return result


def run(ex, cfg, cfg_status):
    blockers = []
    if cfg_status != "READABLE":
        blockers.append("LOCAL_LIVE_CONFIG_NOT_VALIDATED")
    mode = cfg.get("mode")
    if mode != "off":
        # Do NOT use the live API for this audit when mode is enabled.
        return {
            "read_only": True, "mode": "NOT_OFF",
            "configuration_file_status": cfg_status,
            "blockers": ["LIVE_MIRROR_MUST_BE_OFF_FOR_AUDIT"],
            "live_trading_authorized": False,
            "conclusion": "NOT_READY",
        }
    if cfg.get("exchange", "thetruetrade") != "thetruetrade":
        blockers.append("EXCHANGE_CONFIG_NOT_THETRUETRADE")
    if ex.base != OFFICIAL_BASE:
        blockers.append("NON_OFFICIAL_API_BASE")
    if not isinstance(ex, TheTrueTrade):
        blockers.append("ADAPTER_NOT_THETRUETRADE")
    if blockers:
        # Avoid any network calls on invalid config or unexpected API target.
        return {
            "read_only": True, "mode": "OFF",
            "configuration_file_status": cfg_status,
            "blockers": blockers,
            "live_trading_authorized": False,
            "conclusion": "NOT_READY",
        }

    original = ex.request

    def only_get(method, path, query=None, body=None, auth=True):
        if not (
            method == "GET" and body is None and
            ((path == "/futures/markets" and query is None and auth is False)
             or (path == "/futures/assets" and query is None and auth is True)
             or (path == "/futures/positions" and query == {"active": "true"} and auth is True))
        ):
            raise ExchangeError("Live readiness audit forbids this API operation")
        return original(method, path, query=query, auth=auth)

    ex.request = only_get
    try:
        markets = ex.markets()
        contract_summary = market_summary(markets)
        positions = ex._raw_positions()
        equity = ex.equity()
        free = ex.available_balance()
        # Only release of a separate verified venue-specific new-entry readback
        # implementation could change these, not a configured TP/SL on an old
        # position. These are facts about the CURRENT adapter implementation.
        blockers.append("NEW_ENTRY_STOP_READBACK_NOT_IMPLEMENTED")
        blockers.append("STOP_MOVE_READBACK_NOT_IMPLEMENTED")
        blockers.append("RISK_BASED_POSITION_SIZING_NOT_IMPLEMENTED")
        blockers.append("THREE_BOT_SAME_SYMBOL_POSITION_OWNERSHIP_NOT_RESOLVED")
        missing_risk = [k for k in RISK_POLICY_KEYS if k not in cfg]
        if missing_risk:
            blockers.append("LIVE_RISK_POLICY_FIELDS_NOT_CONFIGURED")
        if cfg.get("adopt_existing") is True:
            blockers.append("ADOPT_EXISTING_POSITIONS_ENABLED")
        if any(not x["constraints_known"] for x in contract_summary.values()):
            blockers.append("EXCHANGE_ORDER_MINIMUMS_UNVERIFIED")
        if len(positions):
            blockers.append("EXISTING_REAL_POSITIONS_NEED_INDEPENDENT_REVIEW")
        return {
            "read_only": True,
            "mode": "OFF",
            "configuration_file_status": cfg_status,
            "configured_leverage": cfg.get("leverage", 5)
                if type(cfg.get("leverage", 5)) is int else "INVALID",
            "configured_max_positions": cfg.get("max_positions", 40)
                if type(cfg.get("max_positions", 40)) is int else "INVALID",
            "configured_max_position_usd": (
                limited_positive(cfg.get("max_position_usd", 5000))
            ),
            "live_risk_controls_present": [
                key for key in RISK_POLICY_KEYS if key in cfg
            ],
            "risk_settings_are_enforced_by_current_mirror": False,
            "exchange_equity_usdt": equity,
            "exchange_available_margin_usdt": free,
            "exchange_active_position_records": len(positions),
            "markets": contract_summary,
            "blockers": sorted(set(blockers)),
            "stop_execution_reliability_verified": False,
            "live_trading_authorized": False,
            "conclusion": "NOT_READY",
            "note": (
                "This diagnostic cannot authorize live trading. Never increase "
                "leverage or place minimum-size orders to bypass risk limits."
            ),
        }
    finally:
        ex.request = original


def main():
    try:
        cfg, cfg_status = load_local_config()
        result = run(TheTrueTrade(), cfg, cfg_status)
    except Exception as exc:
        result = {
            "read_only": True,
            "conclusion": "ERROR_NOT_READY",
            "error_category": "READ_ONLY_EXCHANGE_OR_CONFIG_ERROR",
            "error_type": type(exc).__name__,
            "live_trading_authorized": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["conclusion"] == "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
