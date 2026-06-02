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

from repositories.exit_snapshot_repo import ExitSnapshotRepository
from services.exit_snapshot_backfill_service import ExitSnapshotBackfillService
from services.exit_snapshot_service import ExitSnapshotService


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


if __name__ == "__main__":
    test_backfill_approved_matched_exits_is_idempotent()
    print("[OK] test_backfill_approved_matched_exits_is_idempotent")
