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


def build_report(
    db_path: Path,
    *,
    dbstat_limit: int = 0,
    dbstat_timeout_sec: float = 5.0,
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
    return {
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dbstat-limit", type=int, default=0)
    parser.add_argument("--dbstat-timeout-sec", type=float, default=5.0)
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
    if "checkpoint" in report:
        checkpoint = report["checkpoint"]
        print()
        print("Checkpoint")
        for key in ("checkpoint_mode", "busy", "log_frames", "checkpointed_frames", "wal_bytes"):
            print(f"  {key:<22}: {checkpoint.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
