#!/usr/bin/env python3
"""Tests for shared SQLite connection behavior."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402


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


def main():
    tests = [
        test_configure_journal_mode_tolerates_database_locked_error,
        test_configure_journal_mode_reraises_non_lock_errors,
        test_configure_journal_mode_skips_empty_mode,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} DB connection tests passed.")


if __name__ == "__main__":
    main()
