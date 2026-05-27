#!/usr/bin/env python3
"""Tests for the formal label v1 builder contract."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from label_v1_builder import validate_feature_snapshot_contract


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def test_contract_blocks_missing_audit_fields():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE feature_snapshots (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT
                )
                """
            )

        result = validate_feature_snapshot_contract(db_path)

        assert_equal(result["ok"], False, "contract ok")
        assert_true("feature_available_at" in result["missing_feature_audit_fields"], "missing availability")
        assert_true("is_stale" in result["missing_feature_audit_fields"], "missing stale flag")


def test_contract_accepts_audit_fields_and_counts_stale_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE feature_snapshots (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    feature_available_at TEXT,
                    feature_generated_at TEXT,
                    feature_age_seconds REAL,
                    source TEXT,
                    is_stale INTEGER,
                    staleness_reason TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO feature_snapshots (
                    timestamp, symbol, feature_available_at,
                    feature_generated_at, feature_age_seconds,
                    source, is_stale, staleness_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("2026-05-26T10:00:00", "AAPL", "2026-05-26T10:00:00", "2026-05-26T10:00:00", 0, "test", 1, "test"),
            )

        result = validate_feature_snapshot_contract(db_path)

        assert_equal(result["ok"], True, "contract ok")
        assert_equal(result["missing_feature_audit_fields"], [], "missing fields")
        assert_equal(result["stale_feature_snapshot_count"], 1, "stale rows")


def main():
    tests = [
        test_contract_blocks_missing_audit_fields,
        test_contract_accepts_audit_fields_and_counts_stale_rows,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} label v1 builder tests passed.")


if __name__ == "__main__":
    main()
