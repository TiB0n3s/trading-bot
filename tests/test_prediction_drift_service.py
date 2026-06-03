#!/usr/bin/env python3
"""Tests for prediction drift automation."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.prediction_drift_repo import PredictionDriftRepository
from services.prediction_drift_service import PredictionDriftService


def _db(rows_by_date: dict[str, list[tuple[str, float, float]]]) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE daily_symbol_predictions (
                market_date TEXT,
                symbol TEXT,
                prediction_score REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE strong_day_participation (
                market_date TEXT,
                symbol TEXT,
                session_return_pct REAL
            )
            """
        )
        for market_date, rows in rows_by_date.items():
            for symbol, score, outcome in rows:
                con.execute(
                    "INSERT INTO daily_symbol_predictions VALUES (?, ?, ?)",
                    (market_date, symbol, score),
                )
                con.execute(
                    "INSERT INTO strong_day_participation VALUES (?, ?, ?)",
                    (market_date, symbol, outcome),
                )
    return path


def _service(path: Path) -> PredictionDriftService:
    return PredictionDriftService(repository=PredictionDriftRepository(db_path=path))


def test_positive_correlation_does_not_recommend_retraining():
    path = _db(
        {
            "2026-06-01": [("A", 90, 3), ("B", 60, 1), ("C", 20, -1)],
            "2026-06-02": [("A", 80, 2), ("B", 50, 1), ("C", 10, -2)],
            "2026-06-03": [("A", 70, 2), ("B", 40, 0), ("C", 10, -1)],
        }
    )
    report = _service(path).correlation_report(
        target_date="2026-06-03",
        sessions=3,
        bad_session_limit=3,
    ).to_dict()

    assert report["warning"] is False
    assert report["retraining_recommended"] is False
    assert report["bad_session_count"] == 0
    assert report["average_correlation"] and report["average_correlation"] > 0


def test_flat_or_negative_correlation_recommends_retraining_after_limit():
    path = _db(
        {
            "2026-06-01": [("A", 90, -2), ("B", 60, 0), ("C", 20, 3)],
            "2026-06-02": [("A", 90, -1), ("B", 60, 0), ("C", 20, 2)],
            "2026-06-03": [("A", 80, -3), ("B", 50, 0), ("C", 10, 1)],
        }
    )
    report = _service(path).correlation_report(
        target_date="2026-06-03",
        sessions=3,
        bad_session_limit=3,
    ).to_dict()

    assert report["warning"] is True
    assert report["retraining_recommended"] is True
    assert report["bad_session_count"] == 3


def test_insufficient_pairs_are_reported_without_crashing():
    path = _db({"2026-06-03": [("A", 90, 1)]})
    report = _service(path).correlation_report(
        target_date="2026-06-03",
        sessions=1,
        min_pairs_per_session=3,
    ).to_dict()

    assert report["warning"] is False
    assert report["valid_session_count"] == 0
    assert report["date_scores"][0]["status"] == "insufficient_pairs"


def main():
    tests = [
        test_positive_correlation_does_not_recommend_retraining,
        test_flat_or_negative_correlation_recommends_retraining_after_limit,
        test_insufficient_pairs_are_reported_without_crashing,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} prediction drift tests passed.")


if __name__ == "__main__":
    main()
