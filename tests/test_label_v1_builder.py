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

_LABEL_TARGET_DDL = """
CREATE TABLE labeled_setups (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER,
    future_price_60m REAL,
    ret_fwd_60m REAL,
    max_up_60m REAL,
    max_down_60m REAL,
    action_direction TEXT,
    action_mfe_60m_pct REAL,
    action_mae_60m_pct REAL
)
"""


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
            con.execute(_LABEL_TARGET_DDL)

        result = validate_feature_snapshot_contract(db_path)

        assert_equal(result["ok"], False, "contract ok")
        assert_true(
            "feature_available_at" in result["missing_feature_audit_fields"], "missing availability"
        )
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
                (
                    "2026-05-26T10:00:00",
                    "AAPL",
                    "2026-05-26T10:00:00",
                    "2026-05-26T10:00:00",
                    0,
                    "test",
                    1,
                    "test",
                ),
            )
            con.execute(_LABEL_TARGET_DDL)

        result = validate_feature_snapshot_contract(db_path)

        assert_equal(result["ok"], True, "contract ok")
        assert_equal(result["missing_feature_audit_fields"], [], "missing fields")
        assert_equal(result["missing_label_target_fields"], [], "missing label fields")
        assert_equal(result["stale_feature_snapshot_count"], 1, "stale rows")


def test_contract_blocks_missing_60m_action_targets():
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
            con.execute("CREATE TABLE labeled_setups (id INTEGER PRIMARY KEY, snapshot_id INTEGER)")

        result = validate_feature_snapshot_contract(db_path)

        assert_equal(result["ok"], False, "contract ok")
        assert_true("ret_fwd_60m" in result["missing_label_target_fields"], "missing 60m return")
        assert_true(
            "action_mfe_60m_pct" in result["missing_label_target_fields"],
            "missing action-aware mfe",
        )


def main():
    tests = [
        test_contract_blocks_missing_audit_fields,
        test_contract_accepts_audit_fields_and_counts_stale_rows,
        test_contract_blocks_missing_60m_action_targets,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} label v1 builder tests passed.")


if __name__ == "__main__":
    main()
