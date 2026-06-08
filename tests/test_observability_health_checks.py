#!/usr/bin/env python3
"""Tests for lightweight observability health checks."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.database_backup_service import DatabaseBackupService  # noqa: E402
from repositories.job_runs_repo import JobRunsRepository  # noqa: E402
from services.job_runs_service import JobRunsService  # noqa: E402
from services.ops_checks.observability_health_checks import run_observability_health  # noqa: E402


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO sample DEFAULT VALUES")


def _record_successful_job(base_dir: Path, target_date: str) -> None:
    service = JobRunsService(JobRunsRepository(base_dir / "trades.db"))
    service.repository.init_table()
    service.repository.insert_run(
        {
            "job_name": "unit_job",
            "started_at": f"{target_date}T12:00:00+00:00",
            "finished_at": f"{target_date}T12:00:01+00:00",
            "duration_sec": 1.0,
            "exit_code": 0,
            "lock_acquired": True,
            "rows_written": 1,
            "warnings_count": 0,
            "artifact_path": None,
            "artifact_hash": None,
            "command": "unit",
        }
    )


def test_observability_health_passes_with_clean_jobs_and_verified_backup():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        target_date = "2026-06-08"
        _build_db(base_dir / "trades.db")
        _record_successful_job(base_dir, target_date)

        backup_service = DatabaseBackupService(
            base_dir=base_dir,
            backup_dir=base_dir / "backups" / "databases",
        )
        manifest = backup_service.run(db_names=["trades.db"])
        backup_service.write_manifest(manifest)

        assert run_observability_health(target_date, base_dir=base_dir) is True


def test_observability_health_warns_without_backup_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        target_date = "2026-06-08"
        _build_db(base_dir / "trades.db")
        _record_successful_job(base_dir, target_date)

        assert run_observability_health(target_date, base_dir=base_dir) is False


if __name__ == "__main__":
    test_observability_health_passes_with_clean_jobs_and_verified_backup()
    test_observability_health_warns_without_backup_manifest()
    print("observability health checks tests passed")
