#!/usr/bin/env python3
"""Tests for downtime-safe SQLite VACUUM INTO swap workflow."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.sqlite_vacuum_swap import prune_rollback_files, run


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
        con.execute("CREATE INDEX idx_trades_symbol ON trades(symbol)")
        con.execute("INSERT INTO trades(symbol) VALUES ('AAPL')")
        con.execute("CREATE TABLE feature_snapshots (id INTEGER PRIMARY KEY, symbol TEXT)")
        con.executemany(
            "INSERT INTO feature_snapshots(symbol) VALUES (?)",
            [("AAPL",), ("MSFT",), ("NVDA",)],
        )
        con.execute("DELETE FROM feature_snapshots WHERE symbol = 'MSFT'")


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_vacuum_swap_builds_compact_copy_without_swapping():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        compact = base / "compact.db"
        _build_db(db_path)

        manifest = run(
            db_path=db_path,
            compact_path=compact,
            manifest_dir=base / "manifests",
            build=True,
            swap=False,
            replace_build=False,
            force=False,
            skip_service_check=True,
            service_names=(),
        )

        assert manifest["status"] == "complete"
        assert compact.exists()
        assert _count(compact, "trades") == 1
        assert _count(db_path, "feature_snapshots") == 2
        assert _count(compact, "feature_snapshots") == 2


def test_vacuum_swap_blocks_swap_when_runtime_service_active():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        compact = base / "compact.db"
        _build_db(db_path)
        _build_db(compact)

        with patch(
            "pipeline.sqlite_vacuum_swap._service_status",
            return_value={
                "name": "trading-bot",
                "unit": "trading-bot.service",
                "status": "active",
                "active": True,
            },
        ):
            manifest = run(
                db_path=db_path,
                compact_path=compact,
                manifest_dir=base / "manifests",
                build=False,
                swap=True,
                replace_build=False,
                force=False,
                skip_service_check=False,
                service_names=("trading-bot",),
            )

        assert manifest["status"] == "blocked_active_services"
        assert db_path.exists()
        assert compact.exists()


def test_vacuum_swap_swaps_compact_copy_and_keeps_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        compact = base / "compact.db"
        _build_db(db_path)
        with sqlite3.connect(compact) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
            con.execute("INSERT INTO trades(symbol) VALUES ('MSFT')")

        manifest = run(
            db_path=db_path,
            compact_path=compact,
            manifest_dir=base / "manifests",
            build=False,
            swap=True,
            replace_build=False,
            force=False,
            skip_service_check=True,
            service_names=(),
        )

        assert manifest["status"] == "complete"
        assert _count(db_path, "trades") == 1
        with sqlite3.connect(db_path) as con:
            symbol = con.execute("SELECT symbol FROM trades").fetchone()[0]
        assert symbol == "MSFT"
        rollback_path = Path(manifest["actions"][0]["result"]["rollback_path"])
        assert rollback_path.exists()
        with sqlite3.connect(rollback_path) as con:
            symbol = con.execute("SELECT symbol FROM trades").fetchone()[0]
        assert symbol == "AAPL"


def test_prune_rollback_files_removes_stale_rollbacks_and_sidecars():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        _build_db(db_path)
        stale = base / "trades.db.rollback_20260601T000000Z"
        stale_wal = base / "trades.db.rollback_20260601T000000Z.trades.db-wal"
        fresh = base / "trades.db.rollback_20260617T000000Z"
        stale.write_text("old")
        stale_wal.write_text("old wal")
        fresh.write_text("fresh")
        old_ts = 1_700_000_000
        fresh_ts = 1_900_000_000
        for path in (stale, stale_wal):
            path.touch()
            os.utime(path, (old_ts, old_ts))
        fresh.touch()
        os.utime(fresh, (fresh_ts, fresh_ts))

        result = prune_rollback_files(
            db_path=db_path,
            retention_days=2,
            min_keep=1,
            dry_run=False,
        )

        assert result["pruned_count"] == 2
        assert not stale.exists()
        assert not stale_wal.exists()
        assert fresh.exists()
        assert result["retained_count"] == 1


if __name__ == "__main__":
    test_vacuum_swap_builds_compact_copy_without_swapping()
    test_vacuum_swap_blocks_swap_when_runtime_service_active()
    test_vacuum_swap_swaps_compact_copy_and_keeps_rollback()
    test_prune_rollback_files_removes_stale_rollbacks_and_sidecars()
    print("[OK] sqlite vacuum swap tests passed")
