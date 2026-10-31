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


def main() -> int:
    try:
        result = audit_exchange(TheTrueTrade(), read_config()["mode"])
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
