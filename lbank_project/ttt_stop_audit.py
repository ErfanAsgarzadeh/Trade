"""Read-only TheTrueTrade stop-loss schema audit.

This tool NEVER sends POST/PATCH/DELETE and NEVER changes a position. It inspects
the *field names* returned by the already-validated active positions endpoint.
Neither a successful GET nor a stop-looking field is proof of an active stop.
The live execution gate remains locked until the exchange's stop readback API is
documented and independently validated.
"""
from __future__ import annotations

import json
import re
import sys

from exchanges import ExchangeError, TheTrueTrade
from live_mirror import read_config

STOP_NAMES = {
    "stoploss", "stoplossprice", "stoplosstriggerprice", "stopprice",
    "sl", "slprice", "sltriggerprice", "stoplossorder", "stoplossorderid",
    "tpsl", "riskorder", "stoplosssettings",
}


def candidate_paths(record: dict, prefix: str = "", depth: int = 0) -> set[str]:
    """Return only names of possible protection fields, never their values."""
    if depth > 3 or not isinstance(record, dict):
        return set()
    paths: set[str] = set()
    for field, value in record.items():
        if not isinstance(field, str):
            continue
        # Keep the output as non-sensitive, bounded field names.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", field):
            continue
        path = f"{prefix}.{field}" if prefix else field
        normalized = re.sub(r"[^a-z0-9]", "", field.lower())
        if normalized in STOP_NAMES:
            paths.add(path)
        if isinstance(value, dict):
            paths.update(candidate_paths(value, path, depth + 1))
        elif isinstance(value, list) and depth < 2:
            for child in value[:3]:
                if isinstance(child, dict):
                    paths.update(candidate_paths(child, path, depth + 1))
    return paths


def audit_rows(rows: list) -> dict:
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ExchangeError("Invalid read-only positions snapshot")
    fields = sorted({
        name for r in rows for name in r
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
    })
    candidates = sorted(set().union(*(candidate_paths(r) for r in rows)))
    return {
        "position_records_checked": len(rows),
        "returned_position_fields": fields,
        "possible_stop_related_field_names": candidates,
        "stop_loss_verified": False,
        "live_trading_authorized": False,
        "conclusion": "UNVERIFIED",
        "note": (
            "No proven exchange stop readback yet. Missing stop fields do not "
            "prove absence of stops; candidate fields do not prove protection."
        ),
    }


def audit_exchange(exchange: TheTrueTrade, mode: str) -> dict:
    # This is diagnostic-only; fail before any network call if mode is not OFF.
    if mode != "off":
        raise ExchangeError("Read-only stop audit requires Live Mirror mode=off")
    # Explicit guard, including against accidental future code changes.
    request = exchange.request
    def only_get(method, path, *args, **kwargs):
        if str(method).upper() != "GET":
            raise ExchangeError("Stop audit forbids non-GET requests")
        if path != "/futures/positions":
            raise ExchangeError("Stop audit permits only GET /futures/positions")
        return request(method, path, *args, **kwargs)
    exchange.request = only_get
    return audit_rows(exchange._raw_positions())


# Only allow public, non-identifying enum labels into diagnostic output.
ORDER_TYPES = {
    "STOP_MARKET", "STOP_LIMIT", "TAKE_PROFIT_MARKET", "TAKE_PROFIT_LIMIT",
    "MARKET", "LIMIT", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET",
}
STATUS_TYPES = {
    "OPEN", "OPENED", "ACTIVE", "NEW", "PENDING", "TRIGGERED", "FILLED",
    "PARTIALLY_FILLED", "CLOSED", "CANCELED", "CANCELLED", "EXPIRED",
}


