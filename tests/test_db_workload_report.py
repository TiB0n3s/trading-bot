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


if __name__ == "__main__":
    test_db_workload_report_reads_basic_size_metadata()
    print("db workload report tests passed")
