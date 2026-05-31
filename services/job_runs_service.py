"""Job run ledger service used by cron/operator wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Sequence

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


def build_default_job_runs_service() -> JobRunsService:
    return JobRunsService(JobRunsRepository())
