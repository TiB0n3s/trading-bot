#!/usr/bin/env python3
"""Tests for bounded SQLite workload diagnostics."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.db_workload_report import build_report  # noqa: E402


def test_db_workload_report_reads_basic_size_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            con.execute("INSERT INTO sample (value) VALUES ('x')")

        report = build_report(db_path, dbstat_limit=3, dbstat_timeout_sec=1.0)

        assert report["report_version"] == "db_workload_report_v1"
        assert report["table_count"] == 1
        assert report["page_count"] > 0
        assert report["estimated_db_bytes"] > 0
        assert report["dbstat_warning"] is None
        assert any(row["name"] == "sample" for row in report["dbstat_top_objects"])


def test_db_workload_report_flags_long_writer_overlap_with_auto_buy():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        jobs_db_path = Path(tmp) / "jobs.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        with sqlite3.connect(jobs_db_path) as con:
            con.execute(
                """
                CREATE TABLE job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_sec REAL NOT NULL,
                    exit_code INTEGER,
                    lock_acquired INTEGER NOT NULL,
                    skipped_reason TEXT,
                    rows_written INTEGER,
                    warnings_count INTEGER
                )
                """
            )
            con.executemany(
                """
                INSERT INTO job_runs (
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "auto_buy_manager",
                        "2026-06-18T14:00:00+00:00",
                        "2026-06-18T14:00:40+00:00",
                        40.0,
                        0,
                        1,
                        None,
                        None,
                        0,
                    ),
                    (
                        "run_label_features",
                        "2026-06-18T14:00:20+00:00",
                        "2026-06-18T14:02:40+00:00",
                        140.0,
                        0,
                        1,
                        None,
                        None,
                        0,
                    ),
                    (
                        "session_momentum",
                        "2026-06-18T14:10:00+00:00",
                        "2026-06-18T14:10:10+00:00",
                        10.0,
                        0,
                        1,
                        None,
                        None,
                        0,
                    ),
                ],
            )

        report = build_report(
            db_path,
            jobs_db_path=jobs_db_path,
            writer_overlap_date="2026-06-18",
            writer_overlap_jobs=("run_label_features", "session_momentum"),
            writer_overlap_duration_threshold_sec=60.0,
        )

        overlap = report["writer_overlap"]
        assert overlap["auto_buy_runs"] == 1
        assert overlap["watched_runs"] == 2
        assert overlap["overlap_count"] == 1
        assert overlap["long_running_overlap_count"] == 1
        assert overlap["overlaps"][0]["writer_job"]["job_name"] == "run_label_features"
        assert overlap["overlaps"][0]["overlap_sec"] == 20.0


if __name__ == "__main__":
    test_db_workload_report_reads_basic_size_metadata()
    test_db_workload_report_flags_long_writer_overlap_with_auto_buy()
    print("db workload report tests passed")
