#!/usr/bin/env python3
"""Bounded SQLite workload report for the live trading database.

This is an operator diagnostic, not a compaction tool.  It avoids unbounded
table scans by default and uses SQLite's progress handler to abort optional
dbstat inspection when the database is too busy or too large.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from db import DB_PATH, get_read_connection

from scripts.sqlite_checkpoint import run_checkpoint

DEFAULT_JOBS_DB_PATH = DB_PATH
DEFAULT_AUTO_BUY_JOB = "auto_buy_manager"
DEFAULT_WATCH_WRITER_JOBS = ("run_label_features", "session_momentum")
DEFAULT_WRITER_OVERLAP_DURATION_THRESHOLD_SEC = 60.0


def _bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _dbstat_top_objects(
    db_path: Path,
    *,
    limit: int,
    timeout_sec: float,
) -> tuple[list[dict[str, Any]], str | None]:
    if limit <= 0:
        return [], None
    deadline = time.monotonic() + max(0.1, timeout_sec)
    try:
        with get_read_connection(db_path) as con:

            def _abort_if_expired() -> int:
                return 1 if time.monotonic() >= deadline else 0

            con.set_progress_handler(_abort_if_expired, 20_000)
            rows = con.execute(
                """
                SELECT
                    name,
                    COUNT(*) AS pages,
                    SUM(pgsize) AS bytes
                FROM dbstat
                GROUP BY name
                ORDER BY SUM(pgsize) DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        return [], f"dbstat_unavailable_or_aborted:{exc}"
    return [
        {
            "name": str(row["name"]),
            "pages": int(row["pages"] or 0),
            "bytes": int(row["bytes"] or 0),
            "mb": round(int(row["bytes"] or 0) / 1024 / 1024, 2),
        }
        for row in rows
    ], None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _job_interval(row: dict[str, Any]) -> tuple[datetime, datetime] | None:
    started_at = _parse_dt(row.get("started_at"))
    finished_at = _parse_dt(row.get("finished_at"))
    if started_at is None or finished_at is None:
        return None
    if finished_at < started_at:
        return None
    return started_at, finished_at


