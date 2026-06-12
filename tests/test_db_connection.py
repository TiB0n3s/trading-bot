#!/usr/bin/env python3
"""Tests for shared SQLite connection behavior."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402
from sqlite_checkpoint import run_checkpoint  # noqa: E402


class _FakeConnection:
    def __init__(self, error: sqlite3.OperationalError):
        self.error = error
        self.calls: list[str] = []

    def execute(self, sql: str):
        self.calls.append(sql)
        raise self.error


def test_configure_journal_mode_tolerates_database_locked_error():
    con = _FakeConnection(sqlite3.OperationalError("database is locked"))
    old_mode = db.SQLITE_JOURNAL_MODE
    db.SQLITE_JOURNAL_MODE = "DELETE"
    try:
        db._configure_journal_mode(con)  # type: ignore[arg-type]
    finally:
        db.SQLITE_JOURNAL_MODE = old_mode

    assert con.calls == ["PRAGMA journal_mode=DELETE"]


def test_configure_runtime_pragmas_sets_bounded_wal_controls():
    class _PragmaConnection:
        def __init__(self):
            self.calls: list[str] = []

        def execute(self, sql: str):
            self.calls.append(sql)

    con = _PragmaConnection()
    old_sync = db.SQLITE_SYNCHRONOUS
    old_checkpoint = db.SQLITE_WAL_AUTOCHECKPOINT
    old_limit = db.SQLITE_JOURNAL_SIZE_LIMIT
    db.SQLITE_SYNCHRONOUS = "NORMAL"
    db.SQLITE_WAL_AUTOCHECKPOINT = 1000
    db.SQLITE_JOURNAL_SIZE_LIMIT = 67108864
    try:
        db._configure_runtime_pragmas(con)  # type: ignore[arg-type]
    finally:
        db.SQLITE_SYNCHRONOUS = old_sync
        db.SQLITE_WAL_AUTOCHECKPOINT = old_checkpoint
        db.SQLITE_JOURNAL_SIZE_LIMIT = old_limit

    assert con.calls == [
        "PRAGMA synchronous=NORMAL",
        "PRAGMA wal_autocheckpoint=1000",
        "PRAGMA journal_size_limit=67108864",
    ]


def test_configure_journal_mode_reraises_non_lock_errors():
    con = _FakeConnection(sqlite3.OperationalError("disk I/O error"))
    old_mode = db.SQLITE_JOURNAL_MODE
    db.SQLITE_JOURNAL_MODE = "DELETE"

    try:
        try:
            db._configure_journal_mode(con)  # type: ignore[arg-type]
        finally:
            db.SQLITE_JOURNAL_MODE = old_mode
    except sqlite3.OperationalError as exc:
        assert "disk I/O error" in str(exc)
    else:
        raise AssertionError("expected non-lock journal setup failure to be raised")


def test_configure_journal_mode_skips_empty_mode():
    con = _FakeConnection(sqlite3.OperationalError("should not be called"))
    old_mode = db.SQLITE_JOURNAL_MODE
    db.SQLITE_JOURNAL_MODE = ""
    try:
        db._configure_journal_mode(con)  # type: ignore[arg-type]
    finally:
        db.SQLITE_JOURNAL_MODE = old_mode

    assert con.calls == []


def test_sqlite_checkpoint_sets_wal_and_reports_sidecars():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "unit.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
            con.execute("INSERT INTO t (value) VALUES ('a')")

        result = run_checkpoint(
            db_path,
            mode="TRUNCATE",
            busy_timeout_ms=5000,
            wal_autocheckpoint=1000,
            journal_size_limit=67108864,
            set_wal=True,
        )

        assert result["db_path"] == str(db_path)
        assert result["journal_mode"] == "wal"
        assert result["checkpoint_mode"] == "TRUNCATE"
        assert result["wal_bytes"] >= 0


def main():
    tests = [
        test_configure_journal_mode_tolerates_database_locked_error,
        test_configure_runtime_pragmas_sets_bounded_wal_controls,
        test_configure_journal_mode_reraises_non_lock_errors,
        test_configure_journal_mode_skips_empty_mode,
        test_sqlite_checkpoint_sets_wal_and_reports_sidecars,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} DB connection tests passed.")


if __name__ == "__main__":
    main()
