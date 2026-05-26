#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import ensure_decision_snapshots_table
from decision_snapshots import record_decision_snapshot, summarize_snapshots


def assert_equal(actual, expected, message=""):
    if actual != expected:
        raise AssertionError(f"{message} expected={expected!r} actual={actual!r}")


def test_record_decision_snapshot_stores_core_audit_fields():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT
                )
                """
            )
            trade_id = con.execute(
                "INSERT INTO trades (timestamp, symbol, action) VALUES (?, ?, ?)",
                ("2026-05-26 09:31:00", "AAPL", "buy"),
            ).lastrowid

        ensure_decision_snapshots_table(db_path)
        snapshot_id = record_decision_snapshot(
            trade_id=trade_id,
            timestamp="2026-05-26 09:31:00",
            source="test",
            symbol="AAPL",
            action="buy",
            signal_price=100.0,
            decision={"approved": True, "confidence": "high", "position_size_pct": 1.0},
            order={"order_id": "abc", "status": "filled"},
            context={"market_bias": "buy", "session_trend_label": "strong_uptrend"},
            account_state={
                "prediction_gate": {"prediction_score": 71, "prediction_decision": "observe_only"},
                "setup_observation": {"setup_label": "near_vwap_recovery", "setup_policy_action": "boost"},
            },
            raw_signal={"symbol": "AAPL", "action": "buy", "price": 100.0},
            db_path=db_path,
        )

        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM decision_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

        assert_equal(row["trade_id"], trade_id)
        assert_equal(row["symbol"], "AAPL")
        assert_equal(row["approved"], 1)
        assert_equal(row["order_id"], "abc")
        assert_equal(row["market_bias"], "buy")
        assert_equal(row["session_trend_label"], "strong_uptrend")
        assert_equal(row["prediction_score"], 71.0)
        assert_equal(row["setup_label"], "near_vwap_recovery")

        summary = summarize_snapshots("2026-05-26", db_path)
        assert_equal(summary["total"], 1)
        assert_equal(summary["symbols"], 1)


if __name__ == "__main__":
    test_record_decision_snapshot_stores_core_audit_fields()
    print("[OK] decision snapshot tests passed")
