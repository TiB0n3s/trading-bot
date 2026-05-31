#!/usr/bin/env python3
"""Tests for runtime/offline ML feature parity metadata."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import ensure_decision_snapshots_table
from ml_platform.dataset_builder import ROW_COLUMNS
from ml_platform.feature_parity_contract import (
    LIVE_DECISION_ML_FEATURE_PARITY,
    RUNTIME_SNAPSHOT_FEATURE_FIELDS,
)


def _table_columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as con:
        return {
            row[1]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }


def test_ml_live_feature_names_match_runtime_snapshot_and_offline_export():
    offline_columns = set(ROW_COLUMNS)
    runtime_fields = set(RUNTIME_SNAPSHOT_FEATURE_FIELDS)

    missing_offline = [
        spec.offline_export_field
        for spec in LIVE_DECISION_ML_FEATURE_PARITY
        if spec.offline_export_field not in offline_columns
    ]
    missing_runtime = [
        spec.runtime_snapshot_field
        for spec in LIVE_DECISION_ML_FEATURE_PARITY
        if spec.runtime_snapshot_field not in runtime_fields
    ]
    mismatched_names = [
        spec.field
        for spec in LIVE_DECISION_ML_FEATURE_PARITY
        if not (
            spec.field
            == spec.runtime_snapshot_field
            == spec.offline_export_field
        )
    ]

    assert not missing_offline, missing_offline
    assert not missing_runtime, missing_runtime
    assert not mismatched_names, mismatched_names


def test_ml_live_feature_contract_documents_null_and_pit_semantics():
    offenders = [
        spec.field
        for spec in LIVE_DECISION_ML_FEATURE_PARITY
        if not spec.null_semantics
        or not spec.point_in_time_cutoff
        or spec.point_in_time_cutoff in ("unknown", "todo")
    ]
    assert not offenders, offenders


def test_decision_snapshot_table_contains_parity_fields_after_ensure():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")

        ensure_decision_snapshots_table(db_path)
        columns = _table_columns(db_path, "decision_snapshots")
        required = {
            spec.runtime_snapshot_field
            for spec in LIVE_DECISION_ML_FEATURE_PARITY
        }
        assert required <= columns, sorted(required - columns)


def main():
    tests = [
        test_ml_live_feature_names_match_runtime_snapshot_and_offline_export,
        test_ml_live_feature_contract_documents_null_and_pit_semantics,
        test_decision_snapshot_table_contains_parity_fields_after_ensure,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} feature parity contract tests passed.")


if __name__ == "__main__":
    main()
