#!/usr/bin/env python3
"""Tests for automated SQLite right-sizing maintenance orchestration."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.db_right_size_maintenance import run  # noqa: E402


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
        con.execute("INSERT INTO trades(symbol) VALUES ('AAPL')")
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
        con.executemany(
            "INSERT INTO feature_snapshots(timestamp, symbol, last_price) VALUES (?, ?, ?)",
            [
                ("2026-06-01T14:30:00+00:00", "AAPL", 100.0),
                ("2026-06-10T14:30:00+00:00", "MSFT", 200.0),
            ],
        )


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _inactive_service(name: str) -> dict[str, object]:
    return {
        "name": name,
        "unit": f"{name}.service",
        "status": "inactive",
        "active": False,
        "returncode": 3,
    }


def _active_service(name: str) -> dict[str, object]:
    return {
        "name": name,
        "unit": f"{name}.service",
        "status": "active",
        "active": True,
        "returncode": 0,
    }


def test_right_size_blocks_mutation_during_market_hours():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        _build_db(db_path)

        with (
            patch("pipeline.db_right_size_maintenance.is_market_hours", return_value=True),
            patch("pipeline.db_right_size_maintenance.market_session", return_value="open"),
            patch(
                "pipeline.db_right_size_maintenance.sqlite_vacuum_swap._service_status",
                side_effect=_inactive_service,
            ),
        ):
            manifest = run(
                db_path=db_path,
                target_date=date(2026, 6, 15),
                execute_archive=True,
                build_compact=False,
                swap_compact=False,
                checkpoint=False,
                prune_rollbacks=False,
                compact_path=None,
                archive_root=base / "archive",
                manifest_dir=base / "manifests",
                chunk_size=10,
                max_chunks=0,
                rollback_retention_days=2,
                rollback_min_keep=0,
                skip_training_evidence=True,
                force=False,
                skip_market_hours_check=False,
                skip_service_check=False,
                service_names=("trading-bot",),
                dbstat_limit=0,
                dbstat_timeout_sec=1.0,
            )

        assert manifest["status"] == "blocked_market_hours"
        assert _count(db_path, "feature_snapshots") == 2


def test_right_size_allows_online_archive_when_service_active():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        _build_db(db_path)

        with (
            patch("pipeline.db_right_size_maintenance.is_market_hours", return_value=False),
            patch("pipeline.db_right_size_maintenance.market_session", return_value="closed"),
            patch(
                "pipeline.db_right_size_maintenance.sqlite_vacuum_swap._service_status",
                side_effect=_active_service,
            ),
        ):
            manifest = run(
                db_path=db_path,
                target_date=date(2026, 6, 15),
                execute_archive=True,
                build_compact=False,
                swap_compact=False,
                checkpoint=False,
                prune_rollbacks=False,
                compact_path=None,
                archive_root=base / "archive",
                manifest_dir=base / "manifests",
                chunk_size=10,
                max_chunks=0,
                rollback_retention_days=2,
                rollback_min_keep=0,
                skip_training_evidence=True,
                force=False,
                skip_market_hours_check=False,
                skip_service_check=False,
                service_names=("trading-bot",),
                dbstat_limit=0,
                dbstat_timeout_sec=1.0,
            )

        assert manifest["status"] == "complete"
        assert _count(db_path, "feature_snapshots") == 1


def test_right_size_blocks_swap_when_service_active():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        compact_path = base / "compact.db"
        _build_db(db_path)
        _build_db(compact_path)

        with (
            patch("pipeline.db_right_size_maintenance.is_market_hours", return_value=False),
            patch("pipeline.db_right_size_maintenance.market_session", return_value="closed"),
            patch(
                "pipeline.db_right_size_maintenance.sqlite_vacuum_swap._service_status",
                side_effect=_active_service,
            ),
        ):
            manifest = run(
                db_path=db_path,
                target_date=date(2026, 6, 15),
                execute_archive=False,
                build_compact=False,
                swap_compact=True,
                checkpoint=False,
                prune_rollbacks=False,
                compact_path=compact_path,
                archive_root=base / "archive",
                manifest_dir=base / "manifests",
                chunk_size=10,
                max_chunks=0,
                rollback_retention_days=2,
                rollback_min_keep=0,
                skip_training_evidence=True,
                force=False,
                skip_market_hours_check=False,
                skip_service_check=False,
                service_names=("trading-bot",),
                dbstat_limit=0,
                dbstat_timeout_sec=1.0,
            )

        assert manifest["status"] == "blocked_active_services"
        assert compact_path.exists()


def test_right_size_executes_archive_checkpoint_and_compact_copy_off_hours():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        compact_path = base / "compact.db"
        _build_db(db_path)

        with (
            patch("pipeline.db_right_size_maintenance.is_market_hours", return_value=False),
            patch("pipeline.db_right_size_maintenance.market_session", return_value="closed"),
            patch(
                "pipeline.db_right_size_maintenance.sqlite_vacuum_swap._service_status",
                side_effect=_inactive_service,
            ),
        ):
            manifest = run(
                db_path=db_path,
                target_date=date(2026, 6, 15),
                execute_archive=True,
                build_compact=True,
                swap_compact=False,
                checkpoint=True,
                prune_rollbacks=False,
                compact_path=compact_path,
                archive_root=base / "archive",
                manifest_dir=base / "manifests",
                chunk_size=10,
                max_chunks=0,
                rollback_retention_days=2,
                rollback_min_keep=0,
                skip_training_evidence=True,
                force=False,
                skip_market_hours_check=False,
                skip_service_check=False,
                service_names=("trading-bot",),
                dbstat_limit=0,
                dbstat_timeout_sec=1.0,
            )

        assert manifest["status"] == "complete"
        assert _count(db_path, "feature_snapshots") == 1
        assert _count(base / "archive" / "features.db", "feature_snapshots") == 1
        assert compact_path.exists()
        actions = [row["action"] for row in manifest["actions"]]
        assert "cold_learning_archive" in actions
        assert "sqlite_vacuum_swap" in actions
        assert "sqlite_wal_checkpoint" in actions


if __name__ == "__main__":
    test_right_size_blocks_mutation_during_market_hours()
    test_right_size_allows_online_archive_when_service_active()
    test_right_size_blocks_swap_when_service_active()
    test_right_size_executes_archive_checkpoint_and_compact_copy_off_hours()
    print("[OK] db right-size maintenance tests passed")
