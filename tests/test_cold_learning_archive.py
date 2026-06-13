#!/usr/bin/env python3
"""Tests for cold ML learning archival."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.cold_learning_archive import run_archive


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as con:
        row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                feature_version TEXT,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                last_price REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY,
                decision_time TEXT,
                symbol TEXT,
                final_decision TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                entry_time TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features (
                symbol, bar_timestamp, timeframe, feature_version,
                triple_barrier_label, trend_scan_label
            ) VALUES (?, ?, '1m', 'v4', 1, 1)
            """,
            [
                ("AAPL", "2026-06-01T14:30:00+00:00"),
                ("MSFT", "2026-06-11T14:30:00+00:00"),
            ],
        )
        con.executemany(
            "INSERT INTO feature_snapshots(timestamp, symbol, last_price) VALUES (?, ?, ?)",
            [
                ("2026-06-01T14:30:00+00:00", "AAPL", 100.0),
                ("2026-06-08T14:30:00+00:00", "MSFT", 200.0),
            ],
        )
        con.executemany(
            """
            INSERT INTO decision_snapshots(decision_time, symbol, final_decision)
            VALUES (?, ?, ?)
            """,
            [
                ("2026-05-01T14:30:00+00:00", "AAPL", "approved"),
                ("2026-06-01T14:30:00+00:00", "MSFT", "rejected"),
            ],
        )
        con.execute("INSERT INTO trades(symbol, entry_time) VALUES ('AAPL', '2026-05-01')")


def test_cold_learning_archive_dry_run_does_not_mutate():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        _build_db(db_path)
        manifest = run_archive(
            db_path=db_path,
            archive_root=base / "archive",
            target_date=date(2026, 6, 12),
            execute=False,
            chunk_size=1,
            max_chunks=0,
            skip_training_evidence=True,
            selected_tables=None,
        )
        statuses = {row["table"]: row["status"] for row in manifest["tables"]}
        assert statuses["bar_pattern_features"] == "dry_run"
        assert _count(db_path, "bar_pattern_features") == 2
        assert not (base / "archive" / "historical_bars.db").exists()


def test_cold_learning_archive_moves_only_expired_learning_rows_and_preserves_trades():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        archive_root = base / "archive"
        _build_db(db_path)
        manifest = run_archive(
            db_path=db_path,
            archive_root=archive_root,
            target_date=date(2026, 6, 12),
            execute=True,
            chunk_size=1,
            max_chunks=0,
            skip_training_evidence=True,
            selected_tables=None,
        )
        rows = {row["table"]: row for row in manifest["tables"]}
        assert rows["bar_pattern_features"]["archived_rows"] == 1
        assert rows["feature_snapshots"]["archived_rows"] == 1
        assert rows["decision_snapshots"]["archived_rows"] == 1
        assert _count(db_path, "bar_pattern_features") == 1
        assert _count(db_path, "feature_snapshots") == 1
        assert _count(db_path, "decision_snapshots") == 1
        assert _count(db_path, "trades") == 1
        assert _count(archive_root / "historical_bars.db", "bar_pattern_features") == 1
        assert _count(archive_root / "features.db", "feature_snapshots") == 1
        assert _count(archive_root / "learning_archive.db", "decision_snapshots") == 1


if __name__ == "__main__":
    test_cold_learning_archive_dry_run_does_not_mutate()
    test_cold_learning_archive_moves_only_expired_learning_rows_and_preserves_trades()
    print("[OK] cold learning archive tests passed")
