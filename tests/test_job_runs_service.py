#!/usr/bin/env python3
"""Tests for durable cron/operator job run ledger."""

from __future__ import annotations

import fcntl
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.job_runs_repo import JobRunsRepository  # noqa: E402
from services.job_runs_service import JobRunsService  # noqa: E402


def _load_job_runner_module():
    spec = importlib.util.spec_from_file_location(
        "job_runner_under_test",
        ROOT / "scripts" / "job_runner.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
                str(ROOT / "scripts" / "job_runner.py"),
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


def test_job_runner_infers_rows_and_warnings_from_log_output():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        log_path = tmp_path / "job.log"

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "job_runner.py"),
                "--job-name",
                "row_job",
                "--log-file",
                str(log_path),
                "--db-path",
                str(db_path),
                "--",
                sys.executable,
                "-c",
                "print('Inserted 12 daily_symbol_events rows.'); print('[WARN] fallback used')",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        rows = _rows(db_path)
        assert len(rows) == 1
        assert rows[0]["rows_written"] == 12
        assert rows[0]["warnings_count"] == 1


def test_job_runner_infers_rows_from_common_runtime_log_patterns():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        log_path = tmp_path / "job.log"

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "job_runner.py"),
                "--job-name",
                "poll_job",
                "--log-file",
                str(log_path),
                "--db-path",
                str(db_path),
                "--",
                sys.executable,
                "-c",
                (
                    "print('Poll complete - checked: 12, updated: 4, skipped: 8'); "
                    "print('Wrote refreshed market_context.json (37 symbols)')"
                ),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        rows = _rows(db_path)
        assert len(rows) == 1
        assert rows[0]["rows_written"] == 37


def test_job_runner_logs_lock_skipped_run_without_touching_ledger():
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
                    str(ROOT / "scripts" / "job_runner.py"),
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
        assert not db_path.exists()
        assert "lock-busy: unit_job skipped" in log_path.read_text()


def test_job_runner_times_out_long_running_job():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "jobs.db"
        log_path = tmp_path / "job.log"

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "job_runner.py"),
                "--job-name",
                "timeout_job",
                "--log-file",
                str(log_path),
                "--db-path",
                str(db_path),
                "--timeout-seconds",
                "1",
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 124, result.stderr
        text = log_path.read_text()
        assert "job-timeout: timeout_job exceeded 1s" in text
        assert "job-finish: timeout_job exit_code=124" in text
        rows = _rows(db_path)
        assert len(rows) == 1
        assert rows[0]["job_name"] == "timeout_job"
        assert rows[0]["exit_code"] == 124


def test_job_runner_ledger_failure_is_best_effort():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        log_path = tmp_path / "job.log"
        lock_path = tmp_path / "unit.lock"
        job_runner = _load_job_runner_module()

        class FakeService:
            def build_record(self, **kwargs):
                return kwargs

            def record_run(self, record):
                raise sqlite3.OperationalError("database is locked")

        original_builder = job_runner.build_default_job_runs_service
        job_runner.build_default_job_runs_service = lambda: FakeService()
        try:
            result = job_runner.main(
                [
                    "--job-name",
                    "ledger_failure_job",
                    "--lock-file",
                    str(lock_path),
                    "--log-file",
                    str(log_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('job still completed')",
                ]
            )
        finally:
            job_runner.build_default_job_runs_service = original_builder

        assert result == 0
        text = log_path.read_text()
        assert "job still completed" in text
        assert "job-finish: ledger_failure_job exit_code=0" in text
        assert "job-ledger-write-failed: ledger_failure_job" in text

        with lock_path.open("w") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


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
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
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
        assert payload.summary["zero_row_successes"] == 0
        assert payload.summary["unknown_row_successes"] == 0
        assert payload.summary["consecutive_failure_jobs"] == []
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


def test_service_excludes_legacy_retry_jobs_from_runtime_health():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "run_after_close_learning_retry_final",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 1,
                "lock_acquired": True,
                "command": "legacy retry",
            }
        )
        repo.insert_run(
            {
                "job_name": "run_after_close_learning",
                "started_at": "2026-05-31T14:05:00+00:00",
                "finished_at": "2026-05-31T14:05:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 0,
                "lock_acquired": True,
                "rows_written": 1,
                "command": "scheduled",
            }
        )

        svc = JobRunsService(repo)
        payload = svc.health_payload(target_date="2026-05-31")
        status_rows = svc.job_status_table()

        assert payload.summary["total_runs"] == 1
        assert payload.summary["failed"] == 0
        assert payload.summary["clean"] is True
        assert [row["job_name"] for row in status_rows] == ["run_after_close_learning"]


