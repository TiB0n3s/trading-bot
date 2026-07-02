#!/usr/bin/env python3
"""Tests for SQLite backup and restore verification."""

from __future__ import annotations

import os
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.database_backup_service import (  # noqa: E402
    DatabaseBackupService,
    DatabaseRestoreDrillService,
)
from trading_bot.ops_checks.commands.database_backup_checks import (
    _elapsed_minutes,
    _recent_unmanifested_backup_artifacts,
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
        heartbeat = base_dir / "backups" / "database_backup_heartbeat.json"
        assert heartbeat.exists()
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


def test_database_backup_service_reuses_recent_verified_full_backup():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        first = service.run(
            db_names=["trades.db"],
            timestamp="20260608T150000Z",
        )
        service.write_manifest(first)

        second = service.run(
            db_names=["trades.db"],
            timestamp="20260608T160000Z",
            skip_recent_full_hours=24.0,
        )
        manifest_path = service.write_manifest(second)

        assert second.ok
        assert second.backed_up_count == 0
        assert second.reused_count == 1
        assert second.results[0].status == "reused_recent_full"
        assert second.results[0].backup_path == first.results[0].backup_path
        assert run_database_backup_report(base_dir=base_dir, max_age_hours=24.0) is True

        drill_service = DatabaseRestoreDrillService(backup_dir=backup_dir)
        restore_manifest = drill_service.run(
            manifest_path=manifest_path,
            restore_dir=backup_dir / "restore_reused_test",
        )
        assert restore_manifest.ok
        assert restore_manifest.verified_count == 1


def test_database_backup_service_reports_copy_progress():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        progress_phases = []
        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        manifest = service.run(
            db_names=["trades.db"],
            timestamp="20260608T150000Z",
            progress_callback=lambda payload: progress_phases.append(payload.get("phase")),
        )

        assert manifest.ok
        assert "copy" in progress_phases


def test_database_backup_service_reuses_recent_existing_full_artifact_without_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        existing_dir = backup_dir / "20260608T150000Z"
        existing_dir.mkdir(parents=True)
        existing_backup = existing_dir / "trades.db"
        existing_backup.write_bytes((base_dir / "trades.db").read_bytes())

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        manifest = service.run(
            db_names=["trades.db"],
            timestamp="20260608T160000Z",
            skip_recent_full_hours=24.0,
        )

        assert manifest.ok
        assert manifest.backed_up_count == 0
        assert manifest.reused_count == 1
        assert manifest.results[0].status == "reused_recent_existing_full"
        assert manifest.results[0].backup_path == str(existing_backup)


def test_database_backup_service_writes_and_prunes_by_gfs_tier():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        old_son_dir = backup_dir / "son" / "20260601T150000Z"
        old_father_dir = backup_dir / "father" / "20260601T150000Z"
        old_son_dir.mkdir(parents=True)
        old_father_dir.mkdir(parents=True)
        old_son_backup = old_son_dir / "trades.db"
        old_father_backup = old_father_dir / "trades.db"
        old_son_backup.write_bytes((base_dir / "trades.db").read_bytes())
        old_father_backup.write_bytes((base_dir / "trades.db").read_bytes())
        old_time = time.time() - (10 * 24 * 60 * 60)
        old_son_backup.touch()
        old_father_backup.touch()
        os.utime(old_son_backup, (old_time, old_time))
        os.utime(old_father_backup, (old_time, old_time))

        manifest = service.run(
            db_names=["trades.db"],
            timestamp="20260612T150000Z",
            backup_tier="son",
            retention_days=7,
        )
        manifest_path = service.write_manifest(manifest)

        assert manifest.ok
        assert manifest.backup_tier == "son"
        assert "/son/" in str(manifest.results[0].backup_path)
        assert "/son/" in str(manifest_path)
        assert str(old_son_backup) in manifest.pruned_files
        assert not old_son_backup.exists()
        assert old_father_backup.exists()


def test_database_backup_service_adhoc_prune_does_not_cross_tiers():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        old_son_dir = backup_dir / "son" / "20260601T150000Z"
        old_father_dir = backup_dir / "father" / "20260601T150000Z"
        old_adhoc_dir = backup_dir / "20260601T150000Z"
        old_son_dir.mkdir(parents=True)
        old_father_dir.mkdir(parents=True)
        old_adhoc_dir.mkdir(parents=True)

        old_son_backup = old_son_dir / "trades.db"
        old_father_backup = old_father_dir / "trades.db"
        old_adhoc_backup = old_adhoc_dir / "trades.db"
        for path in (old_son_backup, old_father_backup, old_adhoc_backup):
            path.write_bytes((base_dir / "trades.db").read_bytes())
            old_time = time.time() - (10 * 24 * 60 * 60)
            os.utime(path, (old_time, old_time))

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        manifest = service.run(
            db_names=["trades.db"],
            timestamp="20260612T150000Z",
            backup_tier="adhoc",
            retention_days=1,
        )

        assert manifest.ok
        assert str(old_adhoc_backup) in manifest.pruned_files
        assert not old_adhoc_backup.exists()
        assert old_son_backup.exists()
        assert old_father_backup.exists()


def test_database_backup_health_detects_recent_unmanifested_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        base_dir.mkdir()
        _build_db(base_dir / "trades.db")

        service = DatabaseBackupService(base_dir=base_dir, backup_dir=backup_dir)
        manifest = service.run(
            db_names=["trades.db"],
            timestamp="20260608T150000Z",
            backup_tier="son",
        )
        manifest_path = service.write_manifest(manifest)

        unmanifested_dir = backup_dir / "son" / "20260609T150000Z"
        unmanifested_dir.mkdir(parents=True)
        unmanifested = unmanifested_dir / "trades.db"
        unmanifested.write_bytes((base_dir / "trades.db").read_bytes())
        new_time = manifest_path.stat().st_mtime + 10
        os.utime(unmanifested, (new_time, new_time))

        assert _recent_unmanifested_backup_artifacts(backup_dir, manifest_path) == [unmanifested]


def test_database_backup_health_fails_missing_manifest_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "base"
        backup_dir = base_dir / "backups" / "databases"
        backup_dir.mkdir(parents=True)
        missing_backup = backup_dir / "20260608T150000Z" / "trades.db"
        manifest_path = backup_dir / "database_backup_20260608T150000Z.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "report_version": "database_backup_manifest_v1",
                    "created_at": "2026-06-08T15:00:00+00:00",
                    "dry_run": False,
                    "backup_tier": "adhoc",
                    "summary": {
                        "ok": True,
                        "backed_up_count": 1,
                        "reused_count": 0,
                        "missing_count": 0,
                        "failed_count": 0,
                    },
                    "results": [
                        {
                            "name": "trades.db",
                            "status": "verified",
                            "backup_path": str(missing_backup),
                            "integrity_check": "ok",
                            "table_count": 1,
                        }
                    ],
                }
            )
            + "\n"
        )

        assert run_database_backup_report(base_dir=base_dir, max_age_hours=100000.0) is False


def test_database_backup_health_parses_process_elapsed_time():
    assert _elapsed_minutes("02:30") == 2.5
    assert _elapsed_minutes("01:02:30") == 62.5
    assert _elapsed_minutes("1-01:00:00") == 1500
    assert _elapsed_minutes("not-a-time") is None


if __name__ == "__main__":
    test_database_backup_service_verifies_online_backup()
    test_database_backup_cli_writes_manifest_and_ops_report_reads_it()
    test_database_restore_drill_verifies_latest_backup_manifest()
    test_database_backup_service_reuses_recent_verified_full_backup()
    test_database_backup_service_reports_copy_progress()
    test_database_backup_service_reuses_recent_existing_full_artifact_without_manifest()
    test_database_backup_service_writes_and_prunes_by_gfs_tier()
    test_database_backup_service_adhoc_prune_does_not_cross_tiers()
    test_database_backup_health_detects_recent_unmanifested_artifact()
    test_database_backup_health_fails_missing_manifest_artifact()
    test_database_backup_health_parses_process_elapsed_time()
    print("database backup service tests passed")
