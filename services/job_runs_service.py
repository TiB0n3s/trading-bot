"""Job run ledger service used by cron/operator wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Any, Sequence

from repositories.job_runs_repo import JobRunsRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact_hash(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None

    digest = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class JobRunRecord:
    job_name: str
    started_at: str
    finished_at: str
    duration_sec: float
    exit_code: int | None
    lock_acquired: bool
    skipped_reason: str | None = None
    rows_written: int | None = None
    warnings_count: int | None = None
    artifact_path: str | None = None
    artifact_hash: str | None = None
    command: str | None = None

    def to_row(self) -> dict:
        return {
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            "exit_code": self.exit_code,
            "lock_acquired": self.lock_acquired,
            "skipped_reason": self.skipped_reason,
            "rows_written": self.rows_written,
            "warnings_count": self.warnings_count,
            "artifact_path": self.artifact_path,
            "artifact_hash": self.artifact_hash,
            "command": self.command,
        }


@dataclass(frozen=True)
class JobRunsHealthPayload:
    target_date: str
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


class JobRunsService:
    def __init__(self, repository: JobRunsRepository):
        self.repository = repository

    def init_table(self) -> None:
        self.repository.init_table()

    def record_run(self, record: JobRunRecord) -> int | None:
        """Persist one job run. Fail-open because cron logging must not crash jobs."""
        try:
            self.repository.init_table()
            return self.repository.insert_run(record.to_row())
        except Exception:
            return None

    def build_record(
        self,
        *,
        job_name: str,
        started_at: str,
        started_monotonic: float,
        exit_code: int | None,
        lock_acquired: bool,
        skipped_reason: str | None = None,
        rows_written: int | None = None,
        warnings_count: int | None = None,
        artifact_path: str | None = None,
        command: Sequence[str] | None = None,
    ) -> JobRunRecord:
        finished_at = _now_iso()
        return JobRunRecord(
            job_name=job_name,
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=round(time.monotonic() - started_monotonic, 3),
            exit_code=exit_code,
            lock_acquired=lock_acquired,
            skipped_reason=skipped_reason,
            rows_written=rows_written,
            warnings_count=warnings_count,
            artifact_path=artifact_path,
            artifact_hash=_artifact_hash(artifact_path),
            command=" ".join(command) if command else None,
        )

    def recent_runs(self, *, limit: int = 50, job_name: str | None = None):
        self.repository.init_table()
        return self.repository.recent_runs(limit=limit, job_name=job_name)

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        idx = int(round((len(ordered) - 1) * pct))
        return ordered[max(0, min(idx, len(ordered) - 1))]

    def health_payload(
        self,
        *,
        target_date: str,
        limit: int | None = None,
    ) -> JobRunsHealthPayload:
        self.repository.init_table()
        rows = [dict(row) for row in self.repository.runs_for_date(target_date, limit=limit)]
        durations = [
            float(row["duration_sec"])
            for row in rows
            if row.get("duration_sec") is not None
        ]
        job_names = {row.get("job_name") for row in rows if row.get("job_name")}
        succeeded = [
            row
            for row in rows
            if row.get("lock_acquired") == 1 and row.get("exit_code") == 0
        ]
        failed = [
            row
            for row in rows
            if row.get("lock_acquired") == 1
            and row.get("exit_code") not in (0, None)
        ]
        launcher_errors = [
            row
            for row in rows
            if row.get("lock_acquired") == 1
            and row.get("exit_code") is None
            and not row.get("skipped_reason")
        ]
        skipped_lock = [
            row
            for row in rows
            if row.get("lock_acquired") == 0
            and row.get("skipped_reason") == "lock_busy"
        ]
        zero_row_successes = [
            row
            for row in succeeded
            if row.get("rows_written") == 0
        ]
        unknown_row_successes = [
            row
            for row in succeeded
            if row.get("rows_written") is None
        ]
        warnings = sum(int(row.get("warnings_count") or 0) for row in rows)
        rows_written = sum(int(row.get("rows_written") or 0) for row in rows)

        consecutive_failure_rows: list[dict[str, Any]] = []
        warning_rows: list[dict[str, Any]] = []
        zero_row_job_rows: list[dict[str, Any]] = []
        for job_name in sorted(job_names):
            job_rows = [row for row in rows if row.get("job_name") == job_name]
            job_warning_count = sum(int(row.get("warnings_count") or 0) for row in job_rows)
            if job_warning_count:
                warning_rows.append({
                    "job_name": job_name,
                    "warnings_count": job_warning_count,
                })
            job_zero_row_count = sum(
                1
                for row in job_rows
                if row.get("lock_acquired") == 1
                and row.get("exit_code") == 0
                and row.get("rows_written") == 0
            )
            if job_zero_row_count:
                zero_row_job_rows.append({
                    "job_name": job_name,
                    "zero_row_successes": job_zero_row_count,
                })
            streak = 0
            for row in reversed(job_rows):
                if row.get("lock_acquired") != 1:
                    continue
                failed_run = (
                    row.get("exit_code") not in (0, None)
                    or (
                        row.get("exit_code") is None
                        and not row.get("skipped_reason")
                    )
                )
                if failed_run:
                    streak += 1
                    continue
                break
            if streak:
                consecutive_failure_rows.append({
                    "job_name": job_name,
                    "consecutive_failures": streak,
                })

        summary = {
            "total_runs": len(rows),
            "distinct_jobs": len(job_names),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "launcher_errors": len(launcher_errors),
            "skipped_lock_busy": len(skipped_lock),
            "zero_row_successes": len(zero_row_successes),
            "unknown_row_successes": len(unknown_row_successes),
            "warnings_count": warnings,
            "rows_written": rows_written,
            "p50_duration_sec": self._percentile(durations, 0.50),
            "p95_duration_sec": self._percentile(durations, 0.95),
            "consecutive_failure_jobs": consecutive_failure_rows,
            "warning_jobs": warning_rows,
            "zero_row_jobs": zero_row_job_rows,
            "clean": bool(rows) and not failed and not launcher_errors,
        }
        return JobRunsHealthPayload(
            target_date=target_date,
            rows=rows,
            summary=summary,
        )

    def trend_payload(self, *, start_date: str, end_date: str) -> dict[str, Any]:
        self.repository.init_table()
        rows = [dict(row) for row in self.repository.runs_between(start_date, end_date)]
        by_job: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_job.setdefault(str(row.get("job_name") or "unknown"), []).append(row)

        jobs = []
        for job_name, job_rows in sorted(by_job.items()):
            durations = [
                float(row["duration_sec"])
                for row in job_rows
                if row.get("duration_sec") is not None
            ]
            failures = [
                row
                for row in job_rows
                if row.get("lock_acquired") == 1
                and row.get("exit_code") not in (0, None)
            ]
            launcher_errors = [
                row
                for row in job_rows
                if row.get("lock_acquired") == 1
                and row.get("exit_code") is None
                and not row.get("skipped_reason")
            ]
            skipped = [
                row
                for row in job_rows
                if row.get("lock_acquired") == 0
                or row.get("skipped_reason") == "lock_busy"
            ]
            zero_rows = [
                row
                for row in job_rows
                if row.get("lock_acquired") == 1
                and row.get("exit_code") == 0
                and row.get("rows_written") == 0
            ]
            jobs.append({
                "job_name": job_name,
                "runs": len(job_rows),
                "failures": len(failures),
                "launcher_errors": len(launcher_errors),
                "lock_skips": len(skipped),
                "zero_row_successes": len(zero_rows),
                "warnings_count": sum(int(row.get("warnings_count") or 0) for row in job_rows),
                "rows_written": sum(int(row.get("rows_written") or 0) for row in job_rows),
                "p95_duration_sec": self._percentile(durations, 0.95),
            })
        return {
            "report_version": "runtime_health_trend_v1",
            "start_date": start_date,
            "end_date": end_date,
            "rows": len(rows),
            "jobs": jobs,
            "clean": bool(rows)
            and not any(item["failures"] or item["launcher_errors"] for item in jobs),
        }


    def job_status_table(self) -> list[dict[str, Any]]:
        """Return one summary row per job: name, last run time, status, duration."""
        self.repository.init_table()
        rows = self.repository.last_run_per_job()
        now = datetime.now(timezone.utc)
        result = []
        for row in rows:
            row = dict(row)
            started = row.get("started_at") or ""
            age_min: float | None = None
            if started:
                try:
                    dt = datetime.fromisoformat(started).replace(tzinfo=timezone.utc)
                    age_min = (now - dt).total_seconds() / 60
                except Exception:
                    pass
            if row.get("lock_acquired") == 0 or row.get("skipped_reason"):
                status = "skipped"
            elif row.get("exit_code") == 0:
                status = "ok"
            elif row.get("exit_code") is None:
                status = "running?" if age_min is not None and age_min < 10 else "unknown"
            else:
                status = "FAIL"
            result.append({
                "job_name": row.get("job_name"),
                "started_at": started,
                "age_min": round(age_min, 1) if age_min is not None else None,
                "duration_sec": row.get("duration_sec"),
                "exit_code": row.get("exit_code"),
                "rows_written": row.get("rows_written"),
                "warnings_count": row.get("warnings_count"),
                "status": status,
            })
        return result


def build_default_job_runs_service() -> JobRunsService:
    return JobRunsService(JobRunsRepository())
