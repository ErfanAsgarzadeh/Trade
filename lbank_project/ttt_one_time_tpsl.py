"""One-time manual TP/SL PATCH for the previously identified real BTC SHORT.

Unlike the Live Mirror, this script only modifies the TP/SL of an EXISTING
position when every precondition matches. It never opens or closes trades.
Default invocation is read-only; --apply requires existing user authorization.
No automatic retries after a PATCH; an unknown outcome requires manual review.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from exchanges import ExchangeError, TheTrueTrade
from live_mirror import read_config

SYMBOL = "BTCUSDT"
SIDE = "SHORT"
ENTRY = Decimal("77855.4")
SIZE = Decimal("0.004835844590211942")
LEVERAGE = 150
TP = Decimal("76276")
SL = Decimal("78167")
BASE_URL = "https://apiv2.thetruetrade.io"
JOURNAL_NAME = "ttt_manual_btc_short_tpsl_intent.json"


def decimal_value(row, key):
    value = row.get(key)
    if isinstance(value, bool) or value is None:
        raise ExchangeError("Missing or invalid position risk field")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ExchangeError("Missing or invalid position risk field") from None
    if not result.is_finite():
        raise ExchangeError("Non-finite position risk field")
    return result


def preflight(rows):
    """Fail closed if the position has changed since the owner's snapshot."""
    if len(rows) != 1:
        raise ExchangeError("Expected exactly one active position; manual review required")
    row = rows[0]
    if row.get("symbol") != SYMBOL or row.get("side") != SIDE:
        raise ExchangeError("Active position identity changed")
    if str(row.get("status", "")).upper() not in ("OPEN", "OPENED"):
        raise ExchangeError("Target position is not open")
    if row.get("isActive") is False:
        raise ExchangeError("Target position is inactive")
    if abs(decimal_value(row, "entryPrice") - ENTRY) > Decimal("0.01"):
        raise ExchangeError("Target position entry price changed")
    if abs(decimal_value(row, "size") - SIZE) > Decimal("0.00000001"):
        raise ExchangeError("Target position size changed")
    if decimal_value(row, "leverage") != LEVERAGE:
        raise ExchangeError("Target position leverage changed")
    position_id = row.get("id")
    if (isinstance(position_id, bool) or
            not isinstance(position_id, (str, int)) or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(position_id))):
        raise ExchangeError("Invalid target position ID")
    mark = decimal_value(row, "markPrice")
    liquidation = decimal_value(row, "liquidationPrice")
    if not (TP < ENTRY < SL < liquidation and TP < mark < SL):
        raise ExchangeError("Price crossed target or stop/liq geometry is unsafe")
    if mark <= 0:
        raise ExchangeError("Invalid mark price")
    return str(position_id), mark, liquidation, row


def report_preflight(mark, liquidation, row):
    """Arithmetic check only; the exchange's reported PnL may follow other rules."""
    price_only_pnl = (ENTRY - mark) * SIZE
    pnl = decimal_value(row, "unrealizedPnL")
    difference = pnl - price_only_pnl
    return {
        "position_match": True,
        "symbol": SYMBOL,
        "side": SIDE,
        "leverage": LEVERAGE,
        "take_profit": str(TP),
        "stop_loss": str(SL),
        "trigger_reference": "MARK_PRICE",
        "stop_order_type": "STOP_MARKET",
        "take_profit_order_type": "TAKE_PROFIT_MARKET",
        "current_mark": str(mark),
        "liquidation_price": str(liquidation),
        "mark_to_stop_pct": str(round((SL - mark) / mark * 100, 5)),
        "mark_to_liquidation_pct": str(round((liquidation - mark) / mark * 100, 5)),
        "price_only_linear_pnl_estimate": str(round(price_only_pnl, 8)),
        "exchange_reported_unrealized_pnl": str(pnl),
        "reported_minus_price_only_estimate": str(round(difference, 8)),
        "pnl_reconciled": False,
        "stop_loss_verified": False,
    }


def journal_path():
    folder = Path(os.environ.get("TTT_TPSL_JOURNAL_DIR", "/app/runtime"))
    if not folder.is_dir():
        raise ExchangeError("Durable runtime journal folder missing")
    return folder / JOURNAL_NAME


