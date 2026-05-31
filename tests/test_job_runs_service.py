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


def main():
    tests = [
        test_job_runner_records_completed_run,
        test_job_runner_records_lock_skipped_run,
        test_service_records_artifact_hash,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} job run ledger tests passed.")


if __name__ == "__main__":
    main()
