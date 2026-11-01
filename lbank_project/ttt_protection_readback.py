"""READ-ONLY verification of TP/SL configuration on an existing futures position.

Read the full-position view, which may expose stopLoss/takeProfit when
GET /futures/positions?active=true omits them. Never send POST/PATCH/DELETE,
never log raw position/order IDs or user data, and never enable Live Mirror.

Matching configured prices and order IDs is NOT proof that the exchange will
trigger a protective order; that needs an independently validated lifecycle.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
import sys

from exchanges import ExchangeError, TheTrueTrade
from live_mirror import read_config

TP = Decimal("76276")
SL = Decimal("78167")
BASE_URL = "https://apiv2.thetruetrade.io"


def safe_decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def nonempty(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, str))
            and bool(str(value).strip()))


def page_rows(response):
    if isinstance(response, list):
        return response, False
    if not isinstance(response, dict):
        raise ExchangeError("Position history schema invalid")
    rows = next((response[key] for key in ("items", "positions", "data", "results")
                 if isinstance(response.get(key), list)), None)
    if rows is None:
        raise ExchangeError("Position history list missing")
    meta = response.get("meta") or {}
    if not isinstance(meta, dict):
        raise ExchangeError("Position history pagination metadata invalid")
    incomplete = meta.get("hasNext") is True or meta.get("hasNextPage") is True or bool(meta.get("nextCursor"))
    for key in ("total", "totalCount", "totalItems"):
        if meta.get(key) is not None:
            total = safe_decimal(meta[key])
            if total is None or total != total.to_integral_value() or total < len(rows):
                raise ExchangeError("Position history total metadata invalid")
            incomplete = incomplete or total > len(rows)
    if any(not isinstance(row, dict) for row in rows):
        raise ExchangeError("Position history record schema invalid")
    return rows, bool(incomplete)


def reason_category(value):
    if not isinstance(value, str):
        return "MISSING"
    v = value.strip().upper()
    if "LIQUID" in v:
        return "LIQUIDATION"
    if "STOP" in v or v in ("SL", "SL_TRIGGERED"):
        return "STOP_LOSS"
    if "PROFIT" in v or v in ("TP", "TP_TRIGGERED"):
        return "TAKE_PROFIT"
    if any(k in v for k in ("MANUAL", "USER", "MARKET_CLOSE")):
        return "USER_OR_MARKET_CLOSE"
    return "OTHER_OR_UNKNOWN"


def history_closure_summary(rows):
    closed = [row for row in rows if
              isinstance(row.get("status"), str) and
              row["status"].upper() in ("CLOSED", "LIQUIDATED", "SETTLED")]
    reasons = {}
    for row in closed:
        name = reason_category(row.get("closingReason"))
        reasons[name] = reasons.get(name, 0) + 1

    def total(key):
        values = [safe_decimal(row.get(key)) for row in closed]
        if not closed or any(value is None for value in values):
            return None
        return str(sum(values, Decimal(0)))

    return {
        "closed_records_on_page": len(closed),
        "closing_reason_categories": reasons,
        "closed_realized_pnl_sum_if_complete": total("realizedPnL"),
        "closed_open_fees_sum_if_complete": total("openFees"),
        "closed_close_fees_sum_if_complete": total("closeFees"),
        "fee_and_pnl_accounting_basis_verified": False,
        "note": "Page-one totals, if available, are NOT complete account PnL.",
    }


def check_fields(record):
    # Do not return actual values when they differ from requested values.
    required_checks = {
        "stop_loss": (
            "stopLoss", SL, "stopLossOrderType", "STOP_MARKET",
            "stopLossStrategy", "MARK_PRICE", "slOrderId"),
        "take_profit": (
            "takeProfit", TP, "takeProfitOrderType", "TAKE_PROFIT_MARKET",
            "takeProfitStrategy", "MARK_PRICE", "tpOrderId"),
    }
    checks = {}
    for name, (price_key, target, type_key, expected_type,
               strategy_key, expected_strategy, order_id_key) in required_checks.items():
        price = safe_decimal(record.get(price_key))
        checks[name] = {
            "field_present": price_key in record,
            "has_price": price is not None and price > 0,
            "matches_requested_price": price == target if price is not None else False,
            "order_type_matches": record.get(type_key) == expected_type,
            "trigger_strategy_matches": record.get(strategy_key) == expected_strategy,
            "order_id_field_present": order_id_key in record,
            "order_id_populated": nonempty(record.get(order_id_key)),
        }
    return checks


def run(exchange, mode):
    if mode != "off":
        raise ExchangeError("Read-only TP/SL verification requires Live Mirror OFF")
    if exchange.base != BASE_URL:
        raise ExchangeError("Non-official futures base URL")
    original = exchange.request

    def only_get(method, path, query=None, body=None, auth=True):
        if (method != "GET" or body is not None or auth is not True or
                path != "/futures/positions" or
                query not in ({"active": "true"}, {"page": 1})):
            raise ExchangeError("TP/SL diagnostic blocked a non-read-only operation")
        return original(method, path, query=query)

    exchange.request = only_get
    try:
        active_before = exchange._raw_positions()
        if len(active_before) != 1:
            raise ExchangeError("Expected exactly one currently open futures position")
        target = active_before[0]
        if target.get("symbol") != "BTCUSDT" or target.get("side") != "SHORT":
            raise ExchangeError("Target position is not BTCUSDT SHORT")
        target_id = target.get("id")
        if not nonempty(target_id):
            raise ExchangeError("Active position ID is invalid")

        response = exchange.request("GET", "/futures/positions", {"page": 1})
        rows, history_incomplete = page_rows(response)
        matches = [row for row in rows if str(row.get("id")) == str(target_id)]
        if len(matches) > 1:
            raise ExchangeError("Duplicate matching position records in history")
        record = matches[0] if matches else None
        in_history = record is not None
        status_active = bool(
            record is not None and
            str(record.get("status", "")).upper() in ("OPEN", "OPENED") and
            record.get("isActive") is not False and
            record.get("symbol") == "BTCUSDT" and
            record.get("side") == "SHORT"
        )
        checks = check_fields(record) if status_active else None

        # Guard against the position closing or being replaced mid-audit.
        active_after = exchange._raw_positions()
        same_position_still_open = (
            len(active_after) == 1 and
            str(active_after[0].get("id")) == str(target_id) and
            active_after[0].get("symbol") == "BTCUSDT" and
            active_after[0].get("side") == "SHORT"
        )
        config_matches = bool(
            status_active and same_position_still_open and checks and
            all(
                v["has_price"] and v["matches_requested_price"] and
                v["order_type_matches"] and v["trigger_strategy_matches"]
                for v in checks.values()
            )
        )
        order_refs_present = bool(
            checks and all(v["order_id_populated"] for v in checks.values())
        )

        summary = {
            "read_only": True,
            "history_records_on_page": len(rows),
            "history_indicates_more_pages": history_incomplete,
            "current_position_found_in_history": in_history,
            "matched_history_record_is_open": status_active,
            "same_position_still_open_after_readback": same_position_still_open,
            "expected_stop_loss": str(SL),
            "expected_take_profit": str(TP),
            "protective_fields": checks,
            "configuration_readback_matches_requested": config_matches,
            "tp_sl_order_references_both_present": order_refs_present,
            "closed_positions": history_closure_summary(rows),
            "exchange_stop_execution_verified": False,
            "live_trading_authorized": False,
            "conclusion": (
                "CONFIG_MATCHED_NOT_EXECUTION_VERIFIED"
                if config_matches else "UNVERIFIED"
            ),
            "note": (
                "Full-position history exposes possible TP/SL fields, but neither "
                "their equality nor an order ID alone proves active trigger execution."
            ),
        }
        return summary
    finally:
        exchange.request = original


def main():
    try:
        result = run(TheTrueTrade(), read_config()["mode"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "read_only": True,
            "conclusion": "ERROR",
            "error_type": type(exc).__name__,
            "live_trading_authorized": False,
            "message": "Read-only TP/SL verification failed; do not enable Live Mirror.",
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
