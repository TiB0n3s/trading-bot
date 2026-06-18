#!/usr/bin/env python3
"""Tests for ML dataset export label filtering."""

from __future__ import annotations

import sys
import tempfile
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import export_ml_dataset
from export_ml_dataset import BASE_COLUMNS, _exclusion_counts, training_rows, write_csv_streaming


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


def test_write_csv_streaming_tracks_counts_without_source_list():
    original_stream_rows = export_ml_dataset.stream_rows
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "dataset.csv"
        rows = []
        for status, symbol in (("complete", "AAPL"), ("partial_near_close", "MSFT")):
            row = {col: None for col in BASE_COLUMNS}
            row["label_horizon_status"] = status
            row["symbol"] = symbol
            row["outcome_label"] = "win" if status == "complete" else None
            rows.append(row)

        def fake_stream_rows(args, row_callback):  # noqa: ARG001
            for row in rows:
                row_callback(row)

        try:
            export_ml_dataset.stream_rows = fake_stream_rows
            path, stats = write_csv_streaming(
                Namespace(
                    output=str(output),
                    include_incomplete_labels=False,
                )
            )
        finally:
            export_ml_dataset.stream_rows = original_stream_rows

        assert_equal(path, output, "output path")
        assert_equal(stats["source_rows"], 2, "source rows")
        assert_equal(stats["export_rows"], 1, "export rows")
        assert_equal(stats["complete_horizon_rows"], 1, "complete rows")
        assert_equal(stats["exclusion_counts"], {"partial_near_close": 1}, "exclusions")
        assert_equal(stats["symbols"], ["AAPL"], "symbols")


if __name__ == "__main__":
    test_training_rows_default_complete_horizon_only()
    print("[OK] test_training_rows_default_complete_horizon_only")
    test_training_rows_audit_mode_keeps_all_statuses()
    print("[OK] test_training_rows_audit_mode_keeps_all_statuses")
    test_exclusion_counts_keep_horizon_reasons()
    print("[OK] test_exclusion_counts_keep_horizon_reasons")
    test_write_csv_streaming_tracks_counts_without_source_list()
    print("[OK] test_write_csv_streaming_tracks_counts_without_source_list")
    print("\nAll 4 ML dataset export tests passed.")