def audit_order_rows(response) -> dict:
    """Summarize order schema without returning any order IDs, prices or account data."""
    if isinstance(response, list):
        rows, meta = response, {}
    elif isinstance(response, dict):
        rows = next((response[k] for k in ("items", "orders", "data", "results")
                     if isinstance(response.get(k), list)), None)
        meta = response.get("meta") or {}
    else:
        rows, meta = None, {}
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ExchangeError("Invalid futures/orders response: expected order list")
    if not isinstance(meta, dict):
        raise ExchangeError("Invalid futures/orders pagination metadata")
    fields = sorted({
        name for row in rows for name in row
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
    })
    candidate_fields = sorted(set().union(*(candidate_paths(row) for row in rows)))
    counts = {}
    status_counts = {}
    for row in rows:
        # Strict whitelist prevents accidental leaking of IDs and arbitrary values.
        label = next((row[k] for k in ("orderType", "type", "tradeType")
                      if isinstance(row.get(k), str)), "")
        label = label.strip().upper()
        label = label if label in ORDER_TYPES else "OTHER_OR_UNKNOWN"
        counts[label] = counts.get(label, 0) + 1
        status = next((row[k] for k in ("status", "orderStatus")
                       if isinstance(row.get(k), str)), "")
        status = status.strip().upper()
        status = status if status in STATUS_TYPES else "OTHER_OR_UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1
    incomplete = meta.get("hasNextPage") is True or meta.get("hasNext") is True or bool(meta.get("nextCursor"))
    for field in ("total", "totalCount", "totalItems"):
        if meta.get(field) is not None:
            try:
                total = int(meta[field])
                incomplete = incomplete or total > len(rows)
            except (ValueError, TypeError, OverflowError):
                incomplete = True
    return {
        "order_records_checked": len(rows),
        "returned_order_fields": fields,
        "possible_stop_related_field_names": candidate_fields,
        "order_type_counts": counts,
        "order_status_counts": status_counts,
        "possibly_incomplete_page": bool(incomplete),
        "stop_loss_verified": False,
        "live_trading_authorized": False,
        "conclusion": "UNVERIFIED",
        "note": (
            "Open orders may include stops, but field names and enum counts alone "
            "do not prove that a working stop is bound to a particular position."
        ),
    }


def audit_orders(exchange: TheTrueTrade, mode: str) -> dict:
    """Use only the officially documented GET /futures/orders endpoint."""
    if mode != "off":
        raise ExchangeError("Read-only order audit requires Live Mirror mode=off")
    original_request = exchange.request
    def only_orders_get(method, path, *args, **kwargs):
        if str(method).upper() != "GET":
            raise ExchangeError("Order audit forbids non-GET requests")
        if path != "/futures/orders":
            raise ExchangeError("Order audit permits only GET /futures/orders")
        return original_request(method, path, *args, **kwargs)
    exchange.request = only_orders_get
    # The documented filters select working orders; limit the audit to page one.
    # If metadata signals more pages, report incompleteness rather than assuming
    # there are no other protective orders.
    return audit_order_rows(exchange.request(
        "GET", "/futures/orders", {"active": "true", "page": 1}))



