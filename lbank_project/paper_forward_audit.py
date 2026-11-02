"""Read-only 21-day PAPER performance and accounting diagnostic.

Reads existing SQLite files with mode=ro; no bot/config mutations, no exchange
credentials, no orders and no network calls. A close row is not always a trade.
Open positions are valued at entry, NOT live mark price. Historic configuration
and all fees/funding cannot be inferred from these ledgers alone.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
import json
import os
import sqlite3
import sys
import time

SOURCES = {
    "Shahin": ("BOT_DB", "trade_history", "closed_at", "pnl_usd", "entry_price", "exit_price"),
    "Mojsavar": ("C3_DB", "trades", "closed", "pnl", "entry", "exit"),
    "Ghoghnous": ("PA_DB", "trades", "closed", "pnl", "entry", "exit"),
}
WINDOW_DAYS = 21
PER_BOT_SAMPLE = 8


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if isfinite(result) else None


def iso(value):
    n = finite_number(value)
    if n is None or n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return None


def db_readonly(path):
    if not path.is_file():
        raise FileNotFoundError("paper database path not found")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=4)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def table_columns(db, table):
    return {r["name"] for r in db.execute("PRAGMA table_info(" + table + ")")}


def aggregate(rows, group_field):
    groups = defaultdict(lambda: {"rows": 0, "pnl": 0.0, "wins": 0})
    for row in rows:
        key = str(row.get(group_field) or "MISSING")
        if len(key) > 80:
            key = "INVALID_FIELD"
        v = groups[key]
        v["rows"] += 1
        v["pnl"] += row["pnl"]
        v["wins"] += row["pnl"] > 0
    return [{
        "label": key, "rows": d["rows"], "pnl": round(d["pnl"], 6),
        "winning_rows": d["wins"]
    } for key, d in sorted(groups.items(), key=lambda x: x[1]["pnl"])]


def accounting_check(rows, entry_col, exit_col, bot):
    """For C3/PA, gross = signed price move x reported base quantity.

    Difference gross-reported-pnl is the *implied* total cost, not a verified
    fee or funding amount. For Shahin, historical contract_size was not saved
    in trade_history; therefore independently validating the gross is unsafe.
    """
    if bot == "Shahin":
        return {
            "independent_pnl_reconciliation": "NOT_PROVEN_HISTORICAL_CONTRACT_SIZE_AND_FEE_RATE_MISSING"
        }
    implied = []
    invalid = 0
    unreasonable_negative_cost = 0
    for r in rows:
        ent, ext, qty = (finite_number(r.get(x)) for x in (entry_col, exit_col, "qty"))
        side = r.get("side")
        if (ent is None or ext is None or qty is None or ent <= 0 or ext <= 0
                or qty <= 0 or side not in ("long", "short")):
            invalid += 1
            continue
        gross = (1 if side == "long" else -1) * (ext - ent) * qty
        inferred_cost = gross - r["pnl"]
        if inferred_cost < -1e-5:
            unreasonable_negative_cost += 1
        implied.append(inferred_cost)
    return {
        "gross_to_recorded_pnl_rows_checked": len(implied),
        "rows_with_incomplete_trade_geometry": invalid,
        "gross_minus_recorded_pnl_total_usdt": round(sum(implied), 6),
        "rows_with_unexpected_negative_implied_cost": unreasonable_negative_cost,
        "cost_cannot_be_separated_into_fees_funding_slippage": True,
        "historical_round_trip_fee_verified": False,
    }


def open_positions(db, bot):
    cols = table_columns(db, "positions")
    rows = [dict(row) for row in db.execute("SELECT * FROM positions")]
    out = []
    for r in rows:
        if bot == "Shahin":
            state = r.get("state")
            if state == "PENDING":
                out.append({"symbol": r.get("symbol"), "state": "PENDING_NOT_OPEN"})
                continue
            ent, qty, cs, lev, stop = (
                finite_number(r.get(k)) for k in
                ("entry_price", "qty", "contract_size", "isolated_leverage", "active_sl")
            )
            side = r.get("side")
            if lev is None or lev <= 0:
                # Legacy rows may carry the leverage in a frozen config; avoid
                # inventing a default in this independent diagnostic.
                lev = None
            amount = qty * cs if qty is not None and cs is not None else None
        else:
            ent, qty, stop = (
                finite_number(r.get(k)) for k in ("entry", "qty", "stop")
            )
            cs = 1.0
            amount = qty
            side = r.get("side")
            lev = None
            if "position_margin" in {v["name"] for v in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                m = db.execute("SELECT isolated_leverage FROM position_margin WHERE symbol=? AND opened=?",
                               (r.get("symbol"), r.get("opened"))).fetchone()
                if m:
                    lev = finite_number(m[0])
        valid = (ent is not None and ent > 0 and amount is not None and amount > 0
                 and stop is not None and stop > 0 and side in ("long", "short"))
        risk = (max(0.0, (1 if side == "long" else -1) * (ent - stop) * amount)
                if valid else None)
        out.append({
            "symbol": r.get("symbol"),
            "side": side,
            "entry_price": ent,
            "quantity_base_units_if_verified": amount,
            "recorded_stop": stop,
            "isolated_leverage_if_recorded": lev,
            "entry_notional_usdt_if_known": round(ent * amount, 6)
                if ent is not None and amount is not None else None,
            "initial_margin_usdt_if_known": round(ent * amount / lev, 6)
                if ent is not None and amount is not None and lev is not None and lev > 0 else None,
            "remaining_entry_to_stop_risk_usdt_excluding_costs": round(risk, 6)
                if risk is not None else None,
            "current_unrealized_pnl": "NOT_EVALUATED_REQUIRES_VALID_MARK_PRICE",
        })
    return out


def audit_one(db, bot, source, start):
    _, table, ts_field, pnl_field, entry_col, exit_col = source
    required = {"symbol", "side", "reason", "qty", pnl_field, ts_field, entry_col, exit_col}
    if not required.issubset(table_columns(db, table)):
        raise ValueError("trade history schema mismatch")
    data = db.execute(
        f"SELECT * FROM {table} WHERE {ts_field} >= ? ORDER BY {ts_field}, id",
        (start,),
    ).fetchall()
    trade_rows = []
    dropped = 0
    for x in data:
        r = dict(x)
        p = finite_number(r.get(pnl_field))
        if p is None:
            dropped += 1
            continue
        r["pnl"] = p
        trade_rows.append(r)
    gains = sum(max(x["pnl"], 0) for x in trade_rows)
    losses = -sum(min(x["pnl"], 0) for x in trade_rows)
    return {
        "integrity": db.execute("PRAGMA quick_check").fetchone()[0],
        "closed_rows_21d": len(trade_rows),
        "invalid_pnl_rows": dropped,
        "winning_close_rows": sum(x["pnl"] > 0 for x in trade_rows),
        "losing_close_rows": sum(x["pnl"] < 0 for x in trade_rows),
        "realized_pnl_usdt": round(sum(x["pnl"] for x in trade_rows), 6),
        "gross_positive_rows_pnl_usdt": round(gains, 6),
        "gross_negative_rows_pnl_usdt": round(losses, 6),
        "row_based_profit_factor": round(gains / losses, 6) if losses > 0 else None,
        "worst_closed_row_usdt": round(min((x["pnl"] for x in trade_rows), default=0), 6),
        "best_closed_row_usdt": round(max((x["pnl"] for x in trade_rows), default=0), 6),
        "by_reason": aggregate(trade_rows, "reason"),
        "by_symbol": aggregate(trade_rows, "symbol"),
        "recent_closures": [
            {"symbol": x.get("symbol"), "side": x.get("side"),
             "reason": x.get("reason"), "pnl_usdt": round(x["pnl"], 6),
             "close_utc": iso(x[ts_field])}
            for x in trade_rows[-PER_BOT_SAMPLE:]
        ],
        "independent_cost_diagnostic": accounting_check(trade_rows, entry_col, exit_col, bot),
        "open_positions": open_positions(db, bot),
        "replay_of_all_entry_signals_verified": False,
        "historical_configs_available_or_unchanged_verified": False,
        "fees_and_funding_against_venue_verified": False,
    }


def main():
    now = time.time()
    start = now - WINDOW_DAYS * 86400
    result = {
        "read_only": True,
        "generated_utc": iso(now),
        "window_start_utc": iso(start),
        "window_days": WINDOW_DAYS,
        "paper_data_mode": os.getenv("PAPER_DATA_MODE"),
        "official_candles_flag": os.getenv("LBANK_OFFICIAL_CANDLES"),
        "bots": {},
        "combined_realized_pnl_usdt": None,
        "combined_floating_pnl_usdt": None,
        "conclusion": "DIAGNOSTIC_ONLY",
        "note": (
            "Close rows are NOT independent full trades. Open positions are NOT "
            "marked-to-market. Trade history does not prove entry signals, "
            "full candle coverage, funding, actual fills or historic configs."
        ),
    }
    count = 0
    total = 0.0
    for bot, source in SOURCES.items():
        env = source[0]
        raw = os.getenv(env)
        if not raw:
            result["bots"][bot] = {"status": "MISSING_DATABASE_ENV"}
            continue
        try:
            with db_readonly(Path(raw)) as db:
                detail = audit_one(db, bot, source, start)
            detail["status"] = "READ_OK"
            result["bots"][bot] = detail
            total += detail["realized_pnl_usdt"]
            count += 1
        except Exception as exc:
            result["bots"][bot] = {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "note": "Database access or schema error; no changes were made.",
            }
    if count == len(SOURCES):
        result["combined_realized_pnl_usdt"] = round(total, 6)
    else:
        result["conclusion"] = "INCOMPLETE_DIAGNOSTIC"
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["conclusion"] == "DIAGNOSTIC_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
