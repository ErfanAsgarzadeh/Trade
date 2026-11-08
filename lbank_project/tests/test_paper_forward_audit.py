"""Regression tests for entirely read-only three-bot PAPER forward audit."""
import json
import sqlite3
from pathlib import Path

import pytest
import paper_forward_audit as audit


def make_db(tmp_path, bot):
    path = tmp_path / (bot + ".db")
    db = sqlite3.connect(path)
    if bot == "Shahin":
        db.executescript("""
        CREATE TABLE trade_history (
            id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, qty REAL,
            entry_price REAL, exit_price REAL, pnl_usd REAL,
            closed_at REAL, reason TEXT, dry_run INTEGER);
        CREATE TABLE positions (
            symbol TEXT, side TEXT, entry_price REAL, qty REAL,
            contract_size REAL, isolated_leverage INTEGER, active_sl REAL,
            state TEXT);
        """)
        db.execute(
            "INSERT INTO trade_history VALUES(1,'BTC/USDT:USDT','long',0.1,100,90,-1.5,1700000020,'stop',1)")
        db.execute(
            "INSERT INTO trade_history VALUES(2,'BTC/USDT:USDT','long',0.1,100,110,0.5,1700000050,'tp1',1)")
    else:
        db.executescript("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, symbol TEXT, side TEXT,
            entry REAL, exit REAL, qty REAL,
            opened REAL, closed REAL, pnl REAL, reason TEXT);
        CREATE TABLE positions (
            symbol TEXT, side TEXT, entry REAL, qty REAL, stop REAL, opened REAL);
        CREATE TABLE position_margin (
            symbol TEXT, opened REAL, isolated_leverage INTEGER);
        """)
        db.execute(
            "INSERT INTO trades VALUES(1,'ETH/USDT:USDT','long',100,110,2,1699999900,1700000020,19.58,'target')")
        db.execute(
            "INSERT INTO trades VALUES(2,'ETH/USDT:USDT','short',100,110,2,1699999990,1700000050,-20.42,'stop')")
        db.execute(
            "INSERT INTO positions VALUES('ETH/USDT:USDT','long',200,2,194,1700000100)")
        db.execute(
            "INSERT INTO position_margin VALUES('ETH/USDT:USDT',1700000100,5)")
    db.commit()
    db.close()
    return path


@pytest.mark.parametrize("bot", ("Shahin", "Mojsavar", "Ghoghnous"))
def test_accounting_and_reasons_21_days(tmp_path, bot):
    p = make_db(tmp_path, bot)
    with audit.db_readonly(p) as db:
        detail = audit.audit_one(db, bot, audit.SOURCES[bot], 1700000000)
    assert detail["integrity"] == "ok"
    assert detail["closed_rows_21d"] == 2
    assert detail["winning_close_rows"] == 1
    assert detail["losing_close_rows"] == 1
    assert len(detail["by_reason"]) == 2
    if bot == "Shahin":
        assert detail["realized_pnl_usdt"] == -1
        assert not detail["open_positions"]
        assert "NOT_PROVEN" in detail["independent_cost_diagnostic"]["independent_pnl_reconciliation"]
    else:
        assert detail["realized_pnl_usdt"] == -0.84
        assert detail["independent_cost_diagnostic"]["gross_minus_recorded_pnl_total_usdt"] == .84
        pos = detail["open_positions"][0]
        assert pos["entry_notional_usdt_if_known"] == 400
        assert pos["initial_margin_usdt_if_known"] == 80
        assert pos["remaining_entry_to_stop_risk_usdt_excluding_costs"] == 12
        assert pos["current_unrealized_pnl"] == "NOT_EVALUATED_REQUIRES_VALID_MARK_PRICE"
    assert detail["replay_of_all_entry_signals_verified"] is False


def test_readonly_connection_wont_allow_database_changes(tmp_path):
    p = make_db(tmp_path, "Shahin")
    with audit.db_readonly(p) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM trade_history")
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO trade_history (id) VALUES(99)")
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0] == 2


def test_missing_db_does_not_create_file(tmp_path):
    p = tmp_path / "does-not-exist.db"
    with pytest.raises(FileNotFoundError):
        audit.db_readonly(p)
    assert not p.exists()


def test_negative_cost_is_flagged_not_labeled_as_fee():
    rows = [{
        "entry": 100, "exit": 110, "qty": 1,
        "side": "long", "pnl": 100,
    }]
    result = audit.accounting_check(rows, "entry", "exit", "Mojsavar")
    assert result["rows_with_unexpected_negative_implied_cost"] == 1
    assert result["cost_cannot_be_separated_into_fees_funding_slippage"] is True


def test_missing_historical_leverage_is_not_replaced_by_assumption(tmp_path):
    p = make_db(tmp_path, "Shahin")
    with sqlite3.connect(p) as db:
        db.execute("""
            INSERT INTO positions
            VALUES('BTC/USDT:USDT','long',100,2,1,0,90,'TRAILING')
        """)
    with audit.db_readonly(p) as db:
        result = audit.open_positions(db, "Shahin")
    assert result[0]["isolated_leverage_if_recorded"] is None
    assert result[0]["initial_margin_usdt_if_known"] is None
    assert result[0]["remaining_entry_to_stop_risk_usdt_excluding_costs"] == 20


def test_shahin_excludes_non_paper_legacy_rows_from_profit_totals(tmp_path):
    p = make_db(tmp_path, "Shahin")
    with sqlite3.connect(p) as db:
        db.execute("""
            INSERT INTO trade_history VALUES(
                3,'BTC/USDT:USDT','short',1,100,90,900,1700000060,'manual',0)
        """)
    with audit.db_readonly(p) as db:
        result = audit.audit_one(
            db, "Shahin", audit.SOURCES["Shahin"], 1700000000)
    assert result["closed_rows_21d"] == 2
    assert result["realized_pnl_usdt"] == -1
    assert result["excluded_nonpaper_shahin_rows_21d"] == 1
    assert result["historic_scan_coverage_verified"] is False
