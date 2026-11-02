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
        if any(not isinstance(row, dict) for row in response):
            raise ExchangeError("Position history record schema invalid")
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


def closure_reason_diagnostics(rows):
    """Aggregate PnL, leverage and stored TP/SL fields by closure category.

    Closed-position records do not prove stop-loss state at the moment of
    liquidation. Aggregate numerical sums are reported only if every record
    in that category provides a valid value; values are not netted together.
    """
    groups = {}
    for row in rows:
        status = row.get("status")
        if not (isinstance(status, str) and
                status.upper() in ("CLOSED", "LIQUIDATED", "SETTLED")):
            continue
        category = reason_category(row.get("closingReason"))
        groups.setdefault(category, []).append(row)

    def group_sum(records, field):
        numbers = [safe_decimal(row.get(field)) for row in records]
        return (str(sum(numbers, Decimal(0)))
                if all(n is not None for n in numbers) else None)

    result = {}
    for category, records in sorted(groups.items()):
        leverages = [safe_decimal(row.get("leverage")) for row in records]
        valid_leverages = [n for n in leverages if n is not None and n > 0]
        result[category] = {
            "closed_count": len(records),
            "reported_realized_pnl_sum": group_sum(records, "realizedPnL"),
            "reported_total_pnl_sum": group_sum(records, "totalPnL"),
            "reported_open_fees_sum": group_sum(records, "openFees"),
            "reported_close_fees_sum": group_sum(records, "closeFees"),
            "leverage_min_if_known": (str(min(valid_leverages)) if valid_leverages else None),
            "leverage_max_if_known": (str(max(valid_leverages)) if valid_leverages else None),
            "leverage_at_least_50x_count": sum(n >= 50 for n in valid_leverages),
            "leverage_at_least_100x_count": sum(n >= 100 for n in valid_leverages),
            "leverage_missing_or_invalid_count": len(records) - len(valid_leverages),
            "closed_records_with_saved_sl_price": sum(
                (n is not None and n > 0)
                for n in (safe_decimal(row.get("stopLoss")) for row in records)
            ),
            "closed_records_with_sl_order_reference": sum(
                nonempty(row.get("slOrderId")) for row in records
            ),
            "closed_records_with_saved_tp_price": sum(
                (n is not None and n > 0)
                for n in (safe_decimal(row.get("takeProfit")) for row in records)
            ),
            "closed_records_with_tp_order_reference": sum(
                nonempty(row.get("tpOrderId")) for row in records
            ),
            "protective_order_active_at_close_verified": False,
            "reported_pnl_includes_fees_verified": False,
        }
    return result


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
        "by_closing_reason": closure_reason_diagnostics(rows),
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


def closed_btc_short_summary(rows):
    """Only aggregates. A closed BTC SHORT is not necessarily the previous trade."""
    filtered = [
        row for row in rows
        if row.get("symbol") == "BTCUSDT"
        and row.get("side") == "SHORT"
        and str(row.get("status", "")).upper() in ("CLOSED", "LIQUIDATED", "SETTLED")
    ]
    reasons = {}
    for row in filtered:
        reason = reason_category(row.get("closingReason"))
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "closed_btc_short_records_on_page": len(filtered),
        "closed_btc_short_reason_categories": reasons,
        "identical_to_previous_position_proven": False,
    }


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
        response = exchange.request("GET", "/futures/positions", {"page": 1})
        rows, history_incomplete = page_rows(response)
        # A position can close while this audit runs. The second read is
        # essential before we claim that any stored protection remains current.
        active_after = exchange._raw_positions()
        initial_target = [
            row for row in active_before
            if row.get("symbol") == "BTCUSDT" and row.get("side") == "SHORT"
        ]
        final_target = [
            row for row in active_after
            if row.get("symbol") == "BTCUSDT" and row.get("side") == "SHORT"
        ]
        one_target_at_both_reads = (
            len(active_before) == 1 and len(active_after) == 1 and
            len(initial_target) == 1 and len(final_target) == 1 and
            nonempty(initial_target[0].get("id")) and
            str(initial_target[0].get("id")) == str(final_target[0].get("id"))
        )
        if not active_before and not active_after:
            status_code = "NO_ACTIVE_POSITIONS_IN_BOTH_READS"
        elif active_before != active_after:
            status_code = "ACTIVE_POSITIONS_CHANGED_DURING_AUDIT"
        elif not one_target_at_both_reads:
            status_code = "TARGET_NOT_UNIQUELY_ACTIVE"
        else:
            status_code = "TARGET_STILL_OPEN"

        target_id = initial_target[0].get("id") if one_target_at_both_reads else None
        matches = [row for row in rows if
                   target_id is not None and str(row.get("id")) == str(target_id)]
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
        config_matches = bool(
            status_code == "TARGET_STILL_OPEN" and status_active and checks and
            all(
                v["has_price"] and v["matches_requested_price"] and
                v["order_type_matches"] and v["trigger_strategy_matches"]
                for v in checks.values()
            )
        )
        order_refs_present = bool(
            checks and all(v["order_id_populated"] for v in checks.values())
        )
        return {
            "read_only": True,
            "status_code": status_code,
            "active_position_records_first_read": len(active_before),
            "active_position_records_second_read": len(active_after),
            "history_records_on_page": len(rows),
            "history_indicates_more_pages": history_incomplete,
            "current_position_found_in_history": in_history,
            "matched_history_record_is_open": status_active,
            "same_position_still_open_after_readback": one_target_at_both_reads,
            "expected_stop_loss": str(SL),
            "expected_take_profit": str(TP),
            "protective_fields": checks,
            "configuration_readback_matches_requested": config_matches,
            "tp_sl_order_references_both_present": order_refs_present,
            "closed_btc_short": closed_btc_short_summary(rows),
            "closed_positions": history_closure_summary(rows),
            "exchange_stop_execution_verified": False,
            "live_trading_authorized": False,
            "conclusion": (
                "CONFIG_MATCHED_NOT_EXECUTION_VERIFIED"
                if config_matches else "NO_ACTIVE_TARGET" if status_code ==
                "NO_ACTIVE_POSITIONS_IN_BOTH_READS" else "UNVERIFIED"
            ),
            "note": (
                "Read-only account snapshot: a closed position must not be "
                "treated as an API error or as verified stop execution. "
                "History may be partial and BTC SHORT closure identity "
                "is not established from symbol and side alone."
            ),
        }
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
            "error_category": (
                "MIRROR_NOT_OFF" if isinstance(exc, ExchangeError)
                and "Live Mirror OFF" in str(exc)
                else "AUTH_OR_HTTP" if isinstance(exc, ExchangeError)
                and ("HTTP 401" in str(exc) or "HTTP 403" in str(exc))
                else "NETWORK_OR_API" if isinstance(exc, ExchangeError)
                and "TheTrueTrade GET " in str(exc)
                else "SCHEMA_OR_PRECONDITION" if isinstance(exc, ExchangeError)
                else "UNEXPECTED"
            ),
            "live_trading_authorized": False,
            "message": "Read-only TP/SL verification failed; do not enable Live Mirror.",
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
