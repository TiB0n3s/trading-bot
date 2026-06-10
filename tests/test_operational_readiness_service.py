#!/usr/bin/env python3
"""Tests for aggregated operational readiness hardening checks."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.job_runs_repo import JobRunsRepository  # noqa: E402
from services.job_runs_service import JobRunsService  # noqa: E402
from services.operational_readiness_service import (  # noqa: E402
    build_operational_readiness_payload,
)

from ops.database_backup_service import DatabaseBackupService  # noqa: E402


def _build_base_dir(base_dir: Path) -> Path:
    (base_dir / "scripts").mkdir(parents=True)
    (base_dir / "ops").mkdir(parents=True)
    for rel in ("app.py", "db_migrations.py", "ops_check.py", "scripts/job_runner.py"):
        path = base_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test entrypoint\n", encoding="utf-8")
    (base_dir / "wsgi.py").write_text(
        "from app import create_app\napplication = create_app()\n",
        encoding="utf-8",
    )
    (base_dir / "ops" / "compatibility_deletion_plan.md").write_text(
        "# test plan\n",
        encoding="utf-8",
    )
    env_file = base_dir / "trading-bot.env"
    env_file.write_text("WEBHOOK_SECRET=test-secret\n", encoding="utf-8")
    env_file.chmod(0o600)
    return env_file


def _build_db(path: Path, target_date: str) -> None:
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO sample DEFAULT VALUES")
    service = JobRunsService(JobRunsRepository(path))
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


def _write_backup(base_dir: Path) -> Path:
    service = DatabaseBackupService(
        base_dir=base_dir,
        backup_dir=base_dir / "backups" / "databases",
    )
    manifest = service.run(db_names=["trades.db"], timestamp="20260610T120000Z")
    return service.write_manifest(manifest)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "WEBHOOK_SECRET": "test-secret",
            "EXECUTION_MODE": "paper",
            "LIVE_TRADING_ENABLED": "false",
            "ML_AUTHORITY_MODE": "observe_only_compare",
        }
    )
    return env


def test_operational_readiness_passes_with_core_controls_clean():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        target_date = "2026-06-10"
        env_file = _build_base_dir(base_dir)
        _build_db(base_dir / "trades.db", target_date)
        _write_backup(base_dir)

        payload = build_operational_readiness_payload(
            base_dir=base_dir,
            target_date=target_date,
            env_file=env_file,
            env=_env(),
            missing_deployment_references=[],
        )

        assert payload["ready"] is True
        assert payload["critical_failure_count"] == 0


def test_operational_readiness_blocks_stale_database_backup():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        target_date = "2026-06-10"
        env_file = _build_base_dir(base_dir)
        _build_db(base_dir / "trades.db", target_date)
        manifest = _write_backup(base_dir)
        old = time.time() - 72 * 3600
        os.utime(manifest, (old, old))

        payload = build_operational_readiness_payload(
            base_dir=base_dir,
            target_date=target_date,
            env_file=env_file,
            env=_env(),
            max_backup_age_hours=30.0,
            missing_deployment_references=[],
        )

        assert payload["ready"] is False
        backup = next(row for row in payload["checks"] if row["name"] == "database_backup")
        assert backup["status"] == "fail"


def main():
    tests = [
        test_operational_readiness_passes_with_core_controls_clean,
        test_operational_readiness_blocks_stale_database_backup,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} operational readiness tests passed.")


if __name__ == "__main__":
    main()
