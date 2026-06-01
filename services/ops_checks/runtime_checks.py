"""Runtime health checks backed by durable job_runs rows."""

from __future__ import annotations

from pathlib import Path

from repositories.job_runs_repo import JobRunsRepository
from services.job_runs_service import JobRunsService


RUNTIME_HEALTH_REPORT_VERSION = "runtime_health_v1"


def _fmt(value) -> str:
    return "-" if value is None else str(value)


def run_runtime_health(target_date: str, *, base_dir: Path, limit: int = 15) -> bool:
    print()
    print("=" * 72)
    print(f"  Runtime Job Health — {target_date}")
    print("=" * 72)
    print(f"report_version          : {RUNTIME_HEALTH_REPORT_VERSION}")

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
    print(f"zero_row_success  : {summary.get('zero_row_successes', 0)}")
    print(f"unknown_row_count : {summary.get('unknown_row_successes', 0)}")
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
    zero_row_rows = [
        row
        for row in payload.rows
        if row.get("lock_acquired") == 1
        and row.get("exit_code") == 0
        and row.get("rows_written") == 0
    ]
    unknown_row_rows = [
        row
        for row in payload.rows
        if row.get("lock_acquired") == 1
        and row.get("exit_code") == 0
        and row.get("rows_written") is None
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

    if zero_row_rows:
        print()
        print("Zero-row successes:")
        for row in zero_row_rows[:limit]:
            print(
                f"  {row['started_at']} {row['job_name']} "
                f"duration={_fmt(row['duration_sec'])}"
            )

    warning_jobs = summary.get("warning_jobs") or []
    if warning_jobs:
        print()
        print("Warnings by job:")
        for item in warning_jobs[:limit]:
            print(f"  {item['job_name']:<36} {item['warnings_count']}")

    zero_row_jobs = summary.get("zero_row_jobs") or []
    if zero_row_jobs:
        print()
        print("Zero-row successes by job:")
        for item in zero_row_jobs[:limit]:
            print(f"  {item['job_name']:<36} {item['zero_row_successes']}")

    if unknown_row_rows:
        print()
        print("Successes without row-count telemetry:")
        for row in unknown_row_rows[:limit]:
            print(
                f"  {row['started_at']} {row['job_name']} "
                f"duration={_fmt(row['duration_sec'])}"
            )

    streaks = summary.get("consecutive_failure_jobs") or []
    if streaks:
        print()
        print("Consecutive failure streaks:")
        for item in streaks[:limit]:
            print(f"  {item['job_name']:<36} {item['consecutive_failures']}")

    ok = bool(summary["clean"])
    print()
    print("[OK] runtime job ledger is clean" if ok else "[WARN] runtime job ledger has gaps or failures")
    return ok


def run_runtime_health_trend(
    start_date: str,
    *,
    end_date: str,
    base_dir: Path,
    limit: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Runtime Job Health Trend — {start_date} to {end_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    service = JobRunsService(JobRunsRepository(db_path))
    payload = service.trend_payload(start_date=start_date, end_date=end_date)
    print(f"report_version          : {payload['report_version']}")
    print(f"rows                    : {payload['rows']}")
    print(f"jobs                    : {len(payload['jobs'])}")
    if not payload["rows"]:
        print("[WARN] no job_runs rows found for this window")
        return False

    print()
    print(
        f"  {'job':<34} {'runs':>5} {'fail':>5} {'launch':>6} "
        f"{'locks':>5} {'zero':>5} {'warn':>5} {'p95':>8} {'rows':>8}"
    )
    for item in payload["jobs"][:limit]:
        print(
            f"  {item['job_name']:<34} {item['runs']:>5} "
            f"{item['failures']:>5} {item['launcher_errors']:>6} "
            f"{item['lock_skips']:>5} {item['zero_row_successes']:>5} "
            f"{item['warnings_count']:>5} {str(item['p95_duration_sec'] or '-'):>8} "
            f"{item['rows_written']:>8}"
        )

    print()
    print("[OK] runtime health trend is clean" if payload["clean"] else "[WARN] runtime health trend has failures")
    return bool(payload["clean"])