def _load_job_runs_for_overlap(
    jobs_db_path: Path,
    *,
    target_date: str,
    job_names: tuple[str, ...],
) -> tuple[list[dict[str, Any]], str | None]:
    if not jobs_db_path.exists():
        return [], "jobs_db_missing"
    if not job_names:
        return [], None
    placeholders = ",".join("?" for _ in job_names)
    try:
        with get_read_connection(jobs_db_path) as con:
            exists = con.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'job_runs'
                """
            ).fetchone()
            if not exists:
                return [], "job_runs_table_missing"
            rows = con.execute(
                f"""
                SELECT
                    id,
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count
                FROM job_runs
                WHERE substr(started_at, 1, 10) = ?
                  AND job_name IN ({placeholders})
                ORDER BY started_at ASC, id ASC
                """,
                (target_date, *job_names),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], f"job_runs_unavailable:{exc}"
    return [dict(row) for row in rows], None


def _job_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "job_name": str(row["job_name"]),
        "started_at": str(row["started_at"]),
        "finished_at": str(row["finished_at"]),
        "duration_sec": round(float(row.get("duration_sec") or 0.0), 3),
        "exit_code": row.get("exit_code"),
        "lock_acquired": int(row.get("lock_acquired") or 0),
        "skipped_reason": row.get("skipped_reason"),
    }


def _writer_overlap_report(
    jobs_db_path: Path,
    *,
    target_date: str | None,
    auto_buy_job_name: str,
    watch_writer_jobs: tuple[str, ...],
    duration_threshold_sec: float,
    limit: int,
) -> dict[str, Any]:
    target_date = target_date or datetime.now(timezone.utc).date().isoformat()
    watched = tuple(dict.fromkeys(job for job in watch_writer_jobs if job))
    job_names = tuple(dict.fromkeys((auto_buy_job_name, *watched)))
    rows, warning = _load_job_runs_for_overlap(
        jobs_db_path,
        target_date=target_date,
        job_names=job_names,
    )
    auto_buy_runs = [row for row in rows if row.get("job_name") == auto_buy_job_name]
    watched_runs = [row for row in rows if row.get("job_name") in watched]

    overlaps: list[dict[str, Any]] = []
    invalid_rows = 0
    for writer in watched_runs:
        writer_interval = _job_interval(writer)
        if writer_interval is None:
            invalid_rows += 1
            continue
        writer_start, writer_end = writer_interval
        for auto_buy in auto_buy_runs:
            auto_interval = _job_interval(auto_buy)
            if auto_interval is None:
                invalid_rows += 1
                continue
            auto_start, auto_end = auto_interval
            overlap_sec = (
                min(writer_end, auto_end) - max(writer_start, auto_start)
            ).total_seconds()
            if overlap_sec <= 0:
                continue
            writer_duration = float(writer.get("duration_sec") or 0.0)
            auto_duration = float(auto_buy.get("duration_sec") or 0.0)
            overlaps.append(
                {
                    "writer_job": _job_run_summary(writer),
                    "auto_buy_job": _job_run_summary(auto_buy),
                    "overlap_sec": round(overlap_sec, 3),
                    "writer_duration_sec": round(writer_duration, 3),
                    "auto_buy_duration_sec": round(auto_duration, 3),
                    "long_running_writer": writer_duration >= duration_threshold_sec,
                }
            )

    overlaps.sort(
        key=lambda row: (
            0 if row["long_running_writer"] else 1,
            -float(row["overlap_sec"]),
            row["writer_job"]["started_at"],
        )
    )
    long_overlaps = [row for row in overlaps if row["long_running_writer"]]
    return {
        "report_version": "sqlite_writer_overlap_v1",
        "runtime_effect": "diagnostic_only_jobs_db_read",
        "jobs_db_path": str(jobs_db_path),
        "target_date": target_date,
        "auto_buy_job_name": auto_buy_job_name,
        "watched_writer_jobs": list(watched),
        "duration_threshold_sec": float(duration_threshold_sec),
        "auto_buy_runs": len(auto_buy_runs),
        "watched_runs": len(watched_runs),
        "overlap_count": len(overlaps),
        "long_running_overlap_count": len(long_overlaps),
        "invalid_timestamp_rows": invalid_rows,
        "warning": warning,
        "overlaps": overlaps[: max(0, int(limit))],
    }


def build_report(
    db_path: Path,
    *,
    dbstat_limit: int = 0,
    dbstat_timeout_sec: float = 5.0,
    jobs_db_path: Path | None = DEFAULT_JOBS_DB_PATH,
    writer_overlap_date: str | None = None,
    writer_overlap_auto_buy_job: str = DEFAULT_AUTO_BUY_JOB,
    writer_overlap_jobs: tuple[str, ...] = DEFAULT_WATCH_WRITER_JOBS,
    writer_overlap_duration_threshold_sec: float = DEFAULT_WRITER_OVERLAP_DURATION_THRESHOLD_SEC,
    writer_overlap_limit: int = 20,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    wal_path = db_path.with_name(db_path.name + "-wal")
    shm_path = db_path.with_name(db_path.name + "-shm")
    with get_read_connection(db_path) as con:
        journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        page_count = int(con.execute("PRAGMA page_count").fetchone()[0] or 0)
        page_size = int(con.execute("PRAGMA page_size").fetchone()[0] or 0)
        freelist_count = int(con.execute("PRAGMA freelist_count").fetchone()[0] or 0)
        table_count = int(
            con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
            or 0
        )

    dbstat_rows, dbstat_warning = _dbstat_top_objects(
        db_path,
        limit=dbstat_limit,
        timeout_sec=dbstat_timeout_sec,
    )
    total_bytes = page_count * page_size
    free_bytes = freelist_count * page_size
    report = {
        "report_version": "db_workload_report_v1",
        "runtime_effect": "diagnostic_only_no_schema_or_data_mutation",
        "db_path": str(db_path),
        "journal_mode": journal_mode,
        "table_count": table_count,
        "page_count": page_count,
        "page_size": page_size,
        "freelist_count": freelist_count,
        "estimated_db_bytes": total_bytes,
        "estimated_db_gb": round(total_bytes / 1024 / 1024 / 1024, 3),
        "estimated_free_bytes": free_bytes,
        "estimated_free_gb": round(free_bytes / 1024 / 1024 / 1024, 3),
        "file_bytes": _bytes(db_path),
        "wal_bytes": _bytes(wal_path),
        "shm_bytes": _bytes(shm_path),
        "dbstat_top_objects": dbstat_rows,
        "dbstat_warning": dbstat_warning,
    }
    if jobs_db_path is not None:
        report["writer_overlap"] = _writer_overlap_report(
            Path(jobs_db_path).resolve(),
            target_date=writer_overlap_date,
            auto_buy_job_name=writer_overlap_auto_buy_job,
            watch_writer_jobs=writer_overlap_jobs,
            duration_threshold_sec=writer_overlap_duration_threshold_sec,
            limit=writer_overlap_limit,
        )
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dbstat-limit", type=int, default=0)
    parser.add_argument("--dbstat-timeout-sec", type=float, default=5.0)
    parser.add_argument(
        "--jobs-db-path",
        default=str(DEFAULT_JOBS_DB_PATH),
        help="SQLite DB containing job_runs. Defaults to the trading DB used by job_runner.py.",
    )
    parser.add_argument(
        "--no-writer-overlap",
        action="store_true",
        help="Skip the jobs.db writer-overlap section.",
    )
    parser.add_argument(
        "--writer-overlap-date",
        help="Date to inspect in jobs.db, YYYY-MM-DD. Defaults to current UTC date.",
    )
    parser.add_argument("--auto-buy-job-name", default=DEFAULT_AUTO_BUY_JOB)
    parser.add_argument(
        "--watch-writer-job",
        action="append",
        dest="watch_writer_jobs",
        help=(
            "Writer job to compare against auto-buy windows. "
            "May be repeated. Defaults to run_label_features and session_momentum."
        ),
    )
    parser.add_argument(
        "--writer-overlap-duration-threshold-sec",
        type=float,
        default=DEFAULT_WRITER_OVERLAP_DURATION_THRESHOLD_SEC,
    )
    parser.add_argument("--writer-overlap-limit", type=int, default=20)
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Run a bounded WAL checkpoint after the read-only report.",
    )
    parser.add_argument(
        "--checkpoint-mode",
        default="TRUNCATE",
        choices=("PASSIVE", "FULL", "RESTART", "TRUNCATE"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path)
    report = build_report(
        db_path,
        dbstat_limit=args.dbstat_limit,
        dbstat_timeout_sec=args.dbstat_timeout_sec,
        jobs_db_path=None if args.no_writer_overlap else Path(args.jobs_db_path),
        writer_overlap_date=args.writer_overlap_date,
        writer_overlap_auto_buy_job=args.auto_buy_job_name,
        writer_overlap_jobs=tuple(args.watch_writer_jobs or DEFAULT_WATCH_WRITER_JOBS),
        writer_overlap_duration_threshold_sec=args.writer_overlap_duration_threshold_sec,
        writer_overlap_limit=args.writer_overlap_limit,
    )
    if args.checkpoint:
        report["checkpoint"] = run_checkpoint(
            db_path,
            mode=args.checkpoint_mode,
            busy_timeout_ms=5000,
            wal_autocheckpoint=1000,
            journal_size_limit=67108864,
            set_wal=False,
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print("SQLite workload report")
    print(f"  db_path            : {report['db_path']}")
    print(f"  journal_mode       : {report['journal_mode']}")
    print(f"  estimated_db_gb    : {report['estimated_db_gb']}")
    print(f"  estimated_free_gb  : {report['estimated_free_gb']}")
    print(f"  wal_bytes          : {report['wal_bytes']}")
    print(f"  shm_bytes          : {report['shm_bytes']}")
    if report["dbstat_warning"]:
        print(f"  dbstat_warning     : {report['dbstat_warning']}")
    if report["dbstat_top_objects"]:
        print()
        print("Top dbstat objects")
        for row in report["dbstat_top_objects"]:
            print(f"  {row['name']:<42} {row['mb']:>10.2f} MB")
    if "writer_overlap" in report:
        overlap = report["writer_overlap"]
        print()
        print("SQLite writer overlap")
        print(f"  jobs_db_path                    : {overlap['jobs_db_path']}")
        print(f"  target_date                     : {overlap['target_date']}")
        print(f"  watched_writer_jobs             : {', '.join(overlap['watched_writer_jobs'])}")
        print(f"  auto_buy_runs                   : {overlap['auto_buy_runs']}")
        print(f"  watched_runs                    : {overlap['watched_runs']}")
        print(f"  overlap_count                   : {overlap['overlap_count']}")
        print(f"  long_running_overlap_count      : {overlap['long_running_overlap_count']}")
        if overlap["warning"]:
            print(f"  warning                         : {overlap['warning']}")
        if overlap["overlaps"]:
            print()
            print("Writer overlaps")
            for row in overlap["overlaps"]:
                marker = "LONG" if row["long_running_writer"] else "short"
                writer = row["writer_job"]
                auto_buy = row["auto_buy_job"]
                print(
                    "  "
                    f"{marker:<5} {writer['job_name']:<24} "
                    f"writer={writer['started_at']}..{writer['finished_at']} "
                    f"auto_buy={auto_buy['started_at']}..{auto_buy['finished_at']} "
                    f"overlap_sec={row['overlap_sec']}"
                )
    if "checkpoint" in report:
        checkpoint = report["checkpoint"]
        print()
        print("Checkpoint")
        for key in ("checkpoint_mode", "busy", "log_frames", "checkpointed_frames", "wal_bytes"):
            print(f"  {key:<22}: {checkpoint.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
