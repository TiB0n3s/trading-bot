"""Runtime health checks backed by durable job_runs rows."""

from __future__ import annotations

from pathlib import Path

from repositories.job_runs_repo import JobRunsRepository
from services.job_runs_service import JobRunsService


def _fmt(value) -> str:
    return "-" if value is None else str(value)


def run_runtime_health(target_date: str, *, base_dir: Path, limit: int = 15) -> bool:
    print()
    print("=" * 72)
    print(f"  Runtime Job Health — {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    service = JobRunsService(JobRunsRepository(db_path))
    payload = service.health_payload(target_date=target_date)
    summary = payload.summary

    print(f"runs              : {summary['total_runs']}")
    print(f"distinct_jobs     : {summary['distinct_jobs']}")
    print(f"succeeded         : {summary['succeeded']}")
    print(f"failed            : {summary['failed']}")
    print(f"launcher_errors   : {summary['launcher_errors']}")
    print(f"skipped_lock_busy : {summary['skipped_lock_busy']}")
    print(f"warnings_count    : {summary['warnings_count']}")
    print(f"rows_written      : {summary['rows_written']}")
    print(f"p50_duration_sec  : {_fmt(summary['p50_duration_sec'])}")
    print(f"p95_duration_sec  : {_fmt(summary['p95_duration_sec'])}")

    if not payload.rows:
        print("[WARN] no job_runs rows found for this date; runtime cleanliness cannot be proven")
        return False

    problem_rows = [
        row
        for row in payload.rows
        if (
            row.get("lock_acquired") == 1
            and row.get("exit_code") not in (0, None)
        )
        or (
            row.get("lock_acquired") == 1
            and row.get("exit_code") is None
            and not row.get("skipped_reason")
        )
    ]
    skipped_rows = [
        row
        for row in payload.rows
        if row.get("lock_acquired") == 0
        or row.get("skipped_reason")
    ]

    if problem_rows:
        print()
        print("Problem rows:")
        for row in problem_rows[:limit]:
            print(
                f"  {row['started_at']} {row['job_name']} "
                f"exit={_fmt(row['exit_code'])} reason={_fmt(row['skipped_reason'])} "
                f"duration={_fmt(row['duration_sec'])}"
            )

    if skipped_rows:
        print()
        print("Skipped/lock rows:")
        for row in skipped_rows[:limit]:
            print(
                f"  {row['started_at']} {row['job_name']} "
                f"lock={row['lock_acquired']} reason={_fmt(row['skipped_reason'])}"
            )

    ok = bool(summary["clean"])
    print()
    print("[OK] runtime job ledger is clean" if ok else "[WARN] runtime job ledger has gaps or failures")
    return ok
