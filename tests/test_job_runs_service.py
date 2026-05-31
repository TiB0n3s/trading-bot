#!/usr/bin/env python3
"""Tests for durable cron/operator job run ledger."""

from __future__ import annotations

import fcntl
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.job_runs_repo import JobRunsRepository
from services.job_runs_service import JobRunsService


def _rows(db_path: Path):
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute("SELECT * FROM job_runs ORDER BY id")]


def test_job_runner_records_completed_run():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        log_path = tmp_path / "job.log"

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "job_runner.py"),
                "--job-name",
                "unit_job",
                "--lock-file",
                str(tmp_path / "unit.lock"),
                "--log-file",
                str(log_path),
                "--db-path",
                str(db_path),
                "--",
                sys.executable,
                "-c",
                "print('hello job')",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        rows = _rows(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["job_name"] == "unit_job"
        assert row["exit_code"] == 0
        assert row["lock_acquired"] == 1
        assert row["skipped_reason"] is None
        assert "hello job" in log_path.read_text()
        assert "job-start: unit_job" in log_path.read_text()
        assert "job-finish: unit_job exit_code=0" in log_path.read_text()


def test_job_runner_records_lock_skipped_run():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        log_path = tmp_path / "job.log"
        lock_path = tmp_path / "unit.lock"

        with lock_path.open("w") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "job_runner.py"),
                    "--job-name",
                    "unit_job",
                    "--lock-file",
                    str(lock_path),
                    "--log-file",
                    str(log_path),
                    "--db-path",
                    str(db_path),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(7)",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

        assert result.returncode == 0, result.stderr
        rows = _rows(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["job_name"] == "unit_job"
        assert row["exit_code"] is None
        assert row["lock_acquired"] == 0
        assert row["skipped_reason"] == "lock_busy"
        assert "lock-busy: unit_job skipped" in log_path.read_text()


def test_service_records_artifact_hash():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        artifact = tmp_path / "artifact.txt"
        artifact.write_text("abc")

        service = JobRunsService(JobRunsRepository(db_path))
        record = service.build_record(
            job_name="artifact_job",
            started_at="2026-01-01T00:00:00+00:00",
            started_monotonic=0.0,
            exit_code=0,
            lock_acquired=True,
            artifact_path=str(artifact),
            command=["echo", "ok"],
        )
        service.record_run(record)

        rows = _rows(db_path)
        assert len(rows) == 1
        assert rows[0]["artifact_path"] == str(artifact)
        assert rows[0]["artifact_hash"] == (
            "ba7816bf8f01cfea414140de5dae2223"
            "b00361a396177a9cb410ff61f20015ad"
        )


def test_service_builds_runtime_health_payload():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "ok_job",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 0,
                "lock_acquired": True,
                "rows_written": 3,
                "warnings_count": 1,
                "command": "ok",
            }
        )
        repo.insert_run(
            {
                "job_name": "skipped_job",
                "started_at": "2026-05-31T14:01:00+00:00",
                "finished_at": "2026-05-31T14:01:00+00:00",
                "duration_sec": 0.0,
                "exit_code": None,
                "lock_acquired": False,
                "skipped_reason": "lock_busy",
                "command": "skip",
            }
        )

        payload = JobRunsService(repo).health_payload(target_date="2026-05-31")

        assert payload.summary["total_runs"] == 2
        assert payload.summary["distinct_jobs"] == 2
        assert payload.summary["succeeded"] == 1
        assert payload.summary["failed"] == 0
        assert payload.summary["skipped_lock_busy"] == 1
        assert payload.summary["warnings_count"] == 1
        assert payload.summary["rows_written"] == 3
        assert payload.summary["clean"] is True


def test_service_marks_runtime_health_unclean_on_failed_job():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "bad_job",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 2,
                "lock_acquired": True,
                "command": "bad",
            }
        )

        payload = JobRunsService(repo).health_payload(target_date="2026-05-31")

        assert payload.summary["failed"] == 1
        assert payload.summary["clean"] is False


def main():
    tests = [
        test_job_runner_records_completed_run,
        test_job_runner_records_lock_skipped_run,
        test_service_records_artifact_hash,
        test_service_builds_runtime_health_payload,
        test_service_marks_runtime_health_unclean_on_failed_job,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} job run ledger tests passed.")


if __name__ == "__main__":
    main()
