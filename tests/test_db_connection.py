#!/usr/bin/env python3
"""Tests for shared SQLite connection behavior."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import _enable_wal_if_available  # noqa: E402


class _FakeConnection:
    def __init__(self, error: sqlite3.OperationalError):
        self.error = error
        self.calls: list[str] = []

    def execute(self, sql: str):
        self.calls.append(sql)
        raise self.error


def test_enable_wal_tolerates_database_locked_error():
    con = _FakeConnection(sqlite3.OperationalError("database is locked"))

    _enable_wal_if_available(con)  # type: ignore[arg-type]

    assert con.calls == ["PRAGMA journal_mode=WAL"]


def test_enable_wal_reraises_non_lock_errors():
    con = _FakeConnection(sqlite3.OperationalError("disk I/O error"))

    try:
        _enable_wal_if_available(con)  # type: ignore[arg-type]
    except sqlite3.OperationalError as exc:
        assert "disk I/O error" in str(exc)
    else:
        raise AssertionError("expected non-lock WAL setup failure to be raised")


def main():
    tests = [
        test_enable_wal_tolerates_database_locked_error,
        test_enable_wal_reraises_non_lock_errors,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} DB connection tests passed.")


if __name__ == "__main__":
    main()
