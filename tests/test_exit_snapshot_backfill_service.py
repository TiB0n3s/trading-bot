#!/usr/bin/env python3
"""Tests for historical canonical exit snapshot backfill."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.exit_snapshot_repo import ExitSnapshotRepository  # noqa: E402
from services.exit_snapshot_backfill_service import ExitSnapshotBackfillService  # noqa: E402
from services.exit_snapshot_service import ExitSnapshotService  # noqa: E402


def _db_path() -> Path:
    return Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)


def _seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY,
                decision_time TEXT,
                trade_id INTEGER,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                canonical_intelligence_version TEXT,
                canonical_intelligence_hash TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                qty INTEGER,
                fill_price REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE matched_trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                entry_order_id TEXT,
                exit_order_id TEXT,
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                holding_minutes REAL,
                qty REAL,
                entry_price REAL,
                exit_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                mfe_pct REAL,
                capture_ratio REAL,
                exit_reason TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_sell_decision_snapshots (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                candidate_timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT,
                severity TEXT,
                reason TEXT,
                auto_sell_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT,
                order_status TEXT,
                candidate_json TEXT,
                runtime_effect TEXT NOT NULL DEFAULT 'auto_sell_paper_execution_path'
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                id, decision_time, trade_id, symbol, action, approved,
                canonical_intelligence_version, canonical_intelligence_hash,
                canonical_intelligence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "2026-06-01 10:00:00",
                10,
                "NVDA",
                "buy",
                1,
                "canonical_intelligence_v1",
                "a" * 64,
                json.dumps(
                    {
                        "version": "canonical_intelligence_v1",
                        "feature_vector_hash": "a" * 64,
                        "decision_ts": "2026-06-01 10:00:00",
                        "regime_state": {"label": "trend"},
                        "momentum_state": {"state": "accelerating"},
                    }
                ),
            ),
        )
        con.execute(
            "INSERT INTO trades (id, order_id, qty, fill_price) VALUES (?, ?, ?, ?)",
            (10, "entry-1", 1, 100.0),
        )
        con.execute(
            """
            INSERT INTO matched_trades (
                id, symbol, entry_order_id, exit_order_id, entry_timestamp,
                exit_timestamp, holding_minutes, qty, entry_price, exit_price,
                realized_pnl, realized_pnl_pct, mfe_pct, capture_ratio, exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                20,
                "NVDA",
                "entry-1",
                "exit-1",
                "2026-06-01 10:00:00",
                "2026-06-01 10:45:00",
                45,
                1,
                100,
                101,
                1.0,
                1.0,
                1.5,
                0.66,
                "position_manager_full_exit",
            ),
        )
        con.execute(
            """
            INSERT INTO auto_sell_decision_snapshots (
                id, created_at, candidate_timestamp, symbol, action, severity, reason,
                auto_sell_enabled, order_submitted, order_id, order_status,
                candidate_json, runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99,
                "2026-06-01T10:44:59-05:00",
                "2026-06-01 10:44:59",
                "NVDA",
                "sell_candidate",
                "conviction_exit",
                "conviction_exit:trailing_stop",
                1,
                1,
                "exit-1",
                "accepted",
                json.dumps(
                    {
                        "conviction_exit_decision": {
                            "action": "exit",
                            "reason": "trailing_stop",
                        },
                        "layered_ml_final_instruction": "paper_exit",
                        "layered_ml_master_confidence_score": 0.82,
                        "layered_ml_ensemble_probability_pct": 71.0,
                        "sell_pressure_score": 4.0,
                        "sell_pressure_recommendation": "exit",
                    }
                ),
                "auto_sell_paper_execution_path",
            ),
        )


def _rows(db_path: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return list(con.execute("SELECT * FROM exit_snapshots ORDER BY id"))


def test_backfill_approved_matched_exits_is_idempotent():
    db_path = _db_path()
    _seed(db_path)
    repo = ExitSnapshotRepository(db_path)
    service = ExitSnapshotBackfillService(repo, ExitSnapshotService(repo))

    first = service.backfill_approved_matched_exits(start_date="2026-06-01")
    second = service.backfill_approved_matched_exits(start_date="2026-06-01")
    rows = _rows(db_path)

    assert first.scanned == 1
    assert first.inserted == 1
    assert second.scanned == 0
    assert second.inserted == 0
    assert len(rows) == 1
    assert rows[0]["decision_snapshot_id"] == 1
    assert rows[0]["entry_trade_id"] == 10
    assert rows[0]["matched_trade_id"] == 20
    assert rows[0]["symbol"] == "NVDA"
    assert rows[0]["realized_return_pct"] == 1.0
    assert rows[0]["missed_upside_pct"] == 0.5
    assert rows[0]["entry_canonical_intelligence_hash"] == "a" * 64
    snapshot = json.loads(rows[0]["canonical_exit_json"])
    auto_sell = snapshot["exit_trigger"]["metadata"]["auto_sell_decision"]
    assert auto_sell["auto_sell_snapshot_id"] == 99
    assert auto_sell["auto_sell_severity"] == "conviction_exit"
    assert auto_sell["conviction_exit_decision"]["action"] == "exit"
    assert auto_sell["layered_ml_final_instruction"] == "paper_exit"


def test_backfill_repairs_trade_backed_exit_without_decision_snapshot():
    db_path = _db_path()
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY,
                decision_time TEXT,
                trade_id INTEGER,
                symbol TEXT,
                action TEXT,
                approved INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                order_id TEXT,
                qty REAL,
                fill_price REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE matched_trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                entry_order_id TEXT,
                exit_order_id TEXT,
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                holding_minutes REAL,
                qty REAL,
                entry_price REAL,
                exit_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                mfe_pct REAL,
                capture_ratio REAL,
                exit_reason TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO trades (
                id, timestamp, symbol, action, approved, order_id, qty, fill_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (10, "2026-06-09 09:40:00", "JPM", "buy", 1, "entry-10", 1, 315.0),
        )
        con.execute(
            """
            INSERT INTO matched_trades (
                id, symbol, entry_order_id, exit_order_id, entry_timestamp,
                exit_timestamp, holding_minutes, qty, entry_price, exit_price,
                realized_pnl, realized_pnl_pct, mfe_pct, capture_ratio, exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                20,
                "JPM",
                "entry-10",
                "exit-10",
                "2026-06-09 09:40:00",
                "2026-06-09 09:42:00",
                2,
                1,
                315.0,
                315.5,
                0.5,
                0.16,
                0.22,
                0.73,
                "peak_lock_floor",
            ),
        )

    repo = ExitSnapshotRepository(db_path)
    service = ExitSnapshotBackfillService(repo, ExitSnapshotService(repo))

    first = service.backfill_approved_matched_exits(start_date="2026-06-09")
    second = service.backfill_approved_matched_exits(start_date="2026-06-09")
    rows = _rows(db_path)

    assert first.scanned == 1
    assert first.inserted == 1
    assert second.scanned == 0
    assert second.inserted == 0
    assert len(rows) == 1
    assert rows[0]["decision_snapshot_id"] is None
    assert rows[0]["entry_trade_id"] == 10
    assert rows[0]["matched_trade_id"] == 20
    assert rows[0]["symbol"] == "JPM"
    assert rows[0]["realized_return_pct"] == 0.16


if __name__ == "__main__":
    test_backfill_approved_matched_exits_is_idempotent()
    test_backfill_repairs_trade_backed_exit_without_decision_snapshot()
    print("[OK] test_backfill_approved_matched_exits_is_idempotent")
