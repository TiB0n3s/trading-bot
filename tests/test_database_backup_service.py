#!/usr/bin/env python3
"""Tests for SQLite backup and restore verification."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.database_backup_service import (  # noqa: E402
    DatabaseBackupService,
    DatabaseRestoreDrillService,
)
from trading_bot.ops_checks.commands.database_backup_checks import (
    run_database_backup_report,  # noqa: E402
    run_database_restore_drill,
)


def _build_db(path: Path, *, table_name: str = "sample") -> None:
    with sqlite3.connect(path) as con:
        con.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, value TEXT)")
        con.execute(f"INSERT INTO {table_name} (value) VALUES ('ok')")


def test_database_backup_service_verifies_online_backup():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        manifest = service.run(
            db_names=["trades.db", "predictions.db"],
            timestamp="20260608T150000Z",
        )

        assert manifest.ok
        assert manifest.backed_up_count == 1
        assert manifest.missing_count == 1
        row = manifest.results[0]
        assert row.status == "verified"
        assert row.integrity_check == "ok"
        assert row.table_count == 1
        assert row.backup_path is not None

        with sqlite3.connect(row.backup_path) as con:
            value = con.execute("SELECT value FROM sample").fetchone()[0]
        assert value == "ok"


def test_database_backup_cli_writes_manifest_and_ops_report_reads_it():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "jobs.db", table_name="job_runs")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "pipeline" / "database_backup.py"),
                "--base-dir",
                str(base_dir),
                "--backup-dir",
                str(backup_dir),
                "--db",
                "jobs.db",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        assert "backed_up=1" in result.stdout
        manifests = list(backup_dir.glob("database_backup_*.manifest.json"))
        assert len(manifests) == 1
        assert run_database_backup_report(base_dir=base_dir, max_age_hours=24.0) is True


def test_database_restore_drill_verifies_latest_backup_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        backup_service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        backup_manifest = backup_service.run(
            db_names=["trades.db"],
            timestamp="20260608T150000Z",
        )
        backup_service.write_manifest(backup_manifest)

        drill_service = DatabaseRestoreDrillService(backup_dir=backup_dir)
        restore_manifest = drill_service.run(restore_dir=backup_dir / "restore_test")

        assert restore_manifest.ok
        assert restore_manifest.verified_count == 1
        assert restore_manifest.results[0].integrity_check == "ok"
        assert Path(restore_manifest.results[0].restore_path).exists()
        assert run_database_restore_drill(base_dir=base_dir) is True


if __name__ == "__main__":
    test_database_backup_service_verifies_online_backup()
    test_database_backup_cli_writes_manifest_and_ops_report_reads_it()
    test_database_restore_drill_verifies_latest_backup_manifest()
    print("database backup service tests passed")