def diagnose_order_links(exchange: TheTrueTrade, mode: str) -> dict:
    """Compare active positions with historical/working orders; expose aggregates only.

    A filled entry with hasTPSL=true is NOT evidence its protective stop
    remains active. This function never verifies protection or authorizes live.
    """
    if mode != "off":
        raise ExchangeError("Read-only diagnostic requires Live Mirror mode=off")
    original = exchange.request

    def only_safe_get(method, path, query=None, **kwargs):
        if method != "GET":
            raise ExchangeError("Order diagnostic forbids non-GET requests")
        allowed = (
            (path == "/futures/positions" and query == {"active": "true"}) or
            (path == "/futures/orders" and query in (
                {"page": 1}, {"active": "true", "page": 1}))
        )
        if not allowed or kwargs:
            raise ExchangeError("Order diagnostic blocked an unapproved request")
        return original(method, path, query)

    exchange.request = only_safe_get
    try:
        positions = exchange.positions()
        history_response = exchange.request("GET", "/futures/orders", {"page": 1})
        active_response = exchange.request(
            "GET", "/futures/orders", {"active": "true", "page": 1})
        history = audit_order_rows(history_response)
        active = audit_order_rows(active_response)

        def rows(response):
            if isinstance(response, list):
                return response
            for key in ("items", "orders", "data", "results"):
                if isinstance(response.get(key), list):
                    return response[key]
            raise ExchangeError("Invalid order records")

        history_rows = rows(history_response)
        active_rows = rows(active_response)
        ids = {str(i) for pos in positions.values() for i in pos.ids}
        linked_ids = set()
        linked_active_ids = set()
        flags = {"true": 0, "false": 0, "missing": 0, "invalid": 0}
        unknown_groups = {"stop_like": 0, "take_profit_like": 0, "other": 0}
        strategy_counts = {"LATEST_PRICE": 0, "MARK_PRICE": 0,
                           "OTHER_OR_UNKNOWN": 0, "MISSING": 0}
        with_trigger = 0

        def linked_ids_in(records):
            return {
                str(row["positionId"])
                for row in records
                if row.get("positionId") is not None
                and str(row["positionId"]) in ids
            }

        linked_ids = linked_ids_in(history_rows)
        linked_active_ids = linked_ids_in(active_rows)
        linked_orders = 0
        for row in history_rows:
            if (row.get("positionId") is not None and
                    str(row.get("positionId")) in ids):
                linked_orders += 1
            flag = row.get("hasTPSL")
            if flag is True:
                flags["true"] += 1
            elif flag is False:
                flags["false"] += 1
            elif flag is None:
                flags["missing"] += 1
            else:
                flags["invalid"] += 1
            if row.get("triggerPrice") not in (None, ""):
                with_trigger += 1
            strategy = row.get("strategy")
            if isinstance(strategy, str) and strategy.upper() in ("LATEST_PRICE", "MARK_PRICE"):
                strategy_counts[strategy.upper()] += 1
            elif strategy is None:
                strategy_counts["MISSING"] += 1
            else:
                strategy_counts["OTHER_OR_UNKNOWN"] += 1
            kind = next((row[k] for k in ("orderType", "type", "tradeType")
                         if isinstance(row.get(k), str)), "")
            kind = kind.strip().upper()
            if kind not in ORDER_TYPES:
                if "STOP" in kind or kind in ("SL", "SL_MARKET"):
                    unknown_groups["stop_like"] += 1
                elif "PROFIT" in kind or kind in ("TP", "TP_MARKET"):
                    unknown_groups["take_profit_like"] += 1
                else:
                    unknown_groups["other"] += 1

        return {
            "current_position_count": len(positions),
            "current_position_ids_with_historical_orders": len(linked_ids),
            "historical_order_records_linked_to_current_positions": linked_orders,
            "current_position_ids_with_working_orders": len(linked_active_ids),
            "historical_orders": len(history_rows),
            "working_orders": len(active_rows),
            "historical_order_type_counts": history["order_type_counts"],
            "historical_order_status_counts": history["order_status_counts"],
            "unknown_type_groups": unknown_groups,
            "hasTPSL_flag_counts": flags,
            "orders_with_trigger_price_field_populated": with_trigger,
            "strategy_counts": strategy_counts,
            "possibly_incomplete_history": history["possibly_incomplete_page"],
            "possibly_incomplete_working_orders": active["possibly_incomplete_page"],
            "stop_loss_verified": False,
            "live_trading_authorized": False,
            "conclusion": "UNVERIFIED",
            "note": (
                "Historical order flags and trigger prices do not prove active "
                "protective stops; verify exchange stop readback independently."
            ),
        }
    finally:
        exchange.request = original


def main() -> int:
    try:
        if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] not in ("--orders", "--diagnose")):
            raise ExchangeError("Unsupported audit option")
        mode = read_config()["mode"]
        exchange = TheTrueTrade()
        result = (diagnose_order_links(exchange, mode) if "--diagnose" in sys.argv[1:]
                  else audit_orders(exchange, mode) if "--orders" in sys.argv[1:]
                  else audit_exchange(exchange, mode))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        # No raw response bodies, API secrets, or position identifiers in logs.
        print(json.dumps({
            "conclusion": "ERROR",
            "live_trading_authorized": False,
            "error_type": type(exc).__name__,
            "message": "Read-only stop audit failed; live gate remains locked.",
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
