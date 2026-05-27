#!/usr/bin/env python3
"""Tests for memory-only prediction cache."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prediction_cache


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE daily_symbol_predictions (
                market_date TEXT,
                symbol TEXT,
                prediction_score REAL,
                probability_of_profit REAL,
                probability_of_order REAL,
                expected_pnl REAL,
                confidence TEXT,
                sample_size INTEGER,
                reason TEXT,
                timing_score REAL,
                recommended_entry_timing TEXT,
                recommended_exit_timing TEXT,
                trend_score REAL,
                trend_label TEXT,
                trend_regime TEXT,
                trend_confidence TEXT,
                updated_at TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_symbol_predictions VALUES (
                '2026-05-27', 'AAPL', 72.5, 0.61, 0.5, 0.12,
                'medium', 42, 'fixture', 0.4, 'now', 'hold',
                0.7, 'uptrend', 'risk_on', 'medium', '2026-05-27 08:00:00'
            )
            """
        )


def test_refresh_loads_predictions_and_memory_read_does_not_query_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "predictions.db"
        make_db(db_path)

        status = prediction_cache.refresh_prediction_cache(
            market_date="2026-05-27",
            db_path=db_path,
        )
        assert_equal(status["symbol_count"], 1, "symbol count")

        db_path.unlink()
        pred = prediction_cache.get_cached_prediction("AAPL", market_date="2026-05-27")

        assert_true(pred, "cached prediction")
        assert_equal(pred["prediction_score"], 72.5, "prediction score")
        assert_equal(pred["provider"], "daily_symbol_predictions_ttl_cache", "provider")


def test_date_mismatch_returns_none_without_refresh():
    pred = prediction_cache.get_cached_prediction("AAPL", market_date="2026-05-28")
    assert_equal(pred, None, "date mismatch")


if __name__ == "__main__":
    test_refresh_loads_predictions_and_memory_read_does_not_query_db()
    print("[OK] test_refresh_loads_predictions_and_memory_read_does_not_query_db")
    test_date_mismatch_returns_none_without_refresh()
    print("[OK] test_date_mismatch_returns_none_without_refresh")
    print("\nAll 2 prediction cache tests passed.")