def persist_new_intent(path, position_id):
    payload = {
        "operation": "PATCH_EXISTING_TPSL",
        "position_fingerprint": hashlib.sha256(position_id.encode()).hexdigest()[:16],
        "symbol": SYMBOL, "side": SIDE,
        "take_profit": str(TP), "stop_loss": str(SL),
        "started_at_utc": int(time.time()),
        "state": "PENDING_OUTCOME",
        "note": "Do not retry until exchange TP/SL state is independently checked.",
    }
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ExchangeError("Previous TP/SL intent exists; do not repeat PATCH automatically") from None
    with os.fdopen(fd, "w") as file:
        json.dump(payload, file, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    return payload


def update_intent(path, payload, state):
    # Atomic update; preserve the initial PENDING record across failures/crashes.
    updated = dict(payload, state=state, updated_at_utc=int(time.time()))
    tmp = path.with_name(path.name + ".tmp." + str(os.getpid()))
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(updated, file, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)


def run(exchange, *, apply=False, mode="off", intent_path=None):
    if mode != "off":
        raise ExchangeError("Live Mirror must remain OFF")
    if exchange.base != BASE_URL:
        raise ExchangeError("Refusing non-official API base URL")
    original = exchange.request
    intended_id = None
    permitted_patch = False

    def guarded(method, path, query=None, body=None, **kwargs):
        if kwargs:
            raise ExchangeError("Unexpected request arguments")
        if method == "GET" and path == "/futures/positions" and query == {"active": "true"} and body is None:
            return original(method, path, query=query)
        if (method == "PATCH" and permitted_patch and path ==
                f"/futures/positions/{intended_id}/tpsl" and query is None and body == {
                    "takeProfit": str(TP),
                    "takeProfitOrderType": "TAKE_PROFIT_MARKET",
                    "takeProfitStrategy": "MARK_PRICE",
                    "stopLoss": str(SL),
                    "stopLossOrderType": "STOP_MARKET",
                    "stopLossStrategy": "MARK_PRICE",
                }):
            return original(method, path, body=body)
        raise ExchangeError("Blocked unapproved API operation")

    exchange.request = guarded
    try:
        first = exchange._raw_positions()
        position_id, mark, liquidation, row = preflight(first)
        summary = report_preflight(mark, liquidation, row)
        summary.update(patch_sent=False, live_mirror_enabled=False, conclusion="PREVIEW_ONLY")
        if not apply:
            return summary
        path = intent_path if intent_path is not None else journal_path()
        if path.exists():
            raise ExchangeError("Previous TP/SL intent exists; investigate before any retry")

        # Re-read immediately before the single PATCH to limit stale-snapshot risk.
        fresh_id, fresh_mark, fresh_liq, fresh_row = preflight(exchange._raw_positions())
        if fresh_id != position_id:
            raise ExchangeError("Target position identifier changed")
        if abs(fresh_mark - mark) / mark > Decimal("0.002"):
            raise ExchangeError("Mark price changed over 0.2 percent during preflight")
        intended_id = fresh_id
        # Persist BEFORE request. Even a timeout can mean the PATCH succeeded.
        intent = persist_new_intent(path, intended_id)
        permitted_patch = True
        body = {
            "takeProfit": str(TP),
            "takeProfitOrderType": "TAKE_PROFIT_MARKET",
            "takeProfitStrategy": "MARK_PRICE",
            "stopLoss": str(SL),
            "stopLossOrderType": "STOP_MARKET",
            "stopLossStrategy": "MARK_PRICE",
        }
        try:
            response = exchange.request(
                "PATCH", f"/futures/positions/{intended_id}/tpsl", body=body)
            if isinstance(response, dict) and response.get("errors"):
                raise ExchangeError("Exchange reported errors on TP/SL update")
        except Exception:
            # Do not auto-retry. For timeouts, the exchange may have applied it.
            raise ExchangeError(
                "TP/SL PATCH outcome uncertain or rejected; inspect exchange UI and journal, do not retry") from None
        finally:
            permitted_patch = False
        update_intent(path, intent, "ACKNOWLEDGED_NOT_VERIFIED")
        # Read back is intentionally not trusted to verify TPSL: positions
        # omit its fields; /futures/orders?active=true was empty in real account.
        summary.update(
            patch_sent=True,
            conclusion="ACKNOWLEDGED_NOT_VERIFIED",
            stop_loss_verified=False,
            note="Exchange PATCH acknowledged; check TP/SL visually in exchange UI.",
        )
        return summary
    finally:
        exchange.request = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Send exactly one PATCH for the expected existing BTC short")
    args = parser.parse_args()
    try:
        result = run(TheTrueTrade(), apply=args.apply, mode=read_config()["mode"])
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # Never print raw API errors, position IDs, headers or credentials.
        print(json.dumps({
            "conclusion": "ERROR",
            "error_type": type(exc).__name__,
            "message": str(exc) if isinstance(exc, ExchangeError)
                       and "TheTrueTrade " not in str(exc) else
                       "TP/SL check failed; see exchange UI, do not auto-retry.",
            "stop_loss_verified": False,
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
