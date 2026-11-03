"""Strictly read-only TheTrueTrade account and PnL diagnostic.

Only officially documented GET futures paths are permitted. The report omits
identifiers, account-owner fields, transaction details and raw API responses.
This diagnostic NEVER verifies protection or authorizes automated live trading.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
import sys

from exchanges import ExchangeError, TheTrueTrade
from live_mirror import read_config

ALLOWED_REQUESTS = {
    ("/futures/positions", (("active", "true"),)),
    ("/futures/positions", (("page", 1),)),
    ("/futures/trades", (("page", 1),)),
    ("/futures/assets/pnl", ()),
    ("/futures/assets", ()),
}
COLLECTION_KEYS = ("items", "positions", "trades", "results", "data", "history", "records")
VALID_STATUSES = {
    "OPEN", "OPENED", "CLOSED", "CANCELED", "CANCELLED", "LIQUIDATED",
    "SETTLED", "FILLED", "PARTIALLY_FILLED", "PENDING", "NEW", "ACTIVE",
}


def safe_fields(record):
    if not isinstance(record, dict):
        return []
    return sorted(
        key for key in record
        if isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key)
    )


def collection_snapshot(payload):
    """Schema-only inspection of one page; do not assume pagination is complete."""
    if isinstance(payload, list):
        records, top_fields, meta = payload, [], None
    elif isinstance(payload, dict):
        top_fields = safe_fields(payload)
        records = next(
            (payload[key] for key in COLLECTION_KEYS if isinstance(payload.get(key), list)),
            None,
        )
        meta = payload.get("meta")
    else:
        records, top_fields, meta = None, [], None

    if records is None:
        return {
            "schema": "no_recognized_collection",
            "top_level_fields": top_fields,
            "records_on_page": None,
            "record_fields": [],
            "complete_history_proven": False,
        }
    if any(not isinstance(record, dict) for record in records):
        raise ExchangeError("Invalid records in read-only account history")
    incomplete = None
    if meta is not None:
        if not isinstance(meta, dict):
            raise ExchangeError("Invalid account history pagination metadata")
        incomplete = bool(meta.get("hasNext") is True or meta.get("hasNextPage") is True
                          or meta.get("nextCursor"))
        for key in ("total", "totalCount", "totalItems"):
            if meta.get(key) is not None:
                try:
                    total = int(meta[key])
                except (TypeError, ValueError, OverflowError):
                    incomplete = True
                else:
                    incomplete = incomplete or total > len(records)
    return {
        "schema": "records",
        "top_level_fields": top_fields,
        "records_on_page": len(records),
        "record_fields": sorted(set(
            field for record in records for field in safe_fields(record)
        )),
        "more_pages_indicated": incomplete,
        # With one page and sparse metadata, NEVER claim an exhaustive history.
        "complete_history_proven": False,
    }


def decimal_field(record, key):
    value = record.get(key)
    if isinstance(value, bool) or value is None:
        raise ValueError("missing numeric field")
    try:
        parsed = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError("invalid numeric field") from None
    if not parsed.is_finite():
        raise ValueError("non-finite numeric field")
    return parsed


def pnl_price_check(rows):
    """Compare same-record price arithmetic, not accounting-equity reconciliation."""
    out = []
    for row in rows:
        if row.get("symbol") != "BTCUSDT" or row.get("side") != "SHORT":
            continue
        try:
            entry = decimal_field(row, "entryPrice")
            mark = decimal_field(row, "markPrice")
            size = decimal_field(row, "size")
            pnl = decimal_field(row, "unrealizedPnL")
            if not (entry > 0 and mark > 0 and size > 0):
                raise ValueError("non-positive price/size")
            estimate = (entry - mark) * size
            out.append({
                "symbol": "BTCUSDT",
                "side": "SHORT",
                "entry": str(entry),
                "mark": str(mark),
                "size_assuming_base_asset_units": str(size),
                "price_only_linear_pnl_estimate": str(round(estimate, 8)),
                "exchange_unrealized_pnl": str(pnl),
                "difference": str(round(pnl - estimate, 8)),
                "formula_verified_against_exchange_contract_specs": False,
                "same_snapshot_timestamp_verified": False,
            })
        except ValueError:
            out.append({
                "symbol": "BTCUSDT",
                "side": "SHORT",
                "calculation": "UNAVAILABLE_INVALID_FIELDS",
                "formula_verified_against_exchange_contract_specs": False,
            })
    return out


def summarize_positions_history(response, active_rows):
    summary = collection_snapshot(response)
    if not isinstance(response, (dict, list)):
        return {"snapshot": summary, "status_counts": {}}
    if isinstance(response, list):
        rows = response
    else:
        rows = next(
            (response[key] for key in COLLECTION_KEYS if isinstance(response.get(key), list)),
            [],
        )
    counts = {}
    for p in rows:
        status = p.get("status")
        status = status.strip().upper() if isinstance(status, str) else ""
        status = status if status in VALID_STATUSES else "OTHER_OR_UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    active_ids = {str(p["id"]) for p in active_rows if p.get("id") is not None}
    not_active_ids = {
        str(p["id"]) for p in rows
        if p.get("id") is not None and str(p["id"]) not in active_ids
    }
    return {
        "snapshot": summary,
        "status_counts": counts,
        "history_position_ids_not_in_current_active_snapshot": len(not_active_ids),
        "note": "First page only; records missing from active snapshot are not necessarily closed.",
    }


def run(exchange: TheTrueTrade, mode: str):
    if mode != "off":
        raise ExchangeError("Read-only account audit requires Live Mirror OFF")
    if exchange.base != "https://apiv2.thetruetrade.io":
        raise ExchangeError("Non-official exchange base URL blocked")

    original = exchange.request

    def only_safe_get(method, path, query=None, body=None, auth=True):
        query_tuple = tuple(sorted((query or {}).items()))
        if (str(method).upper() != "GET" or body is not None or auth is not True
                or (path, query_tuple) not in ALLOWED_REQUESTS):
            raise ExchangeError("Account audit blocked a non-allowlisted API operation")
        return original(method, path, query=query)

    exchange.request = only_safe_get
    try:
        active = exchange._raw_positions()
        result = {
            "current_open_position_records": len(active),
            "current_position_status_counts": {
                "OPEN_OR_OPENED": len(active),
            },
            "btc_short_price_pnl_diagnostic": pnl_price_check(active),
            "stop_loss_verified_by_api": False,
            "live_trading_authorized": False,
            "read_only": True,
        }

        # Each route is documented, but live response schemas may differ. Preserve
        # independently valid parts of the audit if an optional read fails.
        for label, path, query in (
            ("position_history", "/futures/positions", {"page": 1}),
            ("trade_history", "/futures/trades", {"page": 1}),
            ("futures_pnl_history", "/futures/assets/pnl", None),
        ):
            try:
                payload = exchange.request("GET", path, query)
                if label == "position_history":
                    result[label] = summarize_positions_history(payload, active)
                else:
                    result[label] = collection_snapshot(payload)
            except Exception:
                result[label] = {
                    "schema": "UNAVAILABLE_OR_UNRECOGNIZED",
                    "complete_history_proven": False,
                }
        try:
            result["futures_equity_usdt"] = exchange.equity()
        except Exception:
            result["futures_equity_usdt"] = "UNAVAILABLE"
        try:
            result["available_margin_usdt"] = exchange.available_balance()
        except Exception:
            result["available_margin_usdt"] = "UNAVAILABLE"

        result["conclusion"] = "DIAGNOSTIC_ONLY"
        result["limitations"] = (
            "Historical endpoints show at most page 1 and may omit older records. "
            "Trade PnL, transfers, realized PnL, fees and funding are NOT reconciled. "
            "The price-only PnL check assumes size is BTC base units. "
            "This report does not prove TP/SL activation."
        )
        return result
    finally:
        exchange.request = original


def main():
    try:
        result = run(TheTrueTrade(), read_config()["mode"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Redact raw API errors, IDs, request payloads and credentials.
        print(json.dumps({
            "conclusion": "ERROR",
            "error_type": type(exc).__name__,
            "read_only": True,
            "live_trading_authorized": False,
            "message": "Read-only audit failed; no live action authorized.",
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