def test_service_builds_runtime_health_trend_payload():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "live_features",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 0,
                "lock_acquired": True,
                "rows_written": 0,
                "warnings_count": 1,
                "command": "ok",
            }
        )
        repo.insert_run(
            {
                "job_name": "live_features",
                "started_at": "2026-06-01T14:00:00+00:00",
                "finished_at": "2026-06-01T14:00:03+00:00",
                "duration_sec": 3.0,
                "exit_code": 1,
                "lock_acquired": True,
                "rows_written": 4,
                "warnings_count": 0,
                "command": "bad",
            }
        )

        payload = JobRunsService(repo).trend_payload(
            start_date="2026-05-31",
            end_date="2026-06-01",
        )

        assert payload["report_version"] == "runtime_health_trend_v1"
        assert payload["rows"] == 2
        assert payload["clean"] is False
        job = payload["jobs"][0]
        assert job["job_name"] == "live_features"
        assert job["failures"] == 1
        assert job["zero_row_successes"] == 1
        assert job["rows_written"] == 4


def test_service_runtime_health_uses_latest_job_state_for_recovered_failures():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "after_close",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 1,
                "lock_acquired": True,
                "command": "failed",
            }
        )
        repo.insert_run(
            {
                "job_name": "after_close",
                "started_at": "2026-05-31T14:05:00+00:00",
                "finished_at": "2026-05-31T14:05:03+00:00",
                "duration_sec": 3.0,
                "exit_code": 0,
                "lock_acquired": True,
                "rows_written": 1,
                "command": "recovered",
            }
        )

        svc = JobRunsService(repo)
        health = svc.health_payload(target_date="2026-05-31")
        trend = svc.trend_payload(start_date="2026-05-31", end_date="2026-05-31")

        assert health.summary["total_runs"] == 1
        assert health.summary["failed"] == 0
        assert health.summary["clean"] is True
        assert trend["rows"] == 2
        assert trend["jobs"][0]["runs"] == 2
        assert trend["jobs"][0]["failures"] == 0
        assert trend["clean"] is True


def test_service_builds_latest_job_status_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        repo = JobRunsRepository(db_path)
        repo.init_table()
        repo.insert_run(
            {
                "job_name": "old_status",
                "started_at": "2026-05-31T14:00:00+00:00",
                "finished_at": "2026-05-31T14:00:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 1,
                "lock_acquired": True,
                "rows_written": 0,
                "warnings_count": 0,
                "command": "old",
            }
        )
        repo.insert_run(
            {
                "job_name": "old_status",
                "started_at": "2026-05-31T14:05:00+00:00",
                "finished_at": "2026-05-31T14:05:02+00:00",
                "duration_sec": 2.0,
                "exit_code": 0,
                "lock_acquired": True,
                "rows_written": 4,
                "warnings_count": 1,
                "command": "new",
            }
        )
        repo.insert_run(
            {
                "job_name": "skipped_job",
                "started_at": "2026-05-31T14:06:00+00:00",
                "finished_at": "2026-05-31T14:06:00+00:00",
                "duration_sec": 0.0,
                "exit_code": None,
                "lock_acquired": False,
                "skipped_reason": "lock_busy",
                "command": "skip",
            }
        )

        rows = JobRunsService(repo).job_status_table()

        by_name = {row["job_name"]: row for row in rows}
        assert set(by_name) == {"old_status", "skipped_job"}
        assert by_name["old_status"]["status"] == "ok"
        assert by_name["old_status"]["rows_written"] == 4
        assert by_name["old_status"]["warnings_count"] == 1
        assert by_name["skipped_job"]["status"] == "skipped"


def main():
    tests = [
        test_job_runner_records_completed_run,
        test_job_runner_infers_rows_and_warnings_from_log_output,
        test_job_runner_infers_rows_from_common_runtime_log_patterns,
        test_job_runner_logs_lock_skipped_run_without_touching_ledger,
        test_job_runner_ledger_failure_is_best_effort,
        test_service_records_artifact_hash,
        test_service_builds_runtime_health_payload,
        test_service_marks_runtime_health_unclean_on_failed_job,
        test_service_excludes_legacy_retry_jobs_from_runtime_health,
        test_service_builds_runtime_health_trend_payload,
        test_service_runtime_health_uses_latest_job_state_for_recovered_failures,
        test_service_builds_latest_job_status_table,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} job run ledger tests passed.")


if __name__ == "__main__":
    main()
