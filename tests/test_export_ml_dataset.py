#!/usr/bin/env python3
"""Tests for ML dataset export label filtering."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from export_ml_dataset import _exclusion_counts, training_rows


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_training_rows_default_complete_horizon_only():
    rows = [
        {"label_horizon_status": "complete", "symbol": "AAPL"},
        {"label_horizon_status": "partial_near_close", "symbol": "MSFT"},
        {"label_horizon_status": "unlabeled", "symbol": "NVDA"},
        {"label_horizon_status": None, "symbol": "META"},
    ]

    filtered = training_rows(rows, include_incomplete_labels=False)
    assert_equal([r["symbol"] for r in filtered], ["AAPL"], "complete-only rows")


def test_training_rows_audit_mode_keeps_all_statuses():
    rows = [
        {"label_horizon_status": "complete", "symbol": "AAPL"},
        {"label_horizon_status": "partial_near_close", "symbol": "MSFT"},
        {"label_horizon_status": "unlabeled", "symbol": "NVDA"},
    ]

    filtered = training_rows(rows, include_incomplete_labels=True)
    assert_equal(filtered, rows, "audit rows")


def test_exclusion_counts_keep_horizon_reasons():
    rows = [
        {"label_horizon_status": "complete"},
        {"label_horizon_status": "partial_near_close"},
        {"label_horizon_status": "partial_near_close"},
        {"label_horizon_status": "incomplete"},
        {"label_horizon_status": None},
    ]

    counts = _exclusion_counts(rows)
    assert_equal(
        counts,
        {"partial_near_close": 2, "incomplete": 1, "unlabeled": 1},
        "exclusion counts",
    )


if __name__ == "__main__":
    test_training_rows_default_complete_horizon_only()
    print("[OK] test_training_rows_default_complete_horizon_only")
    test_training_rows_audit_mode_keeps_all_statuses()
    print("[OK] test_training_rows_audit_mode_keeps_all_statuses")
    test_exclusion_counts_keep_horizon_reasons()
    print("[OK] test_exclusion_counts_keep_horizon_reasons")
    print("\nAll 3 ML dataset export tests passed.")
